"""
Lifecycle emails: onboarding nudges, the cycle summary, the next-cycle reminder and the report follow-up.

Behaviour triggers them. The selectors pick who is due today, for the daily send_lifecycle_emails command.
Closing a cycle and delivering a report call their senders directly. SentEmail records each email, so
each one goes out only once.

Anonymity: these emails hold aggregate counts only. They never name reviewers or say who responded, and
the counts for one reviewee stay out when they are below the organization's anonymity threshold.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, F, Max, Min, Q
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from accounts.models import UserProfile
from core.languages import user_language
from core.models import Organization
from core.url import get_absolute_url
from reports.models import Report
from reports.services import apply_display_anonymization, self_vs_others_gap
from reviews.models import ReviewCycle, ReviewerToken
from reviews.services import reviewee_language

from .log import send_logged
from subscriptions.utils import entitlement

from .models import SentEmail

logger = logging.getLogger(__name__)

NUDGE_AFTER = timedelta(days=2)
NUDGE_UNTIL = timedelta(days=14)          # older sign-ups and cycles get no onboarding nudge
NEXT_CYCLE_AFTER = timedelta(days=182)
NEXT_CYCLE_UNTIL = timedelta(days=240)
FOLLOW_UP_AFTER = timedelta(days=30)
FOLLOW_UP_UNTIL = timedelta(days=60)

# A reviewer token someone was invited to, or opened, or filled in. Unused invite-link tokens are not.
REACHED_REVIEWER = (
    Q(invitation_sent_at__isnull=False) | Q(claimed_at__isnull=False) | Q(completed_at__isnull=False)
)


# Selectors: who is due today.

def _sent(kind):
    return SentEmail.objects.filter(kind=kind).values('object_id')


def _may_email(organization):
    """Inactive organizations and lapsed subscriptions get no lifecycle emails."""
    return organization.is_active and entitlement(organization) != 'lapsed'


def organizations_without_cycle(now=None):
    """Organizations that signed up 2 to 14 days ago and have no review cycle yet."""
    now = now or timezone.now()
    organizations = (
        Organization.objects
        .filter(is_active=True, created_at__lte=now - NUDGE_AFTER, created_at__gt=now - NUDGE_UNTIL)
        .exclude(reviewees__review_cycles__isnull=False)
        .exclude(pk__in=_sent(SentEmail.NO_CYCLE))
    )
    return [o for o in organizations if _may_email(o)]


def organizations_without_reviewers(now=None):
    """Organizations whose first cycle started 2 to 14 days ago and that have reached no reviewer yet."""
    now = now or timezone.now()
    reached = ReviewerToken.objects.exclude(category='self').filter(REACHED_REVIEWER)
    organizations = (
        Organization.objects
        .filter(is_active=True)
        .annotate(first_cycle_at=Min('reviewees__review_cycles__created_at'))
        .filter(first_cycle_at__lte=now - NUDGE_AFTER, first_cycle_at__gt=now - NUDGE_UNTIL)
        .exclude(pk__in=reached.values('cycle__reviewee__organization'))
        .exclude(pk__in=_sent(SentEmail.NO_REVIEWERS))
    )
    return [o for o in organizations if _may_email(o)]


def organizations_due_next_cycle(now=None):
    """(organization, last closed cycle) where that cycle closed about six months ago and nothing started since.

    A cycle has no close date. Its updated_at stands in: nothing saves a completed cycle again.
    """
    now = now or timezone.now()
    organizations = (
        Organization.objects
        .filter(is_active=True)
        .annotate(
            last_closed_at=Max('reviewees__review_cycles__updated_at',
                               filter=Q(reviewees__review_cycles__status='completed')),
            last_started_at=Max('reviewees__review_cycles__created_at'),
            open_cycles=Count('reviewees__review_cycles',
                              filter=Q(reviewees__review_cycles__status='active')),
        )
        .filter(
            last_closed_at__lte=now - NEXT_CYCLE_AFTER,
            last_closed_at__gt=now - NEXT_CYCLE_UNTIL,
            last_started_at__lt=F('last_closed_at'),
            open_cycles=0,
        )
    )
    sent = set(_sent(SentEmail.NEXT_CYCLE).values_list('object_id', flat=True))

    due = []
    for organization in organizations:
        if not _may_email(organization):
            continue
        cycle = (
            ReviewCycle.objects.filter(reviewee__organization=organization, status='completed')
            .order_by('-updated_at').first()
        )
        if cycle.pk not in sent:
            due.append((organization, cycle))
    return due


def reports_due_follow_up(now=None):
    """Reports whose reviewee got the report 30 to 60 days ago and no follow-up yet."""
    now = now or timezone.now()
    delivered = SentEmail.objects.filter(
        kind=SentEmail.REPORT_READY,
        sent_at__lte=now - FOLLOW_UP_AFTER,
        sent_at__gt=now - FOLLOW_UP_UNTIL,
    ).values('object_id')
    reports = (
        Report.objects
        .filter(pk__in=delivered, available=True, access_token__isnull=False, cycle__reviewee__is_active=True)
        .filter(Q(access_token_expires__isnull=True) | Q(access_token_expires__gt=now))
        .exclude(cycle__reviewee__email='')
        .exclude(pk__in=_sent(SentEmail.REPORT_FOLLOW_UP))
        .select_related('cycle__reviewee__organization', 'cycle__questionnaire')
    )
    return [r for r in reports if _may_email(r.cycle.reviewee.organization)]


# Sending.

def organization_admins(organization):
    """The active admins of an organization with an email address."""
    profiles = UserProfile.objects.for_organization(organization).filter(user__is_active=True).select_related('user')
    return [
        p.user for p in profiles
        if p.user.email and p.user.has_perm('accounts.can_manage_organization')
    ]


def _once(kind, obj, send):
    """Run send() unless an email of this kind already went out about obj. True if it went out now.

    The record is made first, so two runs at once cannot both send. It goes again when sending fails or
    reaches nobody, so a later run can try again.
    """
    record, created = SentEmail.objects.get_or_create(kind=kind, object_id=obj.pk)
    if not created:
        return False
    try:
        sent = send()
    except Exception:
        record.delete()
        raise
    if not sent:
        record.delete()
    return bool(sent)


def _send(template, subject, recipient, context, organization):
    context = {'site_name': settings.SITE_NAME, **context}
    send_logged(
        organization, template,
        subject=subject,
        message=render_to_string(f'emails/{template}.txt', context),
        recipient_list=[recipient],
        html_message=render_to_string(f'emails/{template}.html', context),
        from_email=organization.from_email or None,
    )


def _send_to_admins(organization, template, build):
    """Send to each admin in their own language. build() returns (subject, context) in the active language."""
    admins = organization_admins(organization)
    for admin in admins:
        with translation.override(user_language(admin, organization)):
            subject, context = build()
            context = {'name': admin.first_name, 'organization': organization, **context}
            _send(template, subject, admin.email, context, organization)
    return len(admins)


def send_no_cycle_nudge(organization):
    """Onboarding: signed up, but no review cycle yet."""
    def build():
        return _('Your account is ready. One step left.'), {
            'create_url': get_absolute_url('review_cycle_create'),
        }
    return _once(SentEmail.NO_CYCLE, organization,
                 lambda: _send_to_admins(organization, 'onboarding_first_cycle', build))


def send_no_reviewers_nudge(organization):
    """Onboarding: a review cycle exists, but no reviewer was invited yet."""
    cycle = ReviewCycle.objects.filter(reviewee__organization=organization).select_related('reviewee').first()

    def build():
        return _("%(name)s's cycle is set up. Invite the reviewers.") % {'name': cycle.reviewee.name}, {
            'reviewee_name': cycle.reviewee.name,
            'cycle_url': get_absolute_url('review_cycle_detail', cycle_uuid=cycle.uuid),
            'threshold': organization.min_responses_for_anonymity,
        }
    return _once(SentEmail.NO_REVIEWERS, organization,
                 lambda: _send_to_admins(organization, 'onboarding_invite_reviewers', build))


def people_with_baseline(organization):
    """How many active people of the organization have a report from a closed cycle. An aggregate count."""
    return (
        Report.objects
        .filter(cycle__reviewee__organization=organization, cycle__reviewee__is_active=True,
                cycle__status='completed', available=True)
        .values('cycle__reviewee').distinct().count()
    )


def send_next_cycle_reminder(organization, cycle):
    """About six months after the organization's last cycle closed."""
    baseline = people_with_baseline(organization)

    def build():
        return _('Time for the next round of 360 feedback'), {
            'baseline': baseline,
            'last_closed_at': cycle.updated_at,
            'create_url': get_absolute_url('review_cycle_create'),
        }
    return _once(SentEmail.NEXT_CYCLE, cycle,
                 lambda: _send_to_admins(organization, 'next_cycle_reminder', build))


