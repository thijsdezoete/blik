"""
Service functions for review cycles
"""
import math
import random
from django.core import signing
from django.utils import timezone
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _, gettext_lazy
from core.email import send_email
from core.languages import recipient_language
from core.url import get_absolute_url
from notifications.log import send_logged
from datetime import timedelta
from django.db.models import F, Q
from questionnaires.models import Question
from .models import ReviewCycle, ReviewerToken


def token_language(token):
    """The language of emails to a reviewer (for the self-assessment, else the reviewee's)."""
    reviewee = token.cycle.reviewee
    return recipient_language(
        token.language,
        reviewee.language if token.category == 'self' else '',
        organization=reviewee.organization,
    )


def reviewee_language(reviewee):
    """The language of emails to a reviewee."""
    return recipient_language(reviewee.language, organization=reviewee.organization)


def self_assessment_token(cycle):
    """The cycle's self-assessment token, addressed to the reviewee; made if there is none.

    A cycle has one self-assessment, so neither the invitation nor the self link may start a
    second token. One already filled in or opened wins over one never used.
    """

    token = (
        cycle.tokens.filter(category='self')
        .order_by(F('completed_at').asc(nulls_last=True), F('claimed_at').asc(nulls_last=True), 'pk')
        .first()
    )

    if token is None:
        return ReviewerToken.objects.create(
            cycle=cycle,
            category='self',
            reviewer_email=cycle.reviewee.email.lower(),
        )

    if not token.reviewer_email:
        token.reviewer_email = cycle.reviewee.email.lower()
        token.save(update_fields=['reviewer_email'])

    return token


def derive_reviewers(reviewee):
    """
    Compute the four reviewer buckets (self/managers/peers/direct_reports) for
    a given Reviewee based on the current org-chart state.

    Rules (see plan: section 2):

        self            = {P}
        managers        = ⋃ over T where P is MEMBER  → managers(T)
        peers           = (⋃ over T where P is MEMBER  → members(T) \\ {P})
                        ∪ (⋃ over T where P is MANAGER → managers(T) \\ {P})
        direct_reports  = ⋃ over T where P is MANAGER → members(T)

    Dedup priority when the same person lands in multiple buckets:
        self > manager > direct_report > peer.

    Returns:
        dict: {
            'self': [Reviewee],
            'manager': [Reviewee],
            'peer': [Reviewee],
            'direct_report': [Reviewee],
        }
        Order within each bucket is by reviewee name for stable display.
    """
    # Local import — avoids circular imports at module load time and keeps the
    # dependency arrow from reviews → accounts.
    from accounts.models import OrgUnitMembership

    # Pull every membership of P in a single query, then fan out into two
    # queries (one per role) that fetch sibling memberships across those
    # units. Three queries total regardless of unit count.
    my_memberships = list(
        OrgUnitMembership.objects
        .filter(reviewee=reviewee)
        .values_list('unit_id', 'role')
    )

    my_member_units = [tid for tid, role in my_memberships if role == OrgUnitMembership.MEMBER]
    my_manager_units = [tid for tid, role in my_memberships if role == OrgUnitMembership.MANAGER]

    managers, peers, direct_reports = [], [], []

    if my_member_units:
        rows = (
            OrgUnitMembership.objects
            .filter(unit_id__in=my_member_units)
            .exclude(reviewee=reviewee)
            .select_related('reviewee')
        )
        for m in rows:
            if m.role == OrgUnitMembership.MANAGER:
                managers.append(m.reviewee)
            else:
                peers.append(m.reviewee)

    if my_manager_units:
        rows = (
            OrgUnitMembership.objects
            .filter(unit_id__in=my_manager_units)
            .exclude(reviewee=reviewee)
            .select_related('reviewee')
        )
        for m in rows:
            if m.role == OrgUnitMembership.MEMBER:
                direct_reports.append(m.reviewee)
            else:
                # Co-manager — counts as a peer.
                peers.append(m.reviewee)

    def _dedup_by_uuid(seq):
        """Preserve first-seen order while dropping duplicate Reviewees."""
        seen = set()
        out = []
        for r in seq:
            if r.uuid in seen:
                continue
            seen.add(r.uuid)
            out.append(r)
        return out

    managers = _dedup_by_uuid(managers)
    direct_reports = _dedup_by_uuid(direct_reports)
    peers = _dedup_by_uuid(peers)

    # Priority dedup: self > manager > direct_report > peer.
    self_uuid = reviewee.uuid
    claimed = {self_uuid}

    def _claim(seq):
        kept = []
        for r in seq:
            if r.uuid in claimed:
                continue
            claimed.add(r.uuid)
            kept.append(r)
        return kept

    managers = _claim(managers)
    direct_reports = _claim(direct_reports)
    peers = _claim(peers)

    def _by_name(seq):
        return sorted(seq, key=lambda r: (r.name or '').lower())

    return {
        'self': [reviewee],
        'manager': _by_name(managers),
        'peer': _by_name(peers),
        'direct_report': _by_name(direct_reports),
    }


