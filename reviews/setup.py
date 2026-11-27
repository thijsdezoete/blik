"""Who reviews a person: the one answer for the detail page, the cycle form, the list dialog and bulk runs."""
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q

from accounts.models import OrgUnitMembership, ReviewSetup, Reviewee, SetupReviewer
from questionnaires.models import Questionnaire
from reviews.models import CATEGORY_ORDER
from reviews.services import derive_reviewers

LISTED = ('manager', 'peer', 'direct_report')
# When one person lands in two categories, the first one here keeps them.
SAVE_PRIORITY = ('manager', 'direct_report', 'peer')


@dataclass
class Setup:
    reviewee: Reviewee
    source: str  # 'saved' | 'chart' | 'previous' | 'empty'
    questionnaire: Questionnaire | None
    flags: dict
    people: dict = field(default_factory=lambda: {c: [] for c in LISTED})
    emails: dict = field(default_factory=lambda: {c: [] for c in LISTED})

    def email_assignments(self, categories):
        assignments = {}
        for category in categories:
            if category == 'self':
                assignments['self'] = [self.reviewee.email.lower()]
            else:
                assignments[category] = [p.email.lower() for p in self.people[category]] + [
                    e.lower() for e in self.emails[category]]
        return assignments


def previous_cycle_reviewers(reviewee):
    """
    The latest cycle of a person as (cycle, email assignments per category), or
    None when it cannot start a new one: no cycle,
    or nobody but the person in it. Emails only, never FKs. The questionnaire is
    for the caller to judge: a bulk run skips an archived one, a list does not.
    """
    previous = reviewee.review_cycles.select_related('questionnaire').first()
    if previous is None:
        return None
    email_assignments = {code: [] for code in previous.active_categories}
    # A colleague deactivated since then is not invited again.
    deactivated = Reviewee.objects.filter(
        organization=reviewee.organization_id, is_active=False, email__iexact=OuterRef('reviewer_email'))
    for category, email in previous.tokens.filter(
        reviewer_email__isnull=False, category__in=previous.active_categories,
    ).exclude(Exists(deactivated)).values_list('category', 'reviewer_email'):
        email_assignments[category].append(email.lower())
    # The self-assessment goes to the person's address of today,
    # not to the one the previous cycle used.
    if 'self' in email_assignments and reviewee.email:
        email_assignments['self'] = [reviewee.email.lower()]
    if not any(emails for code, emails in email_assignments.items() if code != 'self'):
        return None
    return previous, email_assignments


def has_previous_review(reviewee):
    return previous_cycle_reviewers(reviewee) is not None


def _active_people_by_email(reviewee):
    return {
        p.email.lower(): p
        for p in Reviewee.objects.filter(organization=reviewee.organization_id, is_active=True)
    }


def _default_questionnaire(reviewee):
    return Questionnaire.objects.filter(
        organization=reviewee.organization_id, is_active=True).order_by('-is_default', 'name', 'pk').first()


def _place_email(setup, category, email, by_email):
    """An email of an active person shows as that person; an email of nobody we know stays an email."""
    email = email.lower()
    if email == setup.reviewee.email.lower():
        return
    person = by_email.get(email)
    if person is None:
        setup.emails[category].append(email)
    elif person not in setup.people[category]:
        setup.people[category].append(person)


def _chart(reviewee):
    """The org chart buckets, or None when the chart knows nobody besides the person."""
    buckets = derive_reviewers(reviewee)
    return buckets if any(buckets[c] for c in LISTED) else None


