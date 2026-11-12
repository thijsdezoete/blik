"""
What the dashboard and the cycle list say about the state of review cycles.

"Everyone answered" is not a state Blik can know. A cycle whose reviewers are
all invited by email closes by itself on the last answer, and for a shared
link Blik does not know how many people have it. What it does know is whether
the answers so far are enough for a report: each group of reviewers has
reached the organization's anonymity threshold.
"""
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy

from accounts.models import OrgUnit, Reviewee
from accounts.permissions import direct_report_emails, managers_without_account
from reports.models import Report
from reports.services import _hidden_groups, reviewer_counts
from reviews.models import ReviewCycle, ReviewerToken

# The groups of reviewers a report hides below the threshold.
GROUPS = ('peer', 'manager', 'direct_report')

# A cycle with no new answer for this long is worth a reminder.
STALE_AFTER = timedelta(days=7)

# From this many people the dashboard offers the org chart.
ORG_CHART_OFFER_FROM = 5


def with_progress(cycles):
    """Annotate cycles with their token counts: all, answered, and both per group of reviewers."""
    answered = Q(tokens__completed_at__isnull=False)
    counts = {
        'token_count': Count('tokens'),
        'completed_count': Count('tokens', filter=answered),
        'last_answer_at': Max('tokens__completed_at'),
    }
    for group in GROUPS:
        in_group = Q(tokens__category=group)
        counts[f'{group}_total'] = Count('tokens', filter=in_group)
        counts[f'{group}_done'] = Count('tokens', filter=in_group & answered)
    return cycles.annotate(**counts)


def enough_for_report(threshold):
    """
    Active cycles whose answers are enough for a report: at least one group
    has reached the threshold, and no group that has reviewers is below it.
    For cycles from with_progress().
    """
    threshold = max(threshold, 1)
    condition = Q(status='active')
    any_group = Q()
    for group in GROUPS:
        reached = Q(**{f'{group}_done__gte': threshold})
        condition &= Q(**{f'include_{group}': False}) | Q(**{f'{group}_total': 0}) | reached
        any_group |= Q(**{f'include_{group}': True}) & reached
    return condition & any_group


def cycle_stages(threshold):
    """The stages of a cycle, as {key: (label, condition)}. Every cycle from with_progress() is in exactly one."""
    enough = enough_for_report(threshold)
    return {
        'waiting': (gettext_lazy('No answers yet'), Q(status='active', completed_count=0)),
        'collecting': (gettext_lazy('Collecting answers'), Q(status='active', completed_count__gt=0) & ~enough),
        'enough': (gettext_lazy('Enough answers for a report'), enough),
        'completed': (gettext_lazy('Completed'), Q(status='completed')),
    }


def cycle_needs(threshold, now=None):
    """
    The things an active cycle can need from the person who runs it, as
    {key: (label, condition)}. For cycles from with_progress() that also
    have `failed_emails`.
    """
    week_ago = (now or timezone.now()) - STALE_AFTER
    no_reviewers = Q(status='active', **{f'{group}_total': 0 for group in GROUPS})
    return {
        'failed_emails': (gettext_lazy('Emails could not be sent'), Q(status='active', failed_emails__gt=0)),
        'stale': (
            gettext_lazy('No new answer for 7 days'),
            Q(status='active', created_at__lt=week_ago) & ~no_reviewers & ~enough_for_report(threshold)
            & (Q(last_answer_at__isnull=True) | Q(last_answer_at__lt=week_ago)),
        ),
        'no_reviewers': (gettext_lazy('Cycles without reviewers'), no_reviewers),
    }


def failed_emails():
    """Queued emails the outbox could not send, counted per cycle."""
    return Count('tokens', filter=Q(tokens__email_error__gt='') & (
        Q(tokens__invitation_queued_at__isnull=False) | Q(tokens__reminder_queued_at__isnull=False)))


def running_state(cycles, threshold, now=None):
    """The numbers of the "Running now" and "Needs your attention" cards for these cycles; None when none is active."""
    now = now or timezone.now()
    active = with_progress(cycles.filter(status='active')).annotate(failed_emails=failed_emails())
    cycle_count = active.count()
    if not cycle_count:
        return None

    tokens = ReviewerToken.objects.filter(cycle__in=cycles.filter(status='active'))
    answered = Q(completed_at__isnull=False)
    by_email = Q(reviewer_email__isnull=False)
    numbers = tokens.aggregate(
        answers=Count('pk', filter=answered),
        new_answers=Count('pk', filter=Q(completed_at__gte=now - STALE_AFTER)),
        invited=Count('pk', filter=by_email),
        invited_answered=Count('pk', filter=by_email & answered),
        link_answers=Count('pk', filter=~by_email & answered),
    )
    stages = cycle_stages(threshold)
    list_url = reverse('review_cycle_list')
    return {
        **numbers,
        'cycles': cycle_count,
        'oldest': active.order_by('created_at').values_list('created_at', flat=True).first(),
        'stages': [
            {'key': key, 'label': stages[key][0], 'count': active.filter(stages[key][1]).count(),
             'url': f'{list_url}?stage={key}'}
            for key in ('waiting', 'collecting', 'enough')
        ],
        'needs': {
            key: {'count': active.filter(condition).count(), 'url': f'{list_url}?needs={key}'}
            for key, (_label, condition) in cycle_needs(threshold, now).items()
        },
    }