def assign_tokens_to_emails(cycle, email_assignments, language=''):
    """
    Assign reviewer tokens to email addresses with smart randomization.

    Args:
        cycle: ReviewCycle instance
        email_assignments: dict like {
            'self': ['reviewee@example.com'],
            'peer': ['peer1@example.com', 'peer2@example.com'],
            'manager': ['manager@example.com'],
            'direct_report': []
        }
        language: Language for the assigned reviewers, empty for the organization's default

    Returns:
        dict: Statistics about assignments
    """
    stats = {
        'assigned': 0,
        'sent': 0,
        'errors': []
    }

    for category, emails in email_assignments.items():
        if not emails:
            continue

        # Get unassigned tokens for this category
        available_tokens = list(
            cycle.tokens.filter(
                category=category,
                reviewer_email__isnull=True
            )
        )

        if len(emails) > len(available_tokens):
            stats['errors'].append(
                _('Not enough tokens for %(category)s: need %(needed)s, have %(available)s')
                % {'category': category, 'needed': len(emails), 'available': len(available_tokens)}
            )
            continue

        # Randomly shuffle tokens to prevent any pattern linking
        random.shuffle(available_tokens)

        # Assign emails to tokens
        for email, token in zip(emails, available_tokens):
            token.reviewer_email = email.strip().lower()
            if language:
                token.language = language
            token.save()
            stats['assigned'] += 1

    return stats


# About how long a reviewer takes for one question. Optional free-text questions add nothing.
SECONDS_PER_CHOICE_QUESTION = 25
SECONDS_PER_TEXT_QUESTION = 60


def estimated_minutes(questionnaire):
    """About how many minutes the questionnaire takes, as a friendly number. None without questions.

    Up to five minutes in whole minutes, above that in steps of five.
    """

    questions = Question.objects.filter(section__questionnaire=questionnaire)
    seconds = (
        questions.exclude(question_type='text').count() * SECONDS_PER_CHOICE_QUESTION
        + questions.filter(question_type='text', required=True).count() * SECONDS_PER_TEXT_QUESTION
    )

    if not seconds:
        return None

    minutes = math.ceil(seconds / 60)
    return minutes if minutes <= 5 else 5 * math.ceil(minutes / 5)


def responded_count(token):
    """How many other reviewers of the token's cycle responded, for the reminder to that token.

    None when the count could tell who responded: below the anonymity threshold the reports
    use, or when every other reviewer responded. The reviewee's self-assessment does not count.
    """

    others = (
        token.cycle.tokens.exclude(category='self').exclude(pk=token.pk)
        .filter(Q(reviewer_email__isnull=False) | Q(claimed_at__isnull=False) | Q(completed_at__isnull=False))
    )
    responded = others.filter(completed_at__isnull=False).count()

    if responded < max(token.cycle.organization.min_responses_for_anonymity, 1) or responded == others.count():
        return None

    return responded