def has_perception_gap(report):
    """True when the report shows a notable gap between the self-assessment and the others' scores.

    Only a yes or no for the email, never the area or the scores. No when fewer other reviewers
    responded than the anonymity threshold.
    """
    data = report.report_data or {}
    threshold = report.cycle.reviewee.organization.min_responses_for_anonymity
    # The stored gaps include hidden groups; the anonymized insights don't
    insights = apply_display_anonymization(data, threshold).get('insights') or {}
    return bool(insights.get('perception_gaps')) and self_vs_others_gap(data, threshold) is not None


def send_report_follow_up(report):
    """About a month after the reviewee got their report."""
    reviewee = report.cycle.reviewee
    organization = reviewee.organization

    def send():
        with translation.override(reviewee_language(reviewee)):
            context = {
                'name': reviewee.name,
                'organization': organization,
                'report_url': get_absolute_url('reports:reviewee_report', access_token=report.access_token),
                'has_development_path': bool(report.report_data.get('insights', {}).get('development_plan')),
                'has_gap': has_perception_gap(report),
            }
            _send('report_follow_up', _('What should your next report say?'), reviewee.email, context, organization)
        return 1
    return _once(SentEmail.REPORT_FOLLOW_UP, report, send)


# Events. These never raise: an email must not break closing a cycle or delivering a report.