def latest_reports(cycles, threshold, limit=5):
    """The newest reports of these cycles, each with its number of answers and the groups it hides."""
    reports = (
        Report.objects.filter(cycle__in=cycles.filter(status='completed'), available=True)
        .select_related('cycle__reviewee', 'cycle__questionnaire')
        .order_by('-cycle__updated_at', '-pk')[:limit]
    )
    labels = dict(ReviewerToken.CATEGORY_CHOICES)
    return [{
        'cycle': report.cycle,
        'answers': sum(reviewer_counts(report.report_data).values()),
        # The same exemptions as the report itself: self and manager are never hidden.
        'hidden': [labels[group] for group in GROUPS
                   if group in _hidden_groups(report.report_data, threshold, ['self', 'manager'])],
    } for report in reports]


def getting_started(org):
    """The four steps to the first report, each with whether the organization has done it and a number to show."""
    cycles = ReviewCycle.objects.filter(reviewee__organization=org)
    tokens = ReviewerToken.objects.filter(cycle__in=cycles)
    people = Reviewee.objects.for_organization(org).filter(is_active=True).count()
    invited = tokens.filter(
        Q(invitation_sent_at__isnull=False) | Q(claimed_at__isnull=False) | Q(completed_at__isnull=False)).count()
    reports = Report.objects.filter(cycle__in=cycles, available=True).count()
    steps = [
        {'key': 'people', 'done': people > 0, 'count': people},
        {'key': 'cycle', 'done': cycles.exists(), 'count': cycles.count()},
        {'key': 'invitations', 'done': invited > 0, 'count': invited},
        {'key': 'report', 'done': reports > 0, 'count': reports},
    ]
    next_step = next((step['key'] for step in steps if not step['done']), None)
    for step in steps:
        step['next'] = step['key'] == next_step
    done = sum(step['done'] for step in steps)
    return {'steps': steps, 'done': done, 'total': len(steps), 'complete': done == len(steps),
            'percent': round(100 * done / len(steps)), 'people': people}


def suggestions(org, user, started):
    """Things that are not problems but make Blik more useful: accounts for managers, the org chart."""
    has_chart = OrgUnit.objects.filter(organization=org).exists()
    people = Reviewee.objects.for_organization(org).filter(is_active=True)
    return {
        'managers_without_account': (
            len(managers_without_account(org)) if user.has_perm('accounts.can_invite_members') else 0),
        'not_in_chart': people.filter(unit_memberships__isnull=True).count() if has_chart else 0,
        # The org chart comes after the first report: first learn what a cycle is, then scale up.
        'offer_org_chart': (
            started['complete'] and not has_chart and not org.org_chart_offer_dismissed
            and started['people'] >= ORG_CHART_OFFER_FROM and user.has_perm('accounts.can_manage_organization')),
    }


def _progress(cycle, threshold):
    """How far one cycle is, for a row: what is known for invited reviewers, and a count for shared links."""
    tokens = list(cycle.tokens.all())
    by_email = [t for t in tokens if t.reviewer_email and t.category != 'self']
    by_link = [t for t in tokens if not t.reviewer_email and t.category != 'self']
    done = {group: sum(1 for t in tokens if t.category == group and t.completed_at) for group in GROUPS}
    total = {group: sum(1 for t in tokens if t.category == group) for group in GROUPS}
    collected = [group for group in GROUPS if getattr(cycle, f'include_{group}')]
    return {
        'invited': len(by_email),
        'invited_answered': sum(1 for t in by_email if t.completed_at),
        'link_answers': sum(1 for t in by_link if t.completed_at),
        'enough': (
            any(done[group] >= threshold for group in collected)
            and all(total[group] == 0 or done[group] >= threshold for group in collected)),
    }


def personal_state(user, org, threshold, runs_team):
    """
    The dashboard of a person who is not an admin: their own feedback, the
    feedback colleagues wait for, and their direct reports.
    """
    email = (user.email or '').lower()
    if not email or org is None:
        return {'own': [], 'to_review': [], 'team': [], 'team_reports': []}
    threshold = max(threshold, 1)
    in_org = ReviewCycle.objects.filter(reviewee__organization=org).select_related('reviewee', 'questionnaire')

    own = []
    for cycle in in_org.filter(status='active', reviewee__email__iexact=email).prefetch_related('tokens'):
        tokens = list(cycle.tokens.all())
        own.append({
            'cycle': cycle,
            'answers': sum(1 for t in tokens if t.completed_at and t.category != 'self'),
            'self_open': cycle.include_self and not any(t.category == 'self' and t.completed_at for t in tokens),
        })

    # This shows a person the same links their invitation emails hold, and
    # nothing about what anyone answered.
    to_review = list(
        ReviewerToken.objects.filter(
            cycle__in=in_org.filter(status='active'), reviewer_email__iexact=email, completed_at__isnull=True)
        .exclude(category='self').select_related('cycle__reviewee').order_by('cycle__reviewee__name'))

    below = direct_report_emails(user, org)
    team, team_reports = [], []
    if below:
        people = {r.email.lower(): r for r in Reviewee.objects.for_organization(org).filter(is_active=True)}
        team_cycles = [c for c in in_org.prefetch_related('tokens').order_by('reviewee__name', '-created_at')
                       if c.reviewee.email.lower() in below]
        seen = set()
        for cycle in team_cycles:
            if cycle.status != 'active' or cycle.reviewee_id in seen:
                continue
            seen.add(cycle.reviewee_id)
            team.append({'cycle': cycle, 'runs': runs_team, **_progress(cycle, threshold)})
        team_reports = latest_reports(in_org.filter(pk__in=[c.pk for c in team_cycles]), threshold)
        # People of the team who have no cycle running.
        idle = sorted((people[e] for e in below if e in people and people[e].pk not in seen), key=lambda r: r.name)
        team += [{'reviewee': reviewee} for reviewee in idle]
    return {'own': own, 'to_review': to_review, 'team': team, 'team_reports': team_reports}