def send_token_email(token, reminder=False):
    """Send a reviewer the link to their feedback form, as an invitation or a reminder.

    The reviewee's own self-assessment has mails of its own: the reviewer
    mails speak of the reviewee in the third person.
    """

    cycle = token.cycle
    language = token_language(token)

    with translation.override(language):
        feedback_url = get_absolute_url('reviews:feedback_form', token.token)
        questionnaire = cycle.questionnaire.translated()
        context = {
            'reviewee_name': cycle.reviewee.name,
            'category': token.get_category_display(),
            'feedback_url': feedback_url,
            'questionnaire_name': questionnaire.name,
            'organization_name': cycle.organization.name,
            'estimated_minutes': estimated_minutes(cycle.questionnaire),
        }

        if token.category == 'self':
            context |= {
                'reviewee': cycle.reviewee,
                'cycle': cycle,
                'self_assessment_url': feedback_url,
                'is_reminder': reminder,
            }

            template = 'emails/reviewee_self_assessment'

            if reminder:
                subject = _('Your self-assessment is still open: %(questionnaire)s')
            else:
                subject = _('Your self-assessment: %(questionnaire)s')

        elif reminder:
            context['responded_count'] = responded_count(token)
            template = 'emails/reviewer_reminder'
            subject = _('Your feedback for %(name)s is still open')

        else:
            template = 'emails/reviewer_invitation'
            subject = _('Your feedback for %(name)s')

        send_email(
            subject=subject % {'questionnaire': questionnaire.name, 'name': cycle.reviewee.name},
            message=render_to_string(f'{template}.txt', context),
            recipient_list=[token.reviewer_email],
            html_message=render_to_string(f'{template}.html', context),
        )