def review_setup(reviewee, source=None, with_previous=False):
    """
    The reviewer list of a person. `source` 'chart' or 'previous' forces that source (the fill buttons).

    `with_previous`: the viewer may see the status per reviewer (`sees_reviewer_status`). Closing
    a review deletes the places nobody opened, so the reviewers left on it tell who answered.
    Without it the previous review is never a source, and forcing it gives the list as without force.
    """
    if source == 'previous' and not with_previous:
        source = None
    saved = ReviewSetup.objects.filter(reviewee=reviewee).select_related('questionnaire').first()
    flags = {f'include_{c}': True for c in CATEGORY_ORDER}
    questionnaire = None
    if saved is not None:
        flags = {f'include_{c}': getattr(saved, f'include_{c}') for c in CATEGORY_ORDER}
        if saved.questionnaire is not None and saved.questionnaire.is_active:
            questionnaire = saved.questionnaire
    setup = Setup(reviewee, 'empty', questionnaire, flags)

    if source is None and saved is not None:
        setup.source = 'saved'
        by_email = _active_people_by_email(reviewee)
        for row in saved.reviewers.select_related('person').order_by('person__name', 'pk'):
            if row.person is None:
                # Deactivated people are not in by_email, so they drop out here too.
                _place_email(setup, row.category, row.email, by_email)
            elif row.person.is_active:
                setup.people[row.category].append(row.person)
    elif source in (None, 'chart') and (buckets := _chart(reviewee)):
        setup.source = 'chart'
        for category in LISTED:
            setup.people[category] = [p for p in buckets[category] if p.pk != reviewee.pk]
    elif with_previous and source in (None, 'previous') and (previous := previous_cycle_reviewers(reviewee)):
        cycle, assignments = previous
        setup.source = 'previous'
        setup.flags = {f'include_{c}': getattr(cycle, f'include_{c}') for c in CATEGORY_ORDER}
        setup.questionnaire = cycle.questionnaire if cycle.questionnaire.is_active else None
        by_email = _active_people_by_email(reviewee)
        for category in LISTED:
            for email in assignments.get(category, []):
                _place_email(setup, category, email, by_email)

    if setup.questionnaire is None:
        setup.questionnaire = _default_questionnaire(reviewee)
    return setup


@transaction.atomic
def save_review_setup(reviewee, questionnaire, flags, people, emails):
    """Replace the saved list of a person. The one place that applies the rules of a list."""
    by_email = _active_people_by_email(reviewee)
    in_org = {p.pk for p in by_email.values()}
    own = reviewee.email.lower()
    seen_people = {reviewee.pk}
    seen_emails = {own}
    rows = []
    for category in SAVE_PRIORITY:
        chosen = [p for p in people.get(category, []) if p.pk in in_org]
        chosen_emails = []
        for email in emails.get(category, []):
            email = email.strip().lower()
            if email in by_email:
                chosen.append(by_email[email])
            elif email:
                chosen_emails.append(email)
        for person in chosen:
            if person.pk not in seen_people:
                seen_people.add(person.pk)
                rows.append(SetupReviewer(category=category, person=person))
        for email in chosen_emails:
            if email not in seen_emails:
                seen_emails.add(email)
                rows.append(SetupReviewer(category=category, email=email))

    setup, _created = ReviewSetup.objects.update_or_create(
        reviewee=reviewee, defaults={'questionnaire': questionnaire, **flags})
    setup.reviewers.all().delete()
    for row in rows:
        row.setup = setup
    SetupReviewer.objects.bulk_create(rows)
    return setup


def chart_has_reviewers(outer='pk'):
    """
    For a query over people: someone else who is active is in one of the person's units.
    That is when `derive_reviewers` gives at least one reviewer, so when the org chart is a source.
    """
    return Exists(OrgUnitMembership.objects.filter(
        unit__memberships__reviewee=OuterRef(outer), reviewee__is_active=True).exclude(reviewee=OuterRef(outer)))


def saved_reviewer_counts(reviewee_ids):
    """
    For the people who have a saved list: how many reviewers each category of the list holds,
    as {reviewee id: {category: count}}. Only the categories that the list includes;
    deactivated people are not counted. Two queries, whatever the number of people.
    """
    counts = {
        saved.reviewee_id: {c: 0 for c in LISTED if getattr(saved, f'include_{c}')}
        for saved in ReviewSetup.objects.filter(reviewee__in=reviewee_ids)}
    rows = SetupReviewer.objects.filter(setup__reviewee__in=list(counts)).filter(
        Q(person__isnull=True) | Q(person__is_active=True),
    ).values_list('setup__reviewee_id', 'category').annotate(n=Count('id'))
    for reviewee_id, category, n in rows:
        if category in counts[reviewee_id]:
            counts[reviewee_id][category] = n
    return counts