def cycle_summary(cycle):
    """Aggregate counts for the cycle summary. Take them before closing removes the unused tokens.

    The counts for this cycle stay out when fewer reviewers responded than the anonymity threshold.
    """
    organization = cycle.organization
    threshold = organization.min_responses_for_anonymity
    reached = cycle.tokens.exclude(category='self').filter(REACHED_REVIEWER)
    invited = reached.count()
    responded = reached.filter(completed_at__isnull=False).count()
    enough = responded >= max(threshold, 1)
    cycles = ReviewCycle.objects.filter(reviewee__organization=organization).exclude(pk=cycle.pk)

    return {
        'threshold': threshold,
        'enough_responses': enough,
        'responded': responded if enough else None,
        'invited': invited if enough else None,
        'response_rate': round(100 * responded / invited) if enough else None,
        'completed_cycles': cycles.filter(status='completed').count() + 1,
        'open_cycles': cycles.filter(status='active').count(),
    }


def send_cycle_summary(cycle, summary=None):
    """To the admins when a cycle closes: response rate, the organization's open cycles, the next step."""
    try:
        summary = summary or cycle_summary(cycle)
        organization = cycle.organization

        def build():
            return _('Review cycle closed: %(name)s') % {'name': cycle.reviewee.name}, {
                **summary,
                'reviewee_name': cycle.reviewee.name,
                'cycle_url': get_absolute_url('review_cycle_detail', cycle_uuid=cycle.uuid),
                'cycles_url': get_absolute_url('review_cycle_list'),
            }
        return _once(SentEmail.CYCLE_SUMMARY, cycle,
                     lambda: _send_to_admins(organization, 'cycle_summary', build))
    except Exception:
        logger.exception('Error sending the summary for cycle %s', cycle.pk)
        return False


def report_delivered(report):
    """The reviewee got their report: remember when, and send the conversation guide for the first one."""
    try:
        SentEmail.objects.get_or_create(kind=SentEmail.REPORT_READY, object_id=report.pk)
        return send_feedback_conversation_guide(report)
    except Exception:
        logger.exception('Error after delivering report %s', report.pk)
        return False


def send_feedback_conversation_guide(report):
    """To the admins with the first report of the organization: how to run the feedback conversation."""
    organization = report.cycle.reviewee.organization
    earlier = (
        Report.objects.filter(cycle__reviewee__organization=organization, generated_at__lt=report.generated_at)
        .exclude(pk=report.pk)
    )
    if earlier.exists() or not _may_email(organization):
        return False

    def build():
        return _('The first 360 report of %(organization)s is ready') % {'organization': organization.name}, {
            'report_url': get_absolute_url('reports:view_report', cycle_uuid=report.cycle.uuid),
        }
    return _once(SentEmail.FEEDBACK_CONVERSATION, organization,
                 lambda: _send_to_admins(organization, 'feedback_conversation_guide', build))