def send_reviewer_invitations(cycle, token_ids=None):
    """
    Send email invitations to reviewers.

    Args:
        cycle: ReviewCycle instance
        token_ids: Optional list of specific token IDs to send (defaults to all with emails)

    Returns:
        dict: Statistics about emails sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    tokens = cycle.tokens.filter(reviewer_email__isnull=False)

    if token_ids:
        tokens = tokens.filter(id__in=token_ids)
    else:
        # Bulk send: only tokens that haven't been sent yet and aren't completed.
        tokens = tokens.filter(invitation_sent_at__isnull=True, completed_at__isnull=True)

    for token in tokens:
        try:
            send_token_email(token)

            # Mark as sent
            token.invitation_sent_at = timezone.now()
            token.save()

            stats['sent'] += 1

        except Exception as e:
            stats['errors'].append(_('Failed to send to %(email)s: %(error)s') % {'email': token.reviewer_email, 'error': str(e)})

    return stats


# What the reviewee is to the reviewer. The token category names the reviewer's role
# ("direct report review" = a direct report reviews), which reads backwards to the reviewer.
REVIEWER_RELATION = {
    'peer': gettext_lazy('your colleague'),
    'manager': gettext_lazy('your direct report'),
    'direct_report': gettext_lazy('your manager'),
}


def reviewer_relation(category):
    """'your manager', 'your colleague' or 'your direct report'; empty for the self-assessment."""
    return REVIEWER_RELATION.get(category, '')


def feedback_overview_url(email, organization):
    """The reviewer's personal overview of every form they have to fill in, in this organization.

    The link is signed, not stored: nothing ties the address to a token beyond the token's own
    `reviewer_email`. It does not expire, as invitations do not either.
    """

    signed = signing.dumps({'e': email.lower(), 'o': organization.id}, salt='feedback-overview')
    return get_absolute_url('reviews:feedback_overview', signed)


def send_bundle_email(email, tokens):
    """Send one reviewer a single email with every form they have to fill in."""

    organization = tokens[0].cycle.organization
    # Per questionnaire, the person's own self-assessment first, then the colleagues by name.
    tokens = sorted(tokens, key=lambda t: (t.cycle.questionnaire.name, t.category != 'self', t.cycle.reviewee.name))

    with translation.override(token_language(tokens[0])):
        items = []
        for token in tokens:
            cycle = token.cycle
            items.append({
                'reviewee_name': cycle.reviewee.name,
                'relation': reviewer_relation(token.category),
                'is_self': token.category == 'self',
                'questionnaire_name': cycle.questionnaire.translated().name,
                'feedback_url': get_absolute_url('reviews:feedback_form', token.token),
                'estimated_minutes': estimated_minutes(cycle.questionnaire),
            })

        context = {
            'organization_name': organization.name,
            'items': items,
            'total_minutes': sum(item['estimated_minutes'] or 0 for item in items) or None,
            'overview_url': feedback_overview_url(email, organization),
        }

        send_email(
            subject=_('Your feedback forms for %(organization)s') % {'organization': organization.name},
            message=render_to_string('emails/reviewer_invitation_bundle.txt', context),
            recipient_list=[email],
            html_message=render_to_string('emails/reviewer_invitation_bundle.html', context),
        )


def send_grouped_invitations(tokens):
    """Send pending invitations, one email per address.

    A person who reviews several colleagues, or one colleague on several questionnaires, gets
    one email with every link instead of one email per token. An address with a single token
    gets the usual invitation.

    Args:
        tokens: ReviewerTokens with an email, not yet invited and not completed

    Returns:
        dict: emails sent, tokens they covered, and errors
    """
    stats = {
        'sent': 0,
        'tokens': 0,
        'errors': []
    }

    groups = {}
    for token in tokens:
        groups.setdefault(token.reviewer_email.lower(), []).append(token)

    for email, group in groups.items():
        try:
            if len(group) == 1:
                send_token_email(group[0])
            else:
                send_bundle_email(email, group)

            now = timezone.now()
            for token in group:
                token.invitation_sent_at = now
                token.save(update_fields=['invitation_sent_at'])

            stats['sent'] += 1
            stats['tokens'] += len(group)

        except Exception as e:
            stats['errors'].append(_('Failed to send to %(email)s: %(error)s') % {'email': email, 'error': str(e)})

    return stats


def send_reminder_emails(cycle, token_ids=None):
    """
    Send reminder emails to reviewers who haven't completed feedback.

    Args:
        cycle: ReviewCycle instance
        token_ids: Optional list of specific token IDs to remind

    Returns:
        dict: Statistics about reminders sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    # Get incomplete tokens with emails that have been invited
    tokens = cycle.tokens.filter(
        reviewer_email__isnull=False,
        invitation_sent_at__isnull=False,
        completed_at__isnull=True
    )

    if token_ids:
        tokens = tokens.filter(id__in=token_ids)

    for token in tokens:
        try:
            send_token_email(token, reminder=True)

            # Update last reminder sent timestamp
            token.last_reminder_sent_at = timezone.now()
            token.save(update_fields=['last_reminder_sent_at'])

            stats['sent'] += 1

        except Exception as e:
            stats['errors'].append(_('Failed to send reminder to %(email)s: %(error)s') % {'email': token.reviewer_email, 'error': str(e)})

    return stats


def send_reviewee_notifications(cycle, request=None):
    """
    Send emails to reviewee when a cycle is created:
    1. Self-assessment link
    2. Invitation links to share with others

    Args:
        cycle: ReviewCycle instance
        request: Optional request object for building absolute URLs

    Returns:
        dict: Statistics about emails sent
    """
    stats = {
        'sent': 0,
        'errors': []
    }

    if not cycle.reviewee.email:
        stats['errors'].append(_('No email address for reviewee %(name)s') % {'name': cycle.reviewee.name})
        return stats

    # 1. Send the self-assessment email, unless this cycle skips self review
    if cycle.collects('self'):
        send_assessment_email(cycle, stats)

    # 2. Send the links the reviewee shares with everyone else. Self is not
    # among them: the reviewee got their own link above.
    link_categories = [c for c in cycle.active_categories if c != 'self']

    if link_categories:
        send_invitation_links_email(cycle, link_categories, stats)

    return stats


def send_assessment_email(cycle, stats):
    """Send the reviewee their self-assessment token. Records into `stats`."""
    sent = send_reviewer_invitations(cycle, token_ids=[self_assessment_token(cycle).id])
    stats['sent'] += sent['sent']
    stats['errors'] += sent['errors']


def send_invitation_links_email(cycle, categories, stats):
    """Send the reviewee the links to share, one per category. Records into `stats`."""
    try:
        with translation.override(reviewee_language(cycle.reviewee)):
            questionnaire = cycle.questionnaire.translated()
            context = {
                'reviewee': cycle.reviewee,
                'cycle': cycle,
                'questionnaire_name': questionnaire.name,
            }
            for category in categories:
                token = cycle.get_invitation_token(category)
                context[f'{category}_url'] = get_absolute_url('reviews:claim_token', invitation_token=token)

            html_message = render_to_string('emails/reviewee_invitation_links.html', context)
            text_message = render_to_string('emails/reviewee_invitation_links.txt', context)

            send_email(
                subject=_('Your links to share with reviewers: %(questionnaire)s') % {'questionnaire': questionnaire.name},
                message=text_message,
                recipient_list=[cycle.reviewee.email],
                html_message=html_message,
            )

        stats['sent'] += 1

    except Exception as e:
        stats['errors'].append(_('Failed to send invitation links email: %(error)s') % {'error': str(e)})


def send_close_check_emails(dry_run=False):
    """
    Send check-in emails to reviewees whose invite-link cycles have been
    open for at least 7 days and have at least one completed review.

    Args:
        dry_run: If True, find eligible cycles but don't send emails.

    Returns:
        dict: Statistics about emails sent
    """
    stats = {
        'sent': 0,
        'eligible': 0,
        'errors': [],
    }

    cutoff = timezone.now() - timedelta(days=7)

    cycles = ReviewCycle.objects.filter(
        status='active',
        close_check_sent_at__isnull=True,
        created_at__lte=cutoff,
    ).filter(
        tokens__completed_at__isnull=False,
    ).distinct().select_related('reviewee', 'questionnaire')

    stats['eligible'] = cycles.count()

    if dry_run:
        return stats

    for cycle in cycles:
        try:
            if not cycle.reviewee.email:
                stats['errors'].append(
                    f"No email for reviewee {cycle.reviewee.name} (cycle {cycle.uuid})"
                )
                continue

            completed_count = cycle.tokens.filter(completed_at__isnull=False).count()
            total_count = cycle.tokens.count()
            dashboard_url = get_absolute_url('review_cycle_detail', cycle_uuid=cycle.uuid)

            with translation.override(reviewee_language(cycle.reviewee)):
                questionnaire = cycle.questionnaire.translated()
                context = {
                    'reviewee': cycle.reviewee,
                    'cycle': cycle,
                    'questionnaire_name': questionnaire.name,
                    'completed_count': completed_count,
                    'total_count': total_count,
                    'dashboard_url': dashboard_url,
                }

                html_message = render_to_string('emails/cycle_close_check.html', context)
                text_message = render_to_string('emails/cycle_close_check.txt', context)

                send_logged(
                    cycle.reviewee.organization, 'cycle_close_check',
                    subject=_('Check your feedback cycle: %(questionnaire)s') % {'questionnaire': questionnaire.name},
                    message=text_message,
                    recipient_list=[cycle.reviewee.email],
                    html_message=html_message,
                )

            cycle.close_check_sent_at = timezone.now()
            cycle.save(update_fields=['close_check_sent_at'])

            stats['sent'] += 1

        except Exception as e:
            stats['errors'].append(
                f"Failed to send close check for cycle {cycle.uuid}: {str(e)}"
            )

    return stats
