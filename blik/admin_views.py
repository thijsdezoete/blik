"""
Admin dashboard views for Blik
"""
import json
import logging
import math
import random
import re
from datetime import date
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import ProtectedError
from django.db.models import Avg, Count, Exists, F, Max, OuterRef, Q, Subquery
from django.db.models.functions import Lower
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.functional import partition
from django.utils.translation import gettext as _, gettext_lazy, ngettext
from django.views.decorators.http import require_POST

from accounts.chart_link import append_membership, apply_chart_choice, chart_relation, unplaced_with_manager
from accounts.models import Reviewee, UserProfile, OrganizationInvitation, OrgUnit, OrgUnitMembership
from accounts.permissions import (
    assign_organization_admin,
    assign_organization_member,
    can_manage_organization_required,
    can_manage_questionnaires_required,
    can_use_api,
    can_view_all_reports,
    creatable_reviewees,
    is_organization_admin,
    login_required,
    direct_report_emails,
    managers_without_account,
    may_create_for_others,
    run_team_emails,
    set_user_permission,
    visible_cycles,
)
from api.models import APIToken, WebhookEndpoint
from core.env_config import env_managed_fields
from core.languages import default_language, is_language, language_name
from core.gdpr import GDPRDeletionService
from core.models import Organization
from productreviews.models import ProductReview, anonymous_name
from questionnaires.editor import (
    DID_NOT_OBSERVE_TYPES,
    MODELS,
    EditorError,
    add_section,
    advice_for,
    advice_rows,
    advice_threshold,
    clear_model,
    editor_context,
    get_default_labels,
    languages_with_translation,
    load_for_editor,
    question_form_values,
    save_advice,
    save_info,
    save_question,
    save_section,
    set_did_not_observe,
    set_weight,
    translated_into,
)
from questionnaires.models import AnswerOption, Question, QuestionSection, Questionnaire
from questionnaires.ordering import save_layout
from questionnaires.presentation import question_scoring, questionnaire_report_features
from reports.dreyfus_service import DREYFUS_STAGES
from questionnaires.translations import get_language_states, get_text_translations, save_one_translation
from notifications.lifecycle import cycle_summary, send_cycle_summary
from reports.dreyfus_service import (
    agency_profile_with_texts,
    calculate_dreyfus_quadrant,
    quadrant_with_texts,
    skill_profile_with_texts,
    _level_to_stage,
)
from reports.models import Report
from reports.finalize import finalize_cycle
from reports.services import generate_report, self_vs_others_gap
from reviews.models import CATEGORY_ORDER, ReviewCycle, ReviewerToken
from reviews.outbox import queue_invitations, queue_reminders, queue_reviewee_notifications
from blik import dashboard as dashboard_state
from reviews.services import assign_tokens_to_emails, derive_reviewers, send_links_email
from reviews.setup import previous_cycle_reviewers, review_setup, save_review_setup
from subscriptions.models import Subscription
from subscriptions.utils import (
    CREDITS_PER_PACK,
    NoCycleCredits,
    ReviewerLimit,
    billing_context,
    can_see_billing,
    check_employee_limit,
    cycle_credits,
    get_subscription_status,
)

logger = logging.getLogger(__name__)


def limit_error(request, error):
    """A credit or reviewer limit message. Admins who can open Billing get a link to it."""
    from django.utils.html import format_html
    if can_see_billing(request.organization, request.user):
        messages.error(request, format_html('{} <a href="{}">{}</a>', str(error), reverse('billing'), _('Go to Billing')))
    else:
        messages.error(request, str(error))


def get_cycle_or_404(request, cycle_uuid):
    """
    Get a ReviewCycle by UUID, filtered by organization and by what the current
    user is allowed to see. Returns 404 for cycles in another organization or
    belonging to a reviewee whose cycles this user does not run.
    """
    cycles_qs = ReviewCycle.objects.select_related('reviewee', 'questionnaire', 'created_by')
    if request.organization:
        cycles_qs = cycles_qs.filter(reviewee__organization=request.organization)
    allowed = visible_cycles(request.user, cycles_qs)
    team = run_team_emails(request.user, request.organization)
    if team:
        # A manager who may create cycles for their direct reports also runs those cycles.
        allowed = cycles_qs.annotate(reviewee_email_lower=Lower('reviewee__email')).filter(
            Q(pk__in=allowed.values('pk')) | Q(reviewee_email_lower__in=team))
    return get_object_or_404(allowed, uuid=cycle_uuid)


@login_required
def legacy_id_redirect(request, pk, model, url_name):
    """Send an old integer-id URL (bookmark) to its UUID URL, own organization only."""
    obj = get_object_or_404(model, pk=pk, organization=request.organization)
    return redirect(url_name, obj.uuid, permanent=True)


def posted_setup(request, organization, categories):
    """
    Read the reviewer selections of the cycle form: people from the picker and
    emails from the textareas, per category.

    Picker hidden inputs are named `<category>_reviewees` and carry Reviewee
    UUIDs. Textareas are named `<category>_emails` and carry comma/newline
    separated emails. Categories not in `categories` come back empty. An email
    of a person already picked in that category is not repeated.

    Returns (people, emails, warnings): {category: [Reviewee]},
    {category: [email]} and the texts for the emails skipped as invalid.
    """
    people = {code: [] for code, _label in ReviewerToken.CATEGORY_CHOICES}
    emails = {code: [] for code, _label in ReviewerToken.CATEGORY_CHOICES}
    warnings = []
    labels = dict(ReviewerToken.CATEGORY_CHOICES)

    # One query for the chips of all categories.
    all_uuids = set()
    for code in categories:
        all_uuids.update(request.POST.getlist(f'{code}_reviewees'))
    by_uuid = {}
    if all_uuids and organization:
        valid = []
        for u in all_uuids:
            try:
                valid.append(UUID(str(u)))
            except ValueError:
                continue
        by_uuid = {
            str(r.uuid): r
            for r in Reviewee.objects.for_organization(organization).filter(uuid__in=valid)
        }

    for code in categories:
        seen = set()

        # Unknown UUIDs (stale page, deleted reviewee, other org) are skipped.
        for u in request.POST.getlist(f'{code}_reviewees'):
            person = by_uuid.get(str(u))
            email = ((person.email if person else '') or '').strip().lower()
            if email and email not in seen:
                seen.add(email)
                people[code].append(person)

        raw = (request.POST.get(f'{code}_emails') or '').strip()
        for candidate in re.split(r'[,\n]+', raw) if raw else []:
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                validate_email(candidate)
            except ValidationError:
                warnings.append(
                    _('Invalid email skipped in %(category)s: %(email)s')
                    % {'category': labels[code], 'email': candidate}
                )
                continue
            normalized = candidate.lower()
            if normalized not in seen:
                seen.add(normalized)
                emails[code].append(normalized)

    return people, emails, warnings


def posted_emails(people, emails):
    """The posted people and emails of each category as one list of emails."""
    return {code: [p.email.strip().lower() for p in people[code]] + emails[code] for code in people}


def collect_reviewer_emails(request, organization, categories):
    """
    The reviewer selections of the cycle form as {category: [email, ...]},
    deduplicated by normalized email. Per the anonymity invariant, only emails
    are returned: the Reviewee identity is dropped here and never stored on the
    token.

    Returns (email_assignments, warnings).
    """
    people, emails, warnings = posted_setup(request, organization, categories)
    return posted_emails(people, emails), warnings


@login_required
def dashboard(request):
    """What is running and what needs this person: for an admin the organization, for others their own feedback and team."""
    org = request.organization
    threshold = org.min_responses_for_anonymity if org else 3
    sees_all = can_view_all_reports(request.user)
    context = {
        'sees_all': sees_all,
        'threshold': max(threshold, 1),
        'can_create_for_others': may_create_for_others(request.user),
        'subscription_status': get_subscription_status(org) if org else None,
        # A product review is global, not per organization.
        'user_has_reviewed': ProductReview.objects.filter(
            reviewer_email=request.user.email, is_active=True).exists(),
        # "How Blik works" is open until the person folds it once.
        'has_seen_welcome': getattr(getattr(request.user, 'profile', None), 'has_seen_welcome', False),
        **billing_context(org, request.user),
    }
    # Explain what a cycle costs only where Blik bills for it.
    mode = context['subscription_status']['mode'] if context['subscription_status'] else 'self_hosted'
    context['billing_mode'] = mode if context['is_hosted'] and mode != 'self_hosted' else ''
    context['credits_per_pack'] = CREDITS_PER_PACK
    context['show_billing'] = bool(org) and can_see_billing(org, request.user)

    if sees_all and org:
        cycles = ReviewCycle.objects.for_organization(org)
        started = dashboard_state.getting_started(org)
        context.update({
            'started': started,
            'running': dashboard_state.running_state(cycles, threshold),
            'reports': dashboard_state.latest_reports(cycles, threshold),
            'suggestions': dashboard_state.suggestions(org, request.user, started),
        })
    else:
        context['personal'] = dashboard_state.personal_state(
            request.user, org, threshold, runs_team=may_create_for_others(request.user))

    return render(request, 'admin_dashboard/dashboard.html', context)


@login_required
@require_POST
def dashboard_skip_org_chart(request):
    """Hide the dashboard's offer to build an org chart, for the whole organization."""
    org = request.organization
    if org and request.user.has_perm('accounts.can_manage_organization'):
        org.org_chart_offer_dismissed = True
        org.save(update_fields=['org_chart_offer_dismissed'])
    return redirect('admin_dashboard')


@login_required
def team_list(request):
    """Team management - users and invitations"""
    org = request.organization

    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('admin_dashboard')

    # Get all active (non-anonymized) users in this organization
    users_qs = UserProfile.objects.for_organization(org).select_related('user').order_by('-user__date_joined')

    # Get per_page from request, default to 25
    per_page = request.GET.get('per_page', '25')
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25

    # Paginate users
    paginator = Paginator(users_qs, per_page)
    page = request.GET.get('page')
    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        users = paginator.page(1)
    except EmptyPage:
        users = paginator.page(paginator.num_pages)

    # Add permission data as dynamic attribute
    for user_profile in users:
        user_profile.is_org_admin = user_profile.user.has_perm('accounts.can_manage_organization')
        user_profile.can_read_all_reports = can_view_all_reports(user_profile.user)
        user_profile.has_api_access = can_use_api(user_profile.user)

    # Get pending invitations
    invitations = OrganizationInvitation.objects.filter(
        organization=org,
        accepted_at__isnull=True
    ).order_by('-created_at')

    # Get subscription status
    subscription_status = get_subscription_status(org) if org else None

    context = {
        'users': users,
        'invitations': invitations,
        'subscription_status': subscription_status,
        'per_page': per_page,
        'default_language_name': language_name(default_language(org)),
    }

    return render(request, 'admin_dashboard/team.html', context)


@login_required
@require_POST
def update_user_permissions(request):
    """Update user permissions and role"""
    # Check if requester has permission to manage organization
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to manage user permissions.'))
        return redirect('team_list')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('admin_dashboard')

    try:
        user_profile_id = request.POST.get('user_profile_id')
        role = request.POST.get('role')  # 'admin' or 'member'
        can_create_cycles_for_others = request.POST.get('can_create_cycles_for_others') == 'on'
        can_view_reports = request.POST.get('can_view_all_reports') == 'on'
        use_api = request.POST.get('can_use_api') == 'on'

        if not user_profile_id or not role:
            messages.error(request, _('Invalid request: missing required fields.'))
            return redirect('team_list')

        # Get the user profile being updated
        user_profile = get_object_or_404(
            UserProfile,
            id=user_profile_id,
            organization=org
        )
        target_user = user_profile.user

        # Prevent self-demotion or demoting superusers. API access is the one
        # thing an admin sets on their own account: no admin has it by
        # default, so the first one has to take it themselves.
        if target_user.id == request.user.id:
            set_user_permission(target_user, 'can_use_api', use_api)
            if use_api:
                messages.success(request, _('%(username)s now has API access.') % {'username': target_user.username})
            return redirect('team_list')

        if target_user.is_superuser:
            messages.error(request, _('Cannot modify permissions for super admins.'))
            return redirect('team_list')

        # Check if this would be the last admin
        if target_user.has_perm('accounts.can_manage_organization') and role == 'member':
            # Count users with organization admin permission
            admin_profiles = UserProfile.objects.filter(organization=org).select_related('user')
            admin_count = sum(1 for p in admin_profiles if p.user.has_perm('accounts.can_manage_organization'))

            if admin_count <= 1:
                messages.error(request, _('Cannot demote the last organization administrator.'))
                return redirect('team_list')

        # Update role and permissions
        if role == 'admin':
            assign_organization_admin(target_user)
            messages.success(request, _('Successfully promoted %(username)s to Organization Admin.') % {'username': target_user.username})
        else:  # member
            # Remove admin permissions
            assign_organization_member(target_user, can_create_cycles_for_others=False)
            messages.success(request, _('Successfully updated %(username)s to Member role.') % {'username': target_user.username})

        # Update can_create_cycles_for_others permission separately
        # (this can be set independently of role)
        user_profile.refresh_from_db()
        user_profile.can_create_cycles_for_others = can_create_cycles_for_others
        user_profile.save()

        if can_create_cycles_for_others:
            messages.success(request, _('%(username)s can now create review cycles for others.') % {'username': target_user.username})

        # Report access is a permission on the user, not a profile flag. Admins
        # already hold it through their group, so granting it directly would
        # only linger after a demotion.
        grant_reports = can_view_reports and role != 'admin'
        set_user_permission(target_user, 'can_view_all_reports', grant_reports)

        if grant_reports:
            messages.success(request, _('%(username)s can now view all reports.') % {'username': target_user.username})

        # API access is in no group, so it is set for admins and members alike.
        set_user_permission(target_user, 'can_use_api', use_api)

        if use_api:
            messages.success(request, _('%(username)s now has API access.') % {'username': target_user.username})

    except Exception as e:
        messages.error(request, _('Error updating permissions: %(error)s') % {'error': str(e)})

    return redirect('team_list')


REVIEWEE_STAGES = {
    'not_started': (gettext_lazy('Not started'), Q(cycle_count=0)),
    'active': (gettext_lazy('In progress'), Q(active_cycle_count__gt=0)),
    'completed': (gettext_lazy('Completed'), Q(cycle_count__gt=0, active_cycle_count=0)),
}

REVIEWEE_SORTS = {
    'name': gettext_lazy('Name A–Z'),
    'name_desc': gettext_lazy('Name Z–A'),
    'gap': gettext_lazy('Largest self/others difference'),
}


@login_required
def reviewee_list(request):
    """Find people and understand their feedback status before taking action."""
    org = request.organization
    people = Reviewee.objects.for_organization(org).filter(is_active=True)
    if not can_view_all_reports(request.user):
        # Everyone else sees themselves and, as a manager, their direct reports.
        scope = direct_report_emails(request.user, org) | {(request.user.email or '').lower()}
        people = people.annotate(email_lower=Lower('email')).filter(email_lower__in=scope)
    latest_cycles = ReviewCycle.objects.filter(reviewee=OuterRef('pk')).order_by('-created_at', '-pk')
    latest_reports = Report.objects.filter(
        cycle__reviewee=OuterRef('pk'), cycle__status='completed', available=True,
    ).order_by('-cycle__created_at', '-pk')
    reviewees_qs = people.annotate(
        cycle_count=Count('review_cycles'),
        active_cycle_count=Count('review_cycles', filter=Q(review_cycles__status='active')),
        latest_cycle_id=Subquery(latest_cycles.values('id')[:1]),
        latest_questionnaire_id=Subquery(latest_cycles.values('questionnaire_id')[:1]),
        active_cycle_id=Subquery(latest_cycles.filter(status='active').values('id')[:1]),
        latest_report_id=Subquery(latest_reports.values('id')[:1]),
    ).order_by('name', 'pk')

    # Facets come from this organization's visible people, including archived
    # questionnaires still referenced by their latest cycle.
    departments = people.exclude(department='').order_by('department').values_list('department', flat=True).distinct()
    used_questionnaires = Questionnaire.objects.for_organization(org).filter(
        pk__in=reviewees_qs.values('latest_questionnaire_id'),
    ).order_by('name')
    has_reviewees = people.exists()

    q = request.GET.get('q', '').strip()
    department = request.GET.get('department', '')
    questionnaire_filter = request.GET.get('questionnaire', '')
    if q:
        reviewees_qs = reviewees_qs.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(department__icontains=q))
    if department:
        reviewees_qs = reviewees_qs.filter(department=department)
    if questionnaire_filter:
        try:
            questionnaire_uuid = UUID(questionnaire_filter)
        except ValueError:
            questionnaire_filter = ''
        else:
            questionnaire_filter = str(questionnaire_uuid)
            reviewees_qs = reviewees_qs.filter(latest_questionnaire_id__in=
                Questionnaire.objects.for_organization(org).filter(uuid=questionnaire_uuid).values('id'))

    # Counts describe what each stage will show with the other filters applied.
    stage_counts = {key: reviewees_qs.filter(condition).count()
                    for key, (_label, condition) in REVIEWEE_STAGES.items()}
    stage = request.GET.get('stage', '')
    if stage in REVIEWEE_STAGES:
        reviewees_qs = reviewees_qs.filter(REVIEWEE_STAGES[stage][1])
    else:
        stage = ''
    sort = request.GET.get('sort', 'name')
    if sort not in REVIEWEE_SORTS:
        sort = 'name'
    if sort == 'name_desc':
        reviewees_qs = reviewees_qs.order_by('-name', 'pk')

    try:
        per_page = int(request.GET.get('per_page', '25'))
        if per_page not in (25, 50, 100):
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25

    min_threshold = org.min_responses_for_anonymity if org else 3

    def load_reports(rows):
        ids = [person.latest_report_id for person in rows if person.latest_report_id]
        return {
            report.id: (report, self_vs_others_gap(report.report_data, min_threshold))
            for report in Report.objects.filter(id__in=ids).select_related('cycle')
        }

    if sort == 'gap':
        # Preserve the existing across-page ordering and anonymity threshold.
        reviewees_qs = list(reviewees_qs)
        reports_by_id = load_reports(reviewees_qs)
        gap_of = lambda person: reports_by_id.get(person.latest_report_id, (None, None))[1]
        reviewees_qs.sort(key=lambda person: (gap_of(person) is None, -abs(gap_of(person) or 0)))

    reviewees = Paginator(reviewees_qs, per_page).get_page(request.GET.get('page'))
    if sort != 'gap':
        reports_by_id = load_reports(reviewees)

    questionnaires = list(Questionnaire.objects.for_organization(org).filter(
        is_active=True).order_by('-is_default', 'name', 'pk'))
    questionnaire_by_id = {item.id: item for item in questionnaires}
    default_questionnaire = questionnaires[0] if questionnaires else None
    cycle_ids = {cycle_id for person in reviewees
                 for cycle_id in (person.latest_cycle_id, person.active_cycle_id) if cycle_id}
    cycles_by_id = {
        cycle.id: cycle for cycle in ReviewCycle.objects.filter(id__in=cycle_ids).select_related('questionnaire')
    }
    reviewees_with_latest = []
    for person in reviewees:
        latest_cycle = cycles_by_id.get(person.latest_cycle_id)
        latest_questionnaire = latest_cycle.questionnaire if latest_cycle else None
        report, gap = reports_by_id.get(person.latest_report_id, (None, None))
        reviewees_with_latest.append({
            'reviewee': person,
            'source_cycle': latest_cycle,
            'latest_questionnaire': latest_questionnaire,
            'selected_questionnaire': questionnaire_by_id.get(
                latest_questionnaire.id if latest_questionnaire else None, default_questionnaire),
            'active_cycle': cycles_by_id.get(person.active_cycle_id),
            'latest_completed_report': report,
            'gap': gap,
        })

    return render(request, 'admin_dashboard/reviewee_list.html', {
        'reviewees_with_latest': reviewees_with_latest,
        'reviewees': reviewees,
        'questionnaires': questionnaires,
        'subscription_status': get_subscription_status(org) if org else None,
        'per_page': per_page,
        'sort': sort,
        'sorts': REVIEWEE_SORTS.items(),
        'q': q,
        'department': department,
        'departments': departments,
        'questionnaire_filter': questionnaire_filter,
        'used_questionnaires': used_questionnaires,
        'stage': stage,
        'stages': [(key, label, stage_counts[key]) for key, (label, _cond) in REVIEWEE_STAGES.items()],
        'stage_counts': stage_counts,
        'total_count': sum(stage_counts.values()),
        'has_reviewees': has_reviewees,
        'is_filtered': bool(q or department or questionnaire_filter or stage),
    })


def place_in_department(org, reviewee, name, manager=None, leads=False):
    """Put a new reviewee in the org chart unit called `name`, made if there is none yet.

    A new unit gets `manager` as its manager, or the reviewee when they `leads` it.
    """
    unit = OrgUnit.objects.filter(organization=org, name__iexact=name).first()
    if unit is None:
        last = OrgUnit.objects.filter(organization=org).aggregate(m=Max('display_order'))['m'] or 0
        unit = OrgUnit.objects.create(organization=org, name=name, display_order=last + 1)
        if manager and not leads:
            append_membership(unit, manager, OrgUnitMembership.MANAGER)
    append_membership(unit, reviewee, OrgUnitMembership.MANAGER if leads else OrgUnitMembership.MEMBER)
    reviewee.department = unit.name
    reviewee.save(update_fields=['department'])


def department_choices(request):
    """The org chart units the department field suggests, for those who may edit the chart."""
    if not request.user.has_perm('accounts.can_manage_organization'):
        return {'department_units': None}
    units = list(OrgUnit.objects.filter(organization=request.organization).order_by('name').values_list('name', flat=True))
    return {'department_units': units, 'department_units_json': json.dumps(units)}


@login_required
def reviewee_create(request):
    """Create a new reviewee"""
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        department = request.POST.get('department', '').strip()
        language = request.POST.get('language', '')

        if name and email:
            organization = request.organization or Organization.objects.first()
            if not organization:
                messages.error(request, _('No organization found. Please run setup first.'))
                return redirect('admin_dashboard')

            # Non-admins can only create reviewees for themselves
            if not is_organization_admin(request.user):
                if email.lower() != request.user.email.lower():
                    messages.error(request, _('You can only create a reviewee profile for yourself.'))
                    return redirect('reviewee_list')

            # Check employee limit
            allowed, error_message = check_employee_limit(organization)
            if not allowed:
                messages.error(request, error_message)
                return redirect('reviewee_list')

            try:
                with transaction.atomic():
                    reviewee = Reviewee.objects.create(
                        organization=organization,
                        name=name,
                        email=email,
                        department=department,
                        language=language if is_language(language) else '',
                    )
                    # The department is a unit in the org chart, for those who may edit the chart.
                    if department and request.user.has_perm('accounts.can_manage_organization'):
                        manager = Reviewee.objects.for_organization(organization).filter(
                            uuid=request.POST.get('department_manager') or None).first()
                        place_in_department(organization, reviewee, department, manager,
                                            leads=request.POST.get('department_lead') == '1')
                messages.success(request, _('Reviewee "%(name)s" created successfully.') % {'name': reviewee.name})
                return redirect('reviewee_list')
            except Exception as e:
                messages.error(request, _('Error creating reviewee: %(error)s') % {'error': str(e)})
        else:
            messages.error(request, _('Name and email are required.'))

    return render(request, 'admin_dashboard/reviewee_form.html', {
        'action': 'Create',
        'default_language_name': language_name(default_language(request.organization)),
        **department_choices(request),
    })


@login_required
@can_manage_organization_required(
    redirect_url='reviewee_list',
    message=gettext_lazy('You do not have permission to edit reviewees. '
                         'Only organization administrators can access this feature.')
)
def reviewee_edit(request, reviewee_uuid):
    """Edit an existing reviewee - admin only"""
    reviewee = get_object_or_404(Reviewee, uuid=reviewee_uuid, organization=request.organization)

    if request.method == 'POST':
        reviewee.name = request.POST.get('name', reviewee.name)
        reviewee.email = request.POST.get('email', reviewee.email)
        reviewee.department = request.POST.get('department', '')
        language = request.POST.get('language', '')
        reviewee.language = language if is_language(language) else ''

        try:
            reviewee.save()
            messages.success(request, _('Reviewee "%(name)s" updated successfully.') % {'name': reviewee.name})
            return redirect('reviewee_list')
        except Exception as e:
            messages.error(request, _('Error updating reviewee: %(error)s') % {'error': str(e)})

    context = {
        'reviewee': reviewee,
        'action': 'Edit',
        'default_language_name': language_name(reviewee.organization.default_language),
    }

    return render(request, 'admin_dashboard/reviewee_form.html', context)


@login_required
@can_manage_organization_required(
    redirect_url='reviewee_list',
    message=gettext_lazy('You do not have permission to delete reviewees. '
                         'Only organization administrators can access this feature.')
)
def reviewee_delete(request, reviewee_uuid):
    """Soft delete a reviewee - admin only"""
    reviewee = get_object_or_404(Reviewee, uuid=reviewee_uuid, organization=request.organization)

    if request.method == 'POST':
        reviewee.is_active = False
        reviewee.save()
        messages.success(request, _('Reviewee "%(name)s" deactivated.') % {'name': reviewee.name})
        return redirect('reviewee_list')

    context = {
        'reviewee': reviewee,
    }

    return render(request, 'admin_dashboard/reviewee_confirm_delete.html', context)


@login_required
@require_POST
def reviewee_quick_create(request):
    """
    Create or return an existing Reviewee for the reviewee picker component.

    Accepts form-encoded POST with `name`, `email`, optional `department`.
    Returns JSON: {uuid, name, email, department, created}.

    If a Reviewee with the same (organization, email) already exists, returns
    that one (reactivating it if it was soft-deleted) rather than erroring —
    the picker flow treats email as the unique identity, and admins will
    routinely "re-add" someone by email from memory.
    """
    if not request.user.has_perm('accounts.can_manage_organization'):
        return JsonResponse(
            {'error': _('You do not have permission to create reviewees.')},
            status=403,
        )

    org = request.organization
    if not org:
        return JsonResponse({'error': _('No organization context.')}, status=400)

    name = (request.POST.get('name') or '').strip()
    email = (request.POST.get('email') or '').strip().lower()
    department = (request.POST.get('department') or '').strip()

    if not name or not email:
        return JsonResponse(
            {'error': _('Name and email are required.')},
            status=400,
        )

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'error': _('Invalid email address.')}, status=400)

    existing = Reviewee.objects.filter(organization=org, email=email).first()
    if existing:
        reactivated = False
        if not existing.is_active:
            existing.is_active = True
            reactivated = True
        # Only update name if caller provided one and the record currently
        # has no name — don't silently overwrite an existing admin-set name.
        if not existing.name:
            existing.name = name
        if reactivated or not existing.name:
            existing.save()
        return JsonResponse({
            'uuid': str(existing.uuid),
            'name': existing.name,
            'email': existing.email,
            'department': existing.department,
            'created': False,
        })

    allowed, error_message = check_employee_limit(org)
    if not allowed:
        return JsonResponse({'error': error_message}, status=400)

    reviewee = Reviewee.objects.create(
        organization=org,
        name=name,
        email=email,
        department=department,
    )
    return JsonResponse({
        'uuid': str(reviewee.uuid),
        'name': reviewee.name,
        'email': reviewee.email,
        'department': reviewee.department,
        'created': True,
    }, status=201)


@login_required
@require_POST
@can_manage_organization_required(
    redirect_url='reviewee_list',
    message=gettext_lazy('You do not have permission to create review cycles. '
                         'Only organization administrators can access this feature.')
)
def quick_cycle_create(request, reviewee_uuid):
    """
    Quick cycle creation from reviewee/cycle list.
    Creates a cycle based on a specified source cycle or the most recent cycle for this reviewee.
    Copies token structure and email assignments from the source cycle.
    If no previous cycle exists, creates default tokens (1 self, 3 peers, 1 manager, 0 direct reports).
    """
    org = request.organization
    reviewee = get_object_or_404(Reviewee, uuid=reviewee_uuid, organization=org, is_active=True)
    questionnaire_id = request.POST.get('questionnaire_id')
    source_cycle_uuid = request.POST.get('source_cycle_uuid')  # Optional: specific cycle to copy from

    if not questionnaire_id:
        messages.error(request, _('Questionnaire is required.'))
        return redirect('reviewee_list')

    try:
        questionnaire = Questionnaire.objects.get(id=questionnaire_id, organization=org, is_active=True)
    except Questionnaire.DoesNotExist:
        messages.error(request, _('Invalid questionnaire selected.'))
        return redirect('reviewee_list')

    # Pick the cycle to copy from before creating the new one, so its feedback
    # categories can be carried over along with its token structure.
    if source_cycle_uuid:
        # Copy from specific cycle if provided
        try:
            previous_cycle = ReviewCycle.objects.get(uuid=source_cycle_uuid, reviewee=reviewee)
        except ReviewCycle.DoesNotExist:
            previous_cycle = None
    else:
        # Otherwise, get the most recent previous cycle for this reviewee
        previous_cycle = reviewee.review_cycles.order_by('-created_at').first()

    # The dialog's checkboxes; a client without them keeps the previous cycle's categories.
    category_flags = selected_category_flags(request)
    if category_flags and not any(category_flags.values()):
        messages.error(request, _('Select at least one feedback category.'))
        return redirect('reviewee_list')
    if previous_cycle and not category_flags:
        category_flags = {
            f'include_{category}': previous_cycle.collects(category)
            for category in CATEGORY_ORDER
        }

    # Create the cycle and its tokens together: a refused token leaves no cycle behind.
    try:
        with transaction.atomic():
            cycle = ReviewCycle.objects.create(
                reviewee=reviewee,
                questionnaire=questionnaire,
                created_by=request.user,
                status='active',
                **category_flags
            )
            total_tokens = 0
            email_invited_count = 0

            if previous_cycle:
                # Copy tokens from previous cycle, including email assignments. The self-assessment
                # token comes from queue_reviewee_notifications below. A colleague deactivated
                # since then is not invited again, as in a bulk run.
                previous_tokens = previous_cycle.tokens.filter(
                    category__in=cycle.active_categories).exclude(category='self').exclude(Exists(
                        Reviewee.objects.filter(organization=reviewee.organization_id, is_active=False,
                                                email__iexact=OuterRef('reviewer_email'))))

                for prev_token in previous_tokens:
                    ReviewerToken.objects.create(
                        cycle=cycle,
                        category=prev_token.category,
                        reviewer_email=prev_token.reviewer_email
                    )
                    total_tokens += 1
                    if prev_token.reviewer_email:
                        email_invited_count += 1
            else:
                # No previous cycle - use default token distribution
                token_distribution = [
                    ('peer', 3),
                    ('manager', 1),
                    ('direct_report', 0),
                ]

                for category, count in token_distribution:
                    if not cycle.collects(category):
                        continue
                    for i in range(count):
                        ReviewerToken.objects.create(
                            cycle=cycle,
                            category=category
                        )
                        total_tokens += 1

            # The reviewee's emails go in the outbox; the cron sends them
            queue_reviewee_notifications(cycle)
    except (NoCycleCredits, ReviewerLimit) as e:
        limit_error(request, e)
        return redirect('reviewee_list')

    if previous_cycle:
        # Queue the invitations of all email-assigned tokens
        if email_invited_count > 0:
            queued = queue_invitations(cycle.tokens.all())

            messages.success(
                request,
                _('Review cycle created for "%(name)s" using "%(questionnaire)s". '
                  'Copied %(count)s reviewer(s) from previous cycle. '
                  '%(queued)s invitation email(s) go out within about five minutes.')
                % {'name': reviewee.name, 'questionnaire': questionnaire.name,
                   'count': total_tokens, 'queued': queued}
            )
        else:
            messages.success(
                request,
                _('Review cycle created for "%(name)s" using "%(questionnaire)s" with %(count)s reviewer token(s). '
                  'Go to the cycle details to assign reviewers and send invitations.')
                % {'name': reviewee.name, 'questionnaire': questionnaire.name, 'count': total_tokens}
            )
    else:
        messages.success(
            request,
            _('Review cycle created for "%(name)s" using "%(questionnaire)s" with %(count)s reviewer token(s). '
              'Go to the cycle details to assign reviewers and send invitations.')
            % {'name': reviewee.name, 'questionnaire': questionnaire.name, 'count': total_tokens}
        )

    messages.info(request, _("The reviewee's emails go out within about five minutes."))

    # Redirect to cycle detail page
    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
def questionnaire_list(request):
    """List available questionnaires"""
    org = request.organization

    # Subquery to count questions correctly
    question_count_subquery = Question.objects.filter(
        section__questionnaire=OuterRef('pk')
    ).values('section__questionnaire').annotate(
        count=Count('id')
    ).values('count')

    # Only show questionnaires belonging to the user's organization
    # Template questionnaires (organization=None) are not shown here as they're internal
    questionnaires_qs = Questionnaire.objects.filter(
        organization=org
    ) if org else Questionnaire.objects.filter(organization__isnull=False)

    questionnaires = questionnaires_qs.annotate(
        question_count=Subquery(question_count_subquery),
        cycle_count=Count('review_cycles')
    ).prefetch_related(
        *Questionnaire.translation_lookups()
    ).order_by('-is_default', 'name')

    # The languages it is translated into, at least in part
    for questionnaire in questionnaires:
        questionnaire.translation_states = [state for state in get_language_states(questionnaire) if state.translated]
        questionnaire.report_features = questionnaire_report_features(questionnaire)

    # Archived ones are kept out of the way but stay reachable: their cycles
    # and reports still reference them, so they cannot simply disappear.
    # partition() returns the non-matches first.
    archived, active = partition(lambda q: q.is_active, questionnaires)

    context = {
        'questionnaires': active,
        'archived_questionnaires': archived,
    }

    return render(request, 'admin_dashboard/questionnaire_list.html', context)


def editor_url_for(request, questionnaire, language=None):
    """The address of the questionnaire editor, for a page the editor opened (?from=editor) and a user who may edit.

    None for every other visit: the page then leads back to the list.
    """

    if request.GET.get('from') != 'editor' or not request.user.has_perm('accounts.can_manage_questionnaires'):
        return None

    url = reverse('questionnaire_edit', args=[questionnaire.uuid])

    if language and language != questionnaire.source_language:
        return f'{url}?lang={language}'

    return url


@login_required
def questionnaire_preview(request, questionnaire_uuid):
    """Preview a questionnaire in its source language, or in the language that ?lang= picks."""
    questionnaire = get_object_or_404(
        Questionnaire, uuid=questionnaire_uuid, organization=request.organization)
    language = request.GET.get('lang')

    if not is_language(language):
        language = questionnaire.source_language

    editor_url = editor_url_for(request, questionnaire, language)
    questionnaire = questionnaire.translated(language)

    context = {
        'questionnaire': questionnaire,
        'sections': questionnaire.sections.all(),
        'preview_language': language,
        'editor_url': editor_url,
    }

    if request.GET.get('fragment') == 'questions':
        response = render(request, 'admin_dashboard/partials/questionnaire_questions.html', context)
        response['X-Questionnaire-Preview'] = 'questions'
        return response

    return render(request, 'admin_dashboard/questionnaire_preview.html', context)


@login_required
def questionnaire_sample_report(request, questionnaire_uuid):
    """Render an illustrative sample report for a questionnaire.

    Builds a synthetic but shape-correct `insights` and `charts` data set so we
    can reuse the real Dreyfus diamond + agency SVGs and Chart.js radar/gap
    graphs. Seeded by questionnaire id so reloads look identical.
    """
    questionnaire = get_object_or_404(
        Questionnaire, uuid=questionnaire_uuid, organization=request.organization,
    ).translated()

    rng = random.Random(questionnaire.id)

    def score(center, spread=0.35):
        value = rng.uniform(center - spread, center + spread)
        return round(max(1.0, min(5.0, value)), 1)

    # Per-section scores, shaped exactly like what chart.js expects.
    section_scores = {}
    sections_data = []
    overall_totals = []
    for section in questionnaire.sections.all():
        base = rng.uniform(3.4, 4.4)
        cats = {
            'self': score(base - 0.2),
            'peer': score(base + 0.05),
            'manager': score(base + 0.15),
            'direct_report': score(base),
        }
        cats['others_avg'] = round(
            (cats['peer'] + cats['manager'] + cats['direct_report']) / 3, 1
        )
        section_scores[section.title] = cats
        sections_data.append({
            'title': section.title,
            'overall_score': cats['others_avg'],
            'category_scores': [
                ('self', cats['self']),
                ('peer', cats['peer']),
                ('manager', cats['manager']),
                ('direct_report', cats['direct_report']),
            ],
            'question_count': section.questions.count(),
        })
        overall_totals.append(cats['others_avg'])

    overall_score = round(sum(overall_totals) / len(overall_totals), 1) if overall_totals else 0.0

    # Build the `insights` dict that `reports/_dreyfus_profile.html` consumes.
    has_skill, has_agency = questionnaire.dreyfus_dimensions
    insights = {}

    if has_skill:
        skill_level = round(rng.uniform(3.2, 4.1), 2)
        insights['skill_profile'] = skill_profile_with_texts({
            'skill_level': skill_level,
            'stage': _level_to_stage(skill_level),
            'confidence': 0.85,
        })

    if has_agency:
        agency_level = round(rng.uniform(3.4, 4.3), 2)
        insights['agency_profile'] = agency_profile_with_texts({
            'agency_level': agency_level,
            'stage': _level_to_stage(agency_level),
            'confidence': 0.85,
        })

    if has_skill and has_agency:
        quadrant = calculate_dreyfus_quadrant(
            insights['skill_profile']['skill_level'],
            insights['agency_profile']['agency_level'],
        )
        insights['dreyfus_quadrant'] = quadrant_with_texts(quadrant)

    # Minimal development plan so the "next level" cards render.
    if has_skill:
        insights['development_plan'] = {
            'next_level_requirements': insights['skill_profile']['stage_info'].get(
                'development_focus', []
            ),
            'quick_wins': [
                _('Pair with a more senior teammate on a challenging problem this sprint'),
                _('Document one decision you made and why — share it for review'),
                _('Pick a weak area from the feedback and book focused practice time'),
            ],
        }

    context = {
        'questionnaire': questionnaire,
        'sections_data': sections_data,
        'overall_score': overall_score,
        'insights': insights,
        'chart_data': {'section_scores': section_scores},
        'editor_url': editor_url_for(request, questionnaire),
    }

    return render(request, 'admin_dashboard/questionnaire_sample_report.html', context)


@login_required
@can_manage_questionnaires_required
def questionnaire_create(request):
    """Create a new questionnaire"""
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        is_default = request.POST.get('is_default') == 'on'
        source_language = request.POST.get('source_language')

        if not is_language(source_language):
            source_language = translation.get_language()

        if not name:
            messages.error(request, _('Questionnaire name is required.'))
            return render(request, 'admin_dashboard/questionnaire_form.html', {'source_language': source_language})

        try:
            # Get organization from request context
            org = getattr(request, 'organization', None)

            questionnaire = Questionnaire.objects.create(
                name=name,
                description=description,
                is_default=is_default,
                organization=org,
                source_language=source_language,
            )
            messages.success(request, _('Questionnaire "%(name)s" created successfully.') % {'name': questionnaire.name})
            return redirect('questionnaire_edit', questionnaire_uuid=questionnaire.uuid)
        except Exception as e:
            messages.error(request, _('Error creating questionnaire: %(error)s') % {'error': str(e)})

    context = {
        # New questionnaires are most likely written in the language their author works in
        'source_language': translation.get_language(),
    }

    return render(request, 'admin_dashboard/questionnaire_form.html', context)


# The templates of the parts of the editor page that an answer can send again, by slot name
EDITOR_SLOTS = {
    'langs': 'admin_dashboard/editor/_langs.html',
    'settings': 'admin_dashboard/editor/_settings.html',
    'did-not-observe': 'admin_dashboard/editor/_did_not_observe.html',
    'report-card': 'admin_dashboard/editor/_report_card.html',
    'reviewer': 'admin_dashboard/editor/_reviewer.html',
    'report': 'admin_dashboard/editor/_report.html',
}
# The slots of one topic or question: topic-<id>-head, and the row of a question and the parts of the open question
# [0-9], not \d: \d also matches other digits, which no id has
EDITOR_ITEM_SLOT = re.compile(r'(?:(topic)-([0-9]+)-head|(question)-([0-9]+)-(row|labels|report))')
QUESTION_SLOTS = {
    'row': 'admin_dashboard/editor/_question_row.html',
    'labels': 'admin_dashboard/editor/_rating_labels.html',
    'report': 'admin_dashboard/editor/_question_report.html',
}


def _question_context(context, question):
    """The context of the open question and its slots: the slot context with the question and its form values."""

    return {**context, 'question': question, 'values': question_form_values(context['questionnaire'], question)}


def _translation_language(questionnaire, params):
    """The language of the translate mode that lang asks for: a language of the site other than the questionnaire's
    original language. None for the page in the original language."""

    language = params.get('lang')

    return language if is_language(language) and language != questionnaire.source_language else None


def _with_language(context, language):
    """The context of the editor page in the mode of language: for a translation language its texts, each with the id
    of the question it belongs to, and the reviewer's topic translated into it."""

    if language is None:
        return {**context, 'language': None}

    texts = get_text_translations(context['questionnaire'], language)

    for text in texts:
        if isinstance(text.part, Question):
            text.question_id = text.part.id
        elif isinstance(text.part, AnswerOption):
            text.question_id = text.part.question_id

    topic = context['reviewer_section']
    sections = context['questionnaire'].translated(language).sections.all()

    return {
        **context,
        'language': language,
        'language_name': language_name(language),
        'texts': texts,
        'reviewer_section': next((section for section in sections if topic and section.id == topic.id), None),
    }


# The person "Try it" of the advice dialog starts with
ADVICE_TRY_START = {'try_stage': 1, 'try_score': 2.4}


def _advice_question(questionnaire, params, field='question_id'):
    """The question of the advice dialog: one of this questionnaire, with a score."""

    question = _posted_question(questionnaire, params, field)

    if not question_scoring(question).has_score:
        raise EditorError(_('Only a question with a score can have advice.'))

    return question


def _advice_try_values(params):
    """The skill stage (1 to 5) and the score of the person in "Try it" of the advice dialog."""

    try:
        stage = int(params.get('try_stage', ''))
        score = float(params.get('try_score', ''))
    except ValueError:
        stage = score = None

    if stage not in DREYFUS_STAGES or score is None or not (math.isfinite(score) and 1 <= score <= 5):
        raise EditorError(_('Choose a stage and write a score from 1 to 5.'))

    return {'try_stage': stage, 'try_score': score}


def _advice_try_context(question, try_stage, try_score):
    """What "Try it" shows: the advice the person gets, and whether the stage has any advice at all."""

    return {
        'question': question,
        'try_stage': try_stage,
        'try_score': try_score,
        'try_stage_name': DREYFUS_STAGES[try_stage]['name'],
        'try_texts': advice_for(question, try_stage, try_score),
        # With the lowest possible score every line of the stage applies: whether the stage has advice at all
        'try_has_advice': bool(advice_for(question, try_stage, float('-inf'))),
    }


def _render_advice_try(request, context):
    """The slot advice-try of the posted question, for the posted "Try it" values."""

    question_id = request.POST.get('question_id', '')
    question = next(
        (item for section in context['sections'] for item in section.questions.all() if f'{item.id}' == question_id),
        None,
    )

    return question and render_to_string(
        'admin_dashboard/editor/_advice_try.html',
        _advice_try_context(question, **_advice_try_values(request.POST)),
        request=request,
    )


def _advice_dialog(request, questionnaire):
    """The answer to GET ?advice=<id>: the inside of the advice dialog of that question."""

    question = _advice_question(questionnaire, request.GET, 'advice')
    html = render_to_string('admin_dashboard/editor/_advice_dialog.html', {
        **_advice_try_context(question, **ADVICE_TRY_START),
        'rows': advice_rows(question),
        'threshold': advice_threshold(question),
    }, request=request)

    return JsonResponse({'ok': True, 'html': html})


def _render_editor_slot(request, context, name):
    """The HTML of one slot, or None for a topic, question or text that no longer exists."""

    if name == 'advice-try':
        return _render_advice_try(request, context)

    # The state of one text in the translate mode
    if name.startswith('text-'):
        text = next((text for text in context['texts'] if f'text-{text.field_name}' == name), None)

        return text and render_to_string(
            'admin_dashboard/editor/_translate_row.html', {**context, 'text': text}, request=request,
        )

    if not (match := EDITOR_ITEM_SLOT.fullmatch(name)):
        return render_to_string(EDITOR_SLOTS[name], context, request=request)

    sections = context['sections']

    if match[1]:
        section = next((section for section in sections if f'{section.id}' == match[2]), None)

        return section and render_to_string(
            'admin_dashboard/editor/_topic_head.html', {**context, 'section': section}, request=request,
        )

    questions = [question for section in sections for question in section.questions.all()]
    question = next((question for question in questions if f'{question.id}' == match[4]), None)

    if question is None:
        return None

    part_context = {**context, 'question': question} if match[5] == 'row' else _question_context(context, question)

    return render_to_string(QUESTION_SLOTS[match[5]], part_context, request=request)


def editor_response(request, questionnaire, slots, **extra):
    """The answer to an action of the editor page: the named slots, the reviewer and the report, and the chart data.

    The questionnaire is loaded anew, so the slots show what is stored now. An extra value that is a function gets the
    slot context and gives the value to send. A GET (the open question) carries shown and topic in its query. A request
    of the translate mode carries its language in lang.
    """

    params = request.POST if request.method == 'POST' else request.GET
    shown = [model for model in params.get('shown', '').split(',') if model in MODELS]
    context = _with_language(
        editor_context(load_for_editor(questionnaire), shown, params.get('topic')),
        _translation_language(questionnaire, params),
    )
    rendered = {name: _render_editor_slot(request, context, name) for name in [*slots, 'reviewer', 'report']}
    extra = {key: value(context) if callable(value) else value for key, value in extra.items()}

    return JsonResponse({
        'ok': True,
        'slots': {name: html for name, html in rendered.items() if html is not None},
        'chart': context['chart'],
        **extra,
    })


def _posted_section(questionnaire, post, field='section_id'):
    try:
        return questionnaire.sections.get(id=int(post.get(field, '')))
    except (ValueError, QuestionSection.DoesNotExist):
        raise EditorError(_('This topic does not exist any more. Reload the page.'))


def _posted_question(questionnaire, post, field='question_id'):
    # The questionnaire is the organization's, so another organization's question is not found
    try:
        return Question.objects.get(id=int(post.get(field, '')), section__questionnaire=questionnaire)
    except (ValueError, Question.DoesNotExist):
        raise EditorError(_('This question does not exist any more. Reload the page.'))


def _question_form(request, context, question):
    """The HTML of the open question: the form of a question of the context, or of a new, unsaved one."""

    if question.pk:
        question = next(
            (item for section in context['sections'] for item in section.questions.all() if item == question), None,
        )

        # Deleted after it was looked up
        if question is None:
            raise EditorError(_('This question does not exist any more. Reload the page.'))

        did_not_observe = question.offers_did_not_observe
    else:
        question.scoring = question_scoring(question)
        question.answer_count = 0
        did_not_observe = None

    # A new question, or a type without the box, offers it unless no question of the questionnaire does
    if did_not_observe is None or question.question_type not in DID_NOT_OBSERVE_TYPES:
        did_not_observe = context['did_not_observe']() != 'off'

    form_context = {
        **_question_context(context, question),
        'translated': translated_into(question),
        'translated_any': languages_with_translation(question),
        'did_not_observe_checked': did_not_observe,
    }

    return render_to_string('admin_dashboard/editor/_question_form.html', form_context, request=request)


def _open_question(request, questionnaire):
    """The answer to GET ?question=<id> (a stored question) or ?new_in=<section id> (a new question in that topic)."""

    if 'question' in request.GET:
        question = _posted_question(questionnaire, request.GET, 'question')
    else:
        section = _posted_section(questionnaire, request.GET, 'new_in')
        _, labels = get_default_labels(questionnaire)
        # Nothing is stored until the creator writes the question
        question = Question(
            section=section, question_type='rating', config={'min': 1, 'max': len(labels)}, labels=labels,
            required=True,
        )

    return editor_response(request, questionnaire, [], html=lambda context: _question_form(request, context, question))


def _translate_action(request, questionnaire, action):
    """Run one action of the translate mode. It saves translations only: an action that changes the structure or the
    original texts is refused and changes nothing, as is a language that is no translation language."""

    post = request.POST

    if action == 'refresh':
        return editor_response(request, questionnaire, [])

    language = _translation_language(questionnaire, post)

    if action != 'save_translation' or language is None:
        raise EditorError(_('This change is not possible. Reload the page.'))

    field_name = post.get('field_name', '')
    errors = save_one_translation(
        questionnaire, language, field_name, post.get('value', ''), still_correct=bool(post.get('still_correct')),
    )

    if errors:
        raise EditorError(errors[0])

    return editor_response(request, questionnaire, ['langs', f'text-{field_name}'])


def _editor_action(request, questionnaire, action):
    """Run one action of the editor page and answer the slots it can change."""

    post = request.POST

    if 'lang' in post or action == 'save_translation':
        return _translate_action(request, questionnaire, action)

    if action == 'save_info':
        save_info(questionnaire, post)
        return editor_response(request, questionnaire, ['langs'])

    if action == 'set_did_not_observe':
        set_did_not_observe(questionnaire, bool(post.get('on')))
        return editor_response(request, questionnaire, ['did-not-observe'])

    if action == 'add_section':
        section = add_section(questionnaire)

        def topic_card(context):
            card_section = next(item for item in context['sections'] if item.id == section.id)
            return render_to_string(
                'admin_dashboard/editor/_topic.html', {**context, 'section': card_section}, request=request,
            )

        # The count on the language tabs: the new topic's title has no translation
        return editor_response(request, questionnaire, ['langs'], section_id=section.id, html=topic_card)

    if action == 'save_section':
        section = _posted_section(questionnaire, post)
        save_section(section, post.get('title'), post.get('description'))
        return editor_response(request, questionnaire, [f'topic-{section.id}-head', 'langs'])

    if action == 'delete_section':
        _posted_section(questionnaire, post).delete()
        return editor_response(request, questionnaire, ['langs'])

    if action == 'save_question':
        question = _posted_question(questionnaire, post) if post.get('question_id') else None
        section = None if question else _posted_section(questionnaire, post)
        question = save_question(questionnaire, post, question, section)
        # The labels are sent only for a score: a question of another type keeps the fields typed for a score
        parts = ['row', 'report', 'labels'] if question.question_type == 'rating' else ['row', 'report']
        extra = {
            'question_id': question.id,
            # The ids of the stored answers in their order, for the answer rows that were posted
            'option_ids': list(question.options.values_list('id', flat=True)),
        }

        if section:
            extra['row_html'] = lambda context: _render_editor_slot(request, context, f'question-{question.id}-row')

        return editor_response(
            request, questionnaire,
            [*(f'question-{question.id}-{part}' for part in parts), f'topic-{question.section_id}-head', 'report-card',
             'langs', 'did-not-observe'],
            **extra,
        )

    if action == 'delete_question':
        question = _posted_question(questionnaire, post)
        question.delete()

        return editor_response(
            request, questionnaire, [f'topic-{question.section_id}-head', 'report-card', 'langs', 'did-not-observe'],
        )

    if action == 'reorder':
        try:
            save_layout(questionnaire, json.loads(post.get('layout', '')))
        except (ValueError, TypeError, KeyError):
            raise EditorError(_('The new order could not be saved. Reload the page and try again.'))

        # A question that moved to another topic can change the radar point of both
        return editor_response(
            request, questionnaire, [f'topic-{section.id}-head' for section in questionnaire.sections.all()],
        )

    if action in ('save_advice', 'try_advice'):
        question = _advice_question(questionnaire, post)
        # Checked before anything is stored, so a stored change never answers a refusal
        _advice_try_values(post)

        if action == 'save_advice':
            stored = save_advice(question, post)
            # "Advice (n)" in the table of the report card. The keys of the stored lines, in their order, for the lines
            # that were posted, so the next save keeps them
            keys = [item['key'] for item in stored.action_items]

            return editor_response(request, questionnaire, ['report-card', 'advice-try'], keys=keys)

        return editor_response(request, questionnaire, ['advice-try'])

    # The weight and the models also show in part 3 of the open question
    # Only ASCII digits: isdigit() also takes "²", which is no id and no slot
    open_report = [f'question-{post["open"]}-report'] if re.fullmatch('[0-9]+', post.get('open', '')) else []

    if action == 'set_weight':
        question = _posted_question(questionnaire, post)

        try:
            weight = float(post.get('weight', ''))
        except ValueError:
            raise EditorError(_('This weight is not possible.'))

        set_weight(question, post.get('model'), weight)
        return editor_response(request, questionnaire, ['report-card', f'question-{question.id}-report'])

    if action == 'clear_model':
        clear_model(questionnaire, post.get('model'))
        return editor_response(request, questionnaire, ['report-card', *open_report])

    # refresh: a model ticked or unticked changes the card and the open question
    return editor_response(request, questionnaire, ['report-card', *open_report])


EDITOR_ACTIONS = (
    'refresh', 'save_info', 'set_did_not_observe', 'add_section', 'save_section', 'delete_section', 'reorder',
    'save_question', 'delete_question', 'set_weight', 'clear_model', 'save_translation', 'save_advice', 'try_advice',
)


@login_required
@can_manage_questionnaires_required
def questionnaire_edit(request, questionnaire_uuid):
    """The editor of a questionnaire: GET gives the page, GET ?lang= the page in the translate mode, GET ?question= or
    ?new_in= the open question, and every POST of the page answers JSON (editor_response)."""
    # Get organization from request context
    org = getattr(request, 'organization', None)

    # Filter by organization to prevent cross-org access
    questionnaire = get_object_or_404(
        Questionnaire,
        uuid=questionnaire_uuid,
        organization=org
    )

    if request.method == 'GET' and 'advice' in request.GET:
        try:
            return _advice_dialog(request, questionnaire)
        except EditorError as error:
            return JsonResponse({'ok': False, 'message': f'{error}'}, status=400)

    if request.method == 'GET' and ('question' in request.GET or 'new_in' in request.GET):
        try:
            return _open_question(request, questionnaire)
        except EditorError as error:
            return JsonResponse({'ok': False, 'message': f'{error}'}, status=400)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action in EDITOR_ACTIONS:
            try:
                return _editor_action(request, questionnaire, action)
            except EditorError as error:
                return JsonResponse({'ok': False, 'message': f'{error}'}, status=400)

        return JsonResponse({'ok': False, 'message': _('This change is not possible. Reload the page.')}, status=400)

    # An unknown language and the original one give the page in the original language
    context = _with_language(
        editor_context(load_for_editor(questionnaire), []), _translation_language(questionnaire, request.GET),
    )

    return render(request, 'admin_dashboard/questionnaire_editor.html', context)


@login_required
@can_manage_questionnaires_required
def questionnaire_translate(request, questionnaire_uuid, language):
    """The old translation page: translating is the translate mode of the questionnaire editor now."""

    questionnaire = get_object_or_404(
        Questionnaire,
        uuid=questionnaire_uuid,
        organization=request.organization,
    )

    if not is_language(language) or language == questionnaire.source_language:
        raise Http404

    return redirect(f"{reverse('questionnaire_edit', args=[questionnaire.uuid])}?lang={language}")


@login_required
@can_manage_questionnaires_required
def questionnaire_delete(request, questionnaire_uuid):
    """Delete a questionnaire, or archive it when review cycles depend on it.

    ReviewCycle.questionnaire is on_delete=PROTECT, so a questionnaire that
    has been used cannot be deleted at all — its cycles and reports would
    lose the questions their answers refer to. Those are archived instead:
    gone from every selection list, still there for the existing reports.
    """
    org = getattr(request, 'organization', None)
    questionnaire = get_object_or_404(Questionnaire, uuid=questionnaire_uuid, organization=org)
    cycle_count = questionnaire.review_cycles.count()

    if request.method == 'POST':
        name = questionnaire.name

        if cycle_count:
            questionnaire.is_active = False
            questionnaire.save(update_fields=['is_active'])
            messages.success(
                request,
                _('Questionnaire "%(name)s" archived. It is used by %(count)s '
                  'review cycle(s) and cannot be deleted.')
                % {'name': name, 'count': cycle_count}
            )
        else:
            try:
                questionnaire.delete()
            except ProtectedError:
                # A cycle appeared between the count above and this delete.
                questionnaire.is_active = False
                questionnaire.save(update_fields=['is_active'])
                messages.warning(
                    request,
                    _('Questionnaire "%(name)s" is now in use and was archived '
                      'instead of deleted.') % {'name': name}
                )
            else:
                messages.success(request, _('Questionnaire "%(name)s" deleted.') % {'name': name})

        return redirect('questionnaire_list')

    context = {
        'questionnaire': questionnaire,
        'cycle_count': cycle_count,
    }

    return render(request, 'admin_dashboard/questionnaire_confirm_delete.html', context)


@login_required
@can_manage_questionnaires_required
@require_POST
def questionnaire_restore(request, questionnaire_uuid):
    """Put an archived questionnaire back into circulation."""
    org = getattr(request, 'organization', None)
    questionnaire = get_object_or_404(Questionnaire, uuid=questionnaire_uuid, organization=org)

    questionnaire.is_active = True
    questionnaire.save(update_fields=['is_active'])
    messages.success(request, _('Questionnaire "%(name)s" restored.') % {'name': questionnaire.name})

    return redirect('questionnaire_list')


# Where a cycle stands, from its status and response counts. Together the
# stages cover every cycle exactly once. Conditions use the token_count and
# completed_count annotations of review_cycle_list.
CYCLE_SORTS = {
    'newest': (gettext_lazy('Newest first'), ['-created_at']),
    'oldest': (gettext_lazy('Oldest first'), ['created_at']),
    'reviewee': (gettext_lazy('Reviewee A–Z'), ['reviewee__name']),
    'fewest_responses': (gettext_lazy('Fewest responses'), ['completed_count']),
}


@login_required
def review_cycle_list(request):
    """List all review cycles"""
    org = request.organization

    if org:
        # Cycles of anonymized (GDPR-deleted) reviewees are never listed.
        cycles_qs = ReviewCycle.objects.for_organization(org, include_deleted=True).exclude(
            reviewee__email__icontains='@deleted.invalid').select_related(
            'reviewee', 'questionnaire', 'created_by'
        )
    else:
        cycles_qs = ReviewCycle.objects.select_related(
            'reviewee', 'questionnaire', 'created_by'
        )

    below = set() if can_view_all_reports(request.user) else direct_report_emails(request.user, org)
    run_team = run_team_emails(request.user, org)
    if below:
        # Managers also see the cycles of their direct reports in the org
        # chart: to run them when they may create cycles for others, else
        # only to read the report (see report_only below).
        own = visible_cycles(request.user, cycles_qs).values('pk')
        cycles_qs = cycles_qs.annotate(reviewee_email_lower=Lower('reviewee__email')).filter(
            Q(pk__in=own) | Q(reviewee_email_lower__in=below))
    else:
        cycles_qs = visible_cycles(request.user, cycles_qs)
    # Cycles of deactivated people (leavers) are left out, as on the dashboard.
    # "Show deactivated people" lists them, so their past reports can be found.
    has_deactivated = cycles_qs.filter(reviewee__is_active=False).exists()
    show_deactivated = has_deactivated and request.GET.get('deactivated') == '1'
    if not show_deactivated:
        cycles_qs = cycles_qs.filter(reviewee__is_active=True)
    # Questionnaires that occur in this user's cycles, archived ones included.
    used_questionnaires = Questionnaire.objects.filter(
        review_cycles__in=cycles_qs).distinct().order_by('name')

    q = request.GET.get('q', '').strip()
    if q:
        cycles_qs = cycles_qs.filter(Q(reviewee__name__icontains=q) | Q(reviewee__email__icontains=q))
    questionnaire_filter = request.GET.get('questionnaire', '')
    if questionnaire_filter:
        try:
            cycles_qs = cycles_qs.filter(questionnaire__uuid=questionnaire_filter)
        except ValidationError:
            questionnaire_filter = ''

    cycles_qs = dashboard_state.with_progress(cycles_qs.prefetch_related(
        'questionnaire__sections__questions'
    )).annotate(
        # Queued emails the outbox could not send, so a mail problem shows in the list
        failed_emails=dashboard_state.failed_emails(),
        reviewee_has_active_cycle=Exists(
            ReviewCycle.objects.filter(reviewee=OuterRef('reviewee'), status='active')),
    )

    # The dashboard links here with one thing that cycles need, such as a reminder.
    threshold = org.min_responses_for_anonymity if org else 3
    cycle_needs = dashboard_state.cycle_needs(threshold)
    needs = request.GET.get('needs', '')
    if needs in cycle_needs:
        cycles_qs = cycles_qs.filter(cycle_needs[needs][1])
    else:
        needs = ''

    # Counts follow the search and questionnaire filters, so each stage
    # button shows what clicking it would give.
    stages = dashboard_state.cycle_stages(threshold)
    stage_counts = {stage: cycles_qs.filter(cond).count() for stage, (_label, cond) in stages.items()}
    stage = request.GET.get('stage', '')
    if stage in stages:
        cycles_qs = cycles_qs.filter(stages[stage][1])
    else:
        stage = ''

    sort = request.GET.get('sort', '')
    if sort not in CYCLE_SORTS:
        sort = 'newest'
    cycles_qs = cycles_qs.order_by(*CYCLE_SORTS[sort][1], '-created_at')

    # Get per_page from request, default to 25
    per_page = request.GET.get('per_page', '25')
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25

    # Paginate cycles
    paginator = Paginator(cycles_qs, per_page)
    page = request.GET.get('page')
    try:
        cycles = paginator.page(page)
    except PageNotAnInteger:
        cycles = paginator.page(1)
    except EmptyPage:
        cycles = paginator.page(paginator.num_pages)

    # Get available questionnaires for quick cycle creation
    questionnaires = list(
        Questionnaire.objects.for_organization(org).filter(is_active=True).order_by('-is_default', 'name'))
    default_questionnaire = questionnaires[0] if questionnaires else None

    # "New Cycle" opens the start dialog of the reviewee list, set up as a copy of the row's cycle.
    for cycle in cycles:
        cycle.report_only = cycle.reviewee.email.lower() in below - run_team
        cycle.start = {
            'reviewee': cycle.reviewee,
            'source_cycle': cycle,
            'latest_questionnaire': cycle.questionnaire,
            'selected_questionnaire': cycle.questionnaire if cycle.questionnaire.is_active else default_questionnaire,
            'active_cycle': cycle.reviewee_has_active_cycle,
        }

    context = {
        'cycles': cycles,  # Paginated object
        'questionnaires': questionnaires,
        'per_page': per_page,
        'q': q,
        'questionnaire_filter': questionnaire_filter,
        'used_questionnaires': used_questionnaires,
        'stage': stage,
        'stages': [(key, label, stage_counts[key]) for key, (label, _cond) in stages.items()],
        'needs': needs,
        'needs_label': cycle_needs[needs][0] if needs else '',
        'total_count': sum(stage_counts.values()),
        'sort': sort,
        'sorts': [(key, label) for key, (label, _fields) in CYCLE_SORTS.items()],
        'is_filtered': bool(q or questionnaire_filter or stage or needs),
        'has_deactivated': has_deactivated,
        'show_deactivated': show_deactivated,
    }

    return render(request, 'admin_dashboard/review_cycle_list.html', context)


def selected_category_flags(request):
    """Read the category checkboxes as include_* flags for ReviewCycle.

    An unchecked box is absent from the POST, so "all four cleared" and "a
    client that predates the checkboxes" look identical. The form sends a
    hidden marker to tell them apart; without it this returns {} and the
    model defaults apply — all four, the way every cycle worked before.
    """
    if request.POST.get('categories_submitted') != '1':
        return {}

    return {
        f'include_{category}': request.POST.get(f'include_{category}') == 'on'
        for category in CATEGORY_ORDER
    }


def selected_units(request):
    """
    The org chart units ticked on the bulk form; none ticked is a run for everyone.
    A value that is no unit of this organization is a 404: to drop it could
    widen the run to everyone.
    """
    values = set(request.POST.getlist('bulk_units'))
    try:
        units = list(OrgUnit.objects.filter(organization=request.organization, uuid__in=[UUID(v) for v in values]))
    except ValueError:
        raise Http404
    if len(units) != len(values):
        raise Http404
    return units


def bulk_reviewees(user, org, units=()):
    """
    The people a bulk run makes cycles for: everyone this user may start a cycle
    for, or of those only the managers and members of `units`.
    """
    reviewees = creatable_reviewees(user, org)
    if units:
        # ponytail: the units as ticked, not the units below them; walk the chart
        # down here if a parent unit must take its teams along
        reviewees = reviewees.filter(pk__in=OrgUnitMembership.objects.filter(unit__in=units).values('reviewee_id'))
    return reviewees


def plan_bulk_cycles(reviewees, bulk_source, questionnaire, category_flags):
    """
    Work out which cycles a bulk run creates, without creating them. The form
    shows the numbers before the run, and the credit check counts only the
    people who really get a cycle.

    `bulk_source` controls the reviewers of each cycle:
        'chart' — derive from the org chart for each reviewee
        'previous' — each reviewee's latest cycle: its questionnaire,
                     categories and reviewer email strings (never FKs),
                     without the addresses of deactivated people
        'empty' — no reviewers yet (admins fill them in per cycle later)

    Returns (planned, skipped): planned is a list of (reviewee, questionnaire,
    category flags, email assignments or None); skipped counts the people who
    get no cycle.
    """
    # The categories this run collects, read off an unsaved cycle
    # so the defaults match what the created cycles will have.
    active_categories = ReviewCycle(**category_flags).active_categories
    unplaced_count = 0
    planned = []
    for reviewee in reviewees:
        email_assignments = None
        cycle_questionnaire, cycle_flags = questionnaire, category_flags
        if bulk_source == 'previous':
            previous = previous_cycle_reviewers(reviewee)
            # Archived questionnaires do not come back this way.
            if previous is None or not previous[0].questionnaire.is_active:
                unplaced_count += 1
                continue
            cycle, email_assignments = previous
            cycle_questionnaire = cycle.questionnaire
            cycle_flags = {f'include_{c}': getattr(cycle, f'include_{c}') for c in CATEGORY_ORDER}
        elif bulk_source == 'chart':
            buckets = derive_reviewers(reviewee)
            # Build the email_assignments dict the existing
            # helper expects: emails only, no Reviewee FK.
            email_assignments = {
                code: [p.email.lower() for p in buckets.get(code, []) if p.email]
                for code in active_categories
            }
            # Nobody but the reviewee: a worker in an upward run,
            # the person at the top in a peer run. No cycle, no lone
            # self-assessment, no credit spent.
            if not any(emails for code, emails in email_assignments.items() if code != 'self'):
                unplaced_count += 1
                continue

        planned.append((reviewee, cycle_questionnaire, cycle_flags, email_assignments))
    return planned, unplaced_count


def skipped_sentence(bulk_source, skipped):
    """Why a bulk run skips people, as a list with one sentence; empty when it skips nobody."""
    if not skipped:
        return []
    if bulk_source == 'chart':
        return [ngettext(
            '%(skipped)s person is skipped: the org chart gives no reviewers for the selected categories.',
            '%(skipped)s people are skipped: the org chart gives them no reviewers for the selected categories.',
            skipped) % {'skipped': skipped}]
    return [ngettext(
        '%(skipped)s person is skipped: no previous cycle with reviewers and an active questionnaire.',
        '%(skipped)s people are skipped: no previous cycle with reviewers and an active questionnaire.',
        skipped) % {'skipped': skipped}]


@login_required
@require_POST
def review_cycle_bulk_preview(request):
    """What a bulk run with the posted form would create, as a sentence for the form. Creates nothing."""
    if not may_create_for_others(request.user):
        raise Http404
    bulk_source = request.POST.get('bulk_source', 'empty')
    units = selected_units(request)
    reviewees = bulk_reviewees(request.user, request.organization, units)
    planned, skipped = plan_bulk_cycles(reviewees, bulk_source, None, selected_category_flags(request))
    count = len(planned)
    if units:
        sentence = ngettext(
            'This creates %(count)s cycle, for %(count)s of the %(total)s people in the selected departments.',
            'This creates %(count)s cycles, for %(count)s of the %(total)s people in the selected departments.',
            count)
    else:
        sentence = ngettext(
            'This creates %(count)s cycle, for %(count)s of the %(total)s people you can create cycles for.',
            'This creates %(count)s cycles, for %(count)s of the %(total)s people you can create cycles for.',
            count)
    parts = [sentence % {'count': count, 'total': count + skipped}]
    parts += skipped_sentence(bulk_source, skipped)
    return JsonResponse({'count': count, 'skipped': skipped, 'message': ' '.join(parts)})


def create_single_cycle(request, reviewee, questionnaire, category_flags, email_assignments, send_now):
    """
    Create the cycle of one reviewee with a token per reviewer email, put the
    reviewee's emails in the outbox and, with `send_now`, the invitations.
    Raises NoCycleCredits and ReviewerLimit; a refused token leaves no cycle behind.
    """
    with transaction.atomic():
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=request.user,
            status='active',
            **category_flags
        )

        # Create tokens dynamically based on email count, then assign them
        # to the emails with randomization.
        for category_code, emails in email_assignments.items():
            for _email in emails:
                ReviewerToken.objects.create(cycle=cycle, category=category_code)
        assign_stats = assign_tokens_to_emails(cycle, email_assignments) if any(email_assignments.values()) else None

    # The reviewee's emails go in the outbox. After the tokens: the
    # self-assessment goes to the one the form addressed.
    queue_reviewee_notifications(cycle)

    if send_now and assign_stats and assign_stats['assigned'] > 0:
        queue_invitations(cycle.tokens.all())
    return cycle


@login_required
def review_cycle_create(request):
    """Create a new review cycle (single or bulk)"""
    if request.method == 'POST':
        bulk_source = request.POST.get('bulk_source', 'empty')
        # The form of a self-only member has no mode. The org chart or the
        # previous cycle as the source of the reviewers makes it a bulk run:
        # bulk_reviewees gives only the people this user may create a cycle
        # for, so for them it is a run of one.
        creation_mode = request.POST.get('creation_mode') or (
            'bulk' if bulk_source in ('chart', 'previous') else 'single')
        units = selected_units(request) if creation_mode == 'bulk' else []
        questionnaire_id = request.POST.get('questionnaire')
        # Reusing earlier cycles takes the questionnaire and categories from each of them.
        reuse_previous = creation_mode == 'bulk' and bulk_source == 'previous'

        if not questionnaire_id and not reuse_previous:
            messages.error(request, _('Questionnaire is required.'))
            return redirect('review_cycle_create')

        category_flags = selected_category_flags(request)
        if category_flags and not any(category_flags.values()) and not reuse_previous:
            messages.error(request, _('Select at least one feedback category.'))
            return redirect('review_cycle_create')

        try:
            # Get organization from request context
            org = getattr(request, 'organization', None)

            # Filter by organization to prevent cross-org access; archived
            # ones are gone from the form and must not come back through POST.
            questionnaire = None if reuse_previous else Questionnaire.objects.get(
                id=questionnaire_id,
                organization=org,
                is_active=True
            )
            created_cycles = []

            if creation_mode == 'bulk':
                # Create cycles for all active reviewees. Intentionally do NOT
                # send any emails here — the admin confirms sending on the
                # follow-up bulk_send_invitations page. This prevents the
                # request from stalling on SMTP and avoids surprise blasts.
                reviewees = bulk_reviewees(request.user, org, units)
                derived_count = 0
                planned, unplaced_count = plan_bulk_cycles(reviewees, bulk_source, questionnaire, category_flags)

                # Refuse the whole batch up front so the message can say how
                # many credits it needs; the model gate still backs this up.
                credits = cycle_credits(org)
                if credits is not None and len(planned) > credits:
                    raise NoCycleCredits(needed=len(planned), available=credits)

                with transaction.atomic():
                    for reviewee, cycle_questionnaire, cycle_flags, email_assignments in planned:
                        cycle = ReviewCycle.objects.create(
                            reviewee=reviewee,
                            questionnaire=cycle_questionnaire,
                            created_by=request.user,
                            status='active',
                            **cycle_flags
                        )
                        created_cycles.append(cycle)

                        if email_assignments:
                            for cat_code, emails in email_assignments.items():
                                for _email in emails:
                                    ReviewerToken.objects.create(cycle=cycle, category=cat_code)
                            assign_tokens_to_emails(cycle, email_assignments)
                            derived_count += 1

                # Stash the cycle UUIDs in the session for the send-invitations
                # confirmation step. Session avoids URL-length limits when the
                # org has many reviewees.
                request.session['pending_invitation_cycles'] = [
                    str(c.uuid) for c in created_cycles
                ]
                request.session['pending_bulk_source'] = bulk_source

                # One sentence per count, so each can take its plural form; and
                # nothing about skipped people when nobody was skipped.
                created = len(created_cycles)
                if bulk_source == 'chart':
                    sentence = ngettext(
                        'Created %(count)s review cycle with reviewers from the org chart.',
                        'Created %(count)s review cycles with reviewers from the org chart.',
                        created) % {'count': created}
                    messages.success(request, ' '.join([sentence, *skipped_sentence(bulk_source, unplaced_count)]))
                elif bulk_source == 'previous':
                    sentence = ngettext(
                        'Created %(count)s review cycle with the questionnaire and reviewers of the previous cycle of that person.',
                        'Created %(count)s review cycles, each with the questionnaire and reviewers of the previous cycle of that person.',
                        created) % {'count': created}
                    messages.success(request, ' '.join([sentence, *skipped_sentence(bulk_source, unplaced_count)]))
                else:
                    messages.success(
                        request,
                        _('Created %(count)s review cycles. No invitations have been sent yet.')
                        % {'count': len(created_cycles)}
                    )
                return redirect('bulk_send_invitations')

            else:
                # Single reviewee mode
                reviewee_id = request.POST.get('reviewee')
                if not reviewee_id:
                    messages.error(request, _('Reviewee is required for single cycle creation.'))
                    return redirect('review_cycle_create')

                reviewee = creatable_reviewees(request.user, org).get(id=reviewee_id)

                # Reviewer selections from the picker and the email textareas.
                # The form hides categories this cycle skips; a stale or
                # hand-made POST must not reinstate them.
                active = [c for c in CATEGORY_ORDER if category_flags.get(f'include_{c}', True)]
                people, emails, warnings = posted_setup(request, org, active)
                email_assignments = posted_emails(people, emails)
                for w in warnings:
                    messages.warning(request, w)
                send_now = request.POST.get('send_invitations_now') == '1'

                cycle = create_single_cycle(
                    request, reviewee, questionnaire, category_flags, email_assignments, send_now)

                # The list of the reviewee is what the form sent, once the cycle stands.
                listed = ('manager', 'peer', 'direct_report')
                if any(people[c] or emails[c] for c in listed):
                    save_review_setup(
                        reviewee, questionnaire,
                        {f'include_{c}': getattr(cycle, f'include_{c}') for c in CATEGORY_ORDER},
                        {c: people[c] for c in listed}, {c: emails[c] for c in listed})

                if any(email_assignments.values()):
                    assigned = cycle.tokens.filter(reviewer_email__isnull=False).count()
                    if send_now and assigned > 0:
                        messages.success(
                            request,
                            _('Review cycle created for "%(name)s" with %(assigned)s reviewer(s) invited. The invitation emails go out within about five minutes.')
                            % {'name': reviewee.name, 'assigned': assigned}
                        )
                        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)
                    else:
                        messages.success(
                            request,
                            _('Review cycle created for "%(name)s" with %(assigned)s reviewer(s) assigned. Visit the invitations page to send emails.')
                            % {'name': reviewee.name, 'assigned': assigned}
                        )
                        # Redirect to invitations page to send emails
                        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)
                else:
                    # No emails provided, show success and redirect to invitations.
                    # The reviewee's emails were queued by create_single_cycle.
                    messages.success(
                        request,
                        _('Review cycle created for "%(name)s". The reviewee\'s emails go out within about five minutes.')
                        % {'name': reviewee.name}
                    )
                    # Redirect to invitations page to add reviewers
                    return redirect('manage_invitations', cycle_uuid=cycle.uuid)

        except NoCycleCredits as e:
            messages.error(request, str(e))
            if can_see_billing(org, request.user):
                return redirect(f"{reverse('billing')}?reviews={e.needed - e.available}")
            return redirect('review_cycle_create')
        except ReviewerLimit as e:
            limit_error(request, e)
            return redirect('review_cycle_create')
        except Exception as e:
            messages.error(request, _('Error creating review cycle: %(error)s') % {'error': str(e)})
            return redirect('review_cycle_create')

    # GET request - show form
    org = request.organization or (request.user.profile.organization if hasattr(request.user, 'profile') else None)

    # Filter reviewees based on user permissions
    reviewees = creatable_reviewees(request.user, org).order_by('name')

    # Only show questionnaires from user's organization.
    # Prefetch sections/questions so report_type_label doesn't N+1 per option.
    questionnaires = (
        Questionnaire.objects.for_organization(org)
        .filter(is_active=True)
        .prefetch_related('sections__questions')
        .order_by('-is_default', 'name')
    )

    # Org chart availability drives the default for the bulk-source radio:
    # if at least one unit exists we pre-select "derive from chart"; otherwise
    # only "leave empty" is offered.
    units = list(OrgUnit.objects.filter(organization=org).order_by('name')) if org is not None else []
    has_org_chart = bool(units)
    creates_for_whole_organization = request.user.has_perm('accounts.can_manage_organization')

    can_create_for_others = may_create_for_others(request.user)
    context = {
        'reviewees': reviewees,
        'questionnaires': questionnaires,
        'can_create_for_others': can_create_for_others,
        # The reviewer sources that give a self-only member a cycle: the form offers only those.
        'own_sources': set() if can_create_for_others else {
            source for source in ('chart', 'previous') if plan_bulk_cycles(reviewees, source, None, {})[0]},
        'creates_for_whole_organization': creates_for_whole_organization,
        **billing_context(org, request.user),
        'has_org_chart': has_org_chart,
        # A run for some departments is for those who otherwise run it for everyone.
        'bulk_units': units if creates_for_whole_organization else [],
        'has_previous_cycles': ReviewCycle.objects.filter(reviewee__in=reviewees).exists(),
    }

    return render(request, 'admin_dashboard/review_cycle_form.html', context)


@login_required
def bulk_send_invitations(request):
    """Confirm + queue the emails for cycles just created in bulk.

    The `review_cycle_create` view stashes the UUIDs of freshly-bulk-created
    cycles in the session under 'pending_invitation_cycles'. This view renders
    them for review on GET and puts the emails in the outbox on POST; the
    send_queued_invitations cron sends them.
    """
    org = request.organization
    uuids = request.session.get('pending_invitation_cycles', [])
    bulk_source = request.session.get('pending_bulk_source', 'empty')

    cycles_qs = (
        ReviewCycle.objects
        .select_related('reviewee', 'questionnaire')
        .prefetch_related('questionnaire__sections__questions', 'tokens')
        .filter(uuid__in=uuids)
    )
    if org:
        cycles_qs = cycles_qs.filter(reviewee__organization=org)
    cycles = list(cycles_qs.order_by('reviewee__name'))

    if request.method == 'POST':
        if not cycles:
            messages.info(request, _('No pending cycles to send invitations for.'))
            return redirect('review_cycle_list')

        # Chart-derived cycles already hold every reviewer's address, the
        # reviewee's own self-assessment included. The cron sends one email
        # per address across all the cycles, so a person who reviews several
        # colleagues on several questionnaires gets a single mail with every
        # link. Other bulk runs keep the per-cycle reviewee emails with the
        # self-assessment and the links to share.
        reviewer_tokens = 0
        reviewer_emails = 0
        if bulk_source not in ('chart', 'previous'):
            for cycle in cycles:
                queue_reviewee_notifications(cycle)
        else:
            pending_tokens = ReviewerToken.objects.filter(
                cycle__in=cycles,
                reviewer_email__isnull=False,
                invitation_sent_at__isnull=True,
                completed_at__isnull=True,
            )
            addresses = {email.lower() for email in pending_tokens.values_list('reviewer_email', flat=True)}
            reviewer_emails = len(addresses)
            reviewer_tokens = queue_invitations(pending_tokens)

        # Clear the session once the emails are queued.
        request.session.pop('pending_invitation_cycles', None)
        request.session.pop('pending_bulk_source', None)

        if reviewer_tokens:
            messages.success(
                request,
                _('Invitations for %(count)s review cycle(s) are queued. %(tokens)s reviewer invitations go out in %(emails)s emails, one per address, within about five minutes.')
                % {'count': len(cycles), 'tokens': reviewer_tokens, 'emails': reviewer_emails}
            )
        else:
            messages.success(
                request,
                _('Invitations for %(count)s review cycle(s) are queued and go out within about five minutes.') % {'count': len(cycles)}
            )
        return redirect('review_cycle_list')

    # Per-cycle reviewer counts for the preview table.
    cycle_summaries = []
    for cycle in cycles:
        counts = {'self': 0, 'manager': 0, 'peer': 0, 'direct_report': 0}
        for t in cycle.tokens.all():
            if t.category in counts and t.reviewer_email:
                counts[t.category] += 1
        cycle_summaries.append({'cycle': cycle, 'counts': counts, 'total': sum(counts.values())})

    context = {
        'cycles': cycles,
        'cycle_summaries': cycle_summaries,
        'bulk_source': bulk_source,
        'with_reviewers': bulk_source in ('chart', 'previous'),
    }
    return render(request, 'admin_dashboard/bulk_send_invitations.html', context)


@login_required
def review_cycle_detail(request, cycle_uuid):
    """View details of a review cycle"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    tokens = cycle.tokens.all().order_by('category', 'created_at')

    # Group tokens by category
    tokens_by_category = {}
    for token in tokens:
        category = token.get_category_display()
        if category not in tokens_by_category:
            tokens_by_category[category] = []
        tokens_by_category[category].append(token)

    # Calculate completion stats
    total_tokens = tokens.count()
    completed_tokens = tokens.filter(completed_at__isnull=False).count()
    claimed_tokens = tokens.filter(claimed_at__isnull=False).count()
    # An invitation in the outbox is on its way; it is pending again once it failed
    unsent = tokens.filter(reviewer_email__isnull=False, invitation_sent_at__isnull=True, completed_at__isnull=True)
    queued_invites = unsent.filter(invitation_queued_at__isnull=False, email_error='').count()
    pending_invites = unsent.count() - queued_invites
    pending_reminders = tokens.filter(invitation_sent_at__isnull=False, completed_at__isnull=True).count()
    email_invited_count = tokens.filter(reviewer_email__isnull=False).exclude(category='self').count()
    completion_rate = (completed_tokens / total_tokens * 100) if total_tokens > 0 else 0
    claimed_completion_rate = (completed_tokens / claimed_tokens * 100) if claimed_tokens > 0 else 0

    # Get report if exists
    try:
        report = Report.objects.get(cycle=cycle)
        report_exists = True
    except Report.DoesNotExist:
        report = None
        report_exists = False

    context = {
        'cycle': cycle,
        'report': report,
        'tokens_by_category': tokens_by_category,
        'total_tokens': total_tokens,
        'completed_tokens': completed_tokens,
        'pending_tokens': total_tokens - completed_tokens,
        'claimed_tokens': claimed_tokens,
        'pending_invites': pending_invites,
        'queued_invites': queued_invites,
        'pending_reminders': pending_reminders,
        'email_invited_count': email_invited_count,
        'completion_rate': completion_rate,
        'claimed_completion_rate': claimed_completion_rate,
        'report_exists': report_exists,
    }

    return render(request, 'admin_dashboard/review_cycle_detail.html', context)


EMAIL_SENT = ('sent', 'sent_without_pdf')


def lock_cycle(cycle):
    """The cycle, locked until the transaction ends: the finalize_reports cron skips it meanwhile."""
    return ReviewCycle.objects.select_for_update().get(pk=cycle.pk)


def cycle_progress(cycle):
    """
    Invited and answered per active category, counted from the tokens only, and whether the
    group will show in the report. The report hides peers and direct reports below the threshold.
    """
    threshold = cycle.organization.min_responses_for_anonymity
    counts = {
        row['category']: row
        for row in cycle.tokens.values('category').annotate(
            invited=Count('id'), answered=Count('id', filter=Q(completed_at__isnull=False)))
    }
    progress = []
    for category in cycle.active_categories:
        invited = counts.get(category, {}).get('invited', 0)
        answered = counts.get(category, {}).get('answered', 0)
        needed = 0
        if category in ('self', 'manager'):
            shows = 'yes'
        elif invited < threshold:
            shows = 'no'
        elif answered < threshold:
            shows, needed = 'not_yet', threshold - answered
        else:
            shows = 'yes'
        progress.append({'category': category, 'invited': invited, 'answered': answered,
                         'shows': shows, 'needed': needed})
    return progress


@login_required
def generate_report_view(request, cycle_uuid):
    """Generate or regenerate report for a review cycle"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    try:
        with transaction.atomic():
            cycle = lock_cycle(cycle)
            generate_report(cycle)
            # Stores the PDF and sends the email now, the admin expects it
            result, email_errors = finalize_cycle(cycle, force_send=True)

        success_msg = _('Report generated successfully for %(name)s.') % {'name': cycle.reviewee.name}
        if result in EMAIL_SENT:
            success_msg += ' ' + _('Notification email sent.')
        if email_errors:
            success_msg += ' ' + _('(Email errors: %(errors)s)') % {'errors': ', '.join(map(str, email_errors))}

        messages.success(request, success_msg)
    except Exception as e:
        messages.error(request, _('Error generating report: %(error)s') % {'error': str(e)})

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
def close_cycle(request, cycle_uuid):
    """Close/complete a review cycle and generate report if possible"""
    if request.method != 'POST':
        return redirect('review_cycle_detail', cycle_uuid=cycle_uuid)

    cycle = get_cycle_or_404(request, cycle_uuid)

    if cycle.status != 'active':
        messages.warning(request, _('This cycle is already completed.'))
        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    # Check if there are any completed reviews
    completed_count = cycle.tokens.filter(completed_at__isnull=False).count()

    if completed_count == 0:
        messages.error(request, _('Cannot close cycle: No reviews have been completed yet.'))
        return redirect('review_cycle_detail', cycle_uuid=cycle_uuid)

    # Count the responses for the admins' summary before the unused tokens go
    summary = cycle_summary(cycle)

    # Remove unclaimed tokens (tokens that are still active but not claimed)
    # Keep claimed tokens as an indication that the report was closed while people were still working
    unclaimed_tokens = cycle.tokens.filter(claimed_at__isnull=True, completed_at__isnull=True)
    unclaimed_count = unclaimed_tokens.count()
    unclaimed_tokens.delete()

    # Close and finalise under one lock, so the finalize_reports cron can't email the same report too
    error = None
    with transaction.atomic():
        cycle = lock_cycle(cycle)
        cycle.status = 'completed'
        cycle.save()
        try:
            # A failed report leaves the cycle closed; the cron tries again
            with transaction.atomic():
                generate_report(cycle)
                result, _errors = finalize_cycle(cycle, force_send=True)
        except Exception as e:
            logger.exception('Error finalising the report of cycle %s', cycle.id)
            error = e

    if error is None:
        success_msg = _('Cycle closed and report generated for %(name)s.') % {'name': cycle.reviewee.name}
        if result in EMAIL_SENT:
            success_msg += ' ' + _('Notification email sent.')

        messages.success(request, success_msg)
    else:
        messages.error(request, _('Cycle closed but error generating report: %(error)s') % {'error': str(error)})

    send_cycle_summary(cycle, summary)

    return redirect('review_cycle_detail', cycle_uuid=cycle_uuid)


@login_required
def send_reminder_form(request, cycle_uuid):
    """Show form to send reminders for pending reviews"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    # Get pending tokens
    pending_tokens = cycle.tokens.filter(completed_at__isnull=True).order_by('category')

    context = {
        'cycle': cycle,
        'pending_tokens': pending_tokens,
    }

    return render(request, 'admin_dashboard/send_reminder.html', context)


@login_required
def manage_invitations(request, cycle_uuid):
    """Manage reviewer invitations for a cycle"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    # Group tokens by category
    tokens_by_category = {}
    for token in cycle.tokens.all().order_by('category'):
        category = token.get_category_display()
        if category not in tokens_by_category:
            tokens_by_category[category] = []
        tokens_by_category[category].append(token)

    # Statistics
    total_tokens = cycle.tokens.count()
    assigned_tokens = cycle.tokens.filter(reviewer_email__isnull=False).count()
    sent_tokens = cycle.tokens.filter(invitation_sent_at__isnull=False).count()
    completed_tokens = cycle.tokens.filter(completed_at__isnull=False).count()

    context = {
        'cycle': cycle,
        'tokens_by_category': tokens_by_category,
        'total_tokens': total_tokens,
        'assigned_tokens': assigned_tokens,
        'sent_tokens': sent_tokens,
        'unsent_tokens': assigned_tokens - sent_tokens,
        'completed_tokens': completed_tokens,
        'default_language_name': language_name(cycle.organization.default_language),
        'self_token': cycle.tokens.filter(category='self', reviewer_email__isnull=False).first(),
    }

    return render(request, 'admin_dashboard/manage_invitations.html', context)


@login_required
def assign_invitations(request, cycle_uuid):
    """Assign email addresses to reviewer tokens (creating tokens dynamically)"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    if request.method == 'POST':
        categories = cycle.active_categories
        if cycle.tokens.filter(category='self', reviewer_email__isnull=False).exists():
            # The reviewee already has their self-assessment token; another
            # address would start a second one.
            categories = [c for c in categories if c != 'self']
        email_assignments, warnings = collect_reviewer_emails(request, request.organization, categories)
        for w in warnings:
            messages.warning(request, w)

        # All new tokens or none: past the free reviewer cap nothing is added.
        try:
            with transaction.atomic():
                # Create tokens dynamically based on email count
                tokens_created = 0
                for category_code, emails in email_assignments.items():
                    if not emails:
                        continue

                    # Get existing unassigned tokens for this category (only count tokens without emails)
                    existing_unassigned = cycle.tokens.filter(
                        category=category_code,
                        reviewer_email__isnull=True
                    ).count()
                    needed_count = len(emails)

                    # Create additional tokens if needed
                    if needed_count > existing_unassigned:
                        for i in range(needed_count - existing_unassigned):
                            ReviewerToken.objects.create(
                                cycle=cycle,
                                category=category_code
                            )
                            tokens_created += 1

                # Assign tokens to emails with randomization
                language = request.POST.get('language', '')
                stats = assign_tokens_to_emails(cycle, email_assignments, language=language if is_language(language) else '')
        except ReviewerLimit as e:
            limit_error(request, e)
            return redirect('manage_invitations', cycle_uuid=cycle.uuid)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        # Check if user wants to send invitations immediately
        action = request.POST.get('action', 'assign')
        if action == 'assign' and stats['assigned'] > 0:
            # Put the invitations in the outbox
            queued = queue_invitations(cycle.tokens.all())

            if queued:
                messages.success(request, _('Invited %(assigned)s reviewer(s). %(queued)s invitation email(s) go out within about five minutes.') % {'assigned': stats['assigned'], 'queued': queued})
            else:
                messages.success(request, _('Successfully assigned %(assigned)s email(s). Invitations will be sent separately.') % {'assigned': stats['assigned']})
        elif stats['assigned'] > 0:
            messages.success(request, _('Successfully assigned %(assigned)s email(s). No invitations sent yet.') % {'assigned': stats['assigned']})

        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    return redirect('manage_invitations', cycle_uuid=cycle.uuid)


@login_required
def send_invitations(request, cycle_uuid):
    """Queue the email invitations to assigned reviewers: all pending ones, or the one token posted"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    if request.method == 'POST':
        tokens = cycle.tokens.all()
        token_id = request.POST.get('token_id')
        if token_id:
            tokens = tokens.filter(id=token_id)
        queued = queue_invitations(tokens)

        if queued:
            messages.success(request, ngettext(
                '%(count)s invitation email goes out within about five minutes.',
                '%(count)s invitation emails go out within about five minutes.',
                queued,
            ) % {'count': queued})
        else:
            messages.info(request, _('No pending invitations to send.'))

        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
@require_POST
def send_reviewee_links(request, cycle_uuid):
    """Send the reviewee the links to share once more"""
    cycle = get_cycle_or_404(request, cycle_uuid)
    categories = [category for category in cycle.active_categories if category != 'self']

    # The links only open feedback forms while the cycle is active
    if cycle.status != 'active' or not categories:
        messages.error(request, _('This cycle has no links to send.'))
        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    try:
        send_links_email(cycle, categories)
    except Exception as e:
        messages.error(request, _('Failed to send invitation links email: %(error)s') % {'error': str(e)})
    else:
        messages.success(request, _('The links have been sent to %(email)s.') % {'email': cycle.reviewee.email})

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
def send_reminder(request, cycle_uuid):
    """Queue reminder emails for pending reviews. The cron sends one email per reviewer."""
    cycle = get_cycle_or_404(request, cycle_uuid)

    if request.method == 'POST':
        queued = queue_reminders(cycle.tokens.all())

        if queued:
            messages.success(request, ngettext(
                'A reminder for %(count)s open review goes out within about five minutes.',
                'Reminders for %(count)s open reviews go out within about five minutes, one email per reviewer.',
                queued,
            ) % {'count': queued})
        else:
            messages.info(request, _('No pending reminders to send.'))

        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    return redirect('send_reminder_form', cycle_uuid=cycle.uuid)


@login_required
@require_POST
def send_individual_reminder(request, cycle_uuid, token_id):
    """Queue a reminder email to a specific reviewer"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    try:
        # Get the specific token
        token = ReviewerToken.objects.get(id=token_id, cycle=cycle)

        # Check if token has email and invitation was sent
        if not token.reviewer_email:
            messages.error(request, _('Cannot send reminder: no email assigned to this reviewer.'))
            return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

        if not token.invitation_sent_at:
            messages.error(request, _('Cannot send reminder: invitation not sent yet.'))
            return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

        if token.is_completed:
            messages.info(request, _('This reviewer has already completed their feedback.'))
            return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

        queue_reminders(ReviewerToken.objects.filter(pk=token.pk))
        messages.success(request, _('The reminder goes out within about five minutes.'))

    except ReviewerToken.DoesNotExist:
        messages.error(request, _('Reviewer token not found.'))
    except Exception as e:
        messages.error(request, _('Error sending reminder: %(error)s') % {'error': str(e)})

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
@require_POST
def remove_reviewer_token(request, cycle_uuid, token_id):
    """Remove a reviewer token from a cycle (only if not started) - Admin only"""
    # Check organization admin permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to remove reviewers.'))
        return redirect('review_cycle_detail', cycle_uuid=cycle_uuid)

    cycle = get_cycle_or_404(request, cycle_uuid)

    try:
        # Get the specific token
        token = ReviewerToken.objects.get(id=token_id, cycle=cycle)

        # Only allow deletion if reviewer hasn't started (no claimed_at or completed_at)
        if token.claimed_at or token.completed_at:
            messages.error(request, _('Cannot remove: reviewer has already started or completed their feedback.'))
            return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

        # Store info for success message
        category = token.get_category_display()
        email = token.reviewer_email if token.reviewer_email else _('unclaimed token')

        # Delete the token
        token.delete()

        messages.success(request, _('Removed %(category)s reviewer (%(email)s) from cycle.') % {'category': category, 'email': email})

        # Check if all remaining tokens are completed
        remaining_tokens = cycle.tokens.all()
        if remaining_tokens.exists():
            all_completed = not remaining_tokens.filter(completed_at__isnull=True).exists()

            if all_completed and cycle.status == 'active':
                # Auto-close the cycle. The finalize_reports cron makes the report and emails it.
                cycle.status = 'completed'
                cycle.save()
                messages.success(request, _('Cycle automatically closed (all remaining reviewers completed). The report is ready within a few minutes.'))

                send_cycle_summary(cycle)

    except ReviewerToken.DoesNotExist:
        messages.error(request, _('Reviewer token not found.'))
    except Exception as e:
        messages.error(request, _('Error removing reviewer: %(error)s') % {'error': str(e)})

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
@require_POST
def send_report_email(request, cycle_uuid):
    """Send report notification email to reviewee"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    # Check if report exists
    try:
        report = Report.objects.get(cycle=cycle)
    except Report.DoesNotExist:
        messages.error(request, _('No report found for this cycle. Please generate the report first.'))
        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    # Send notification email, with the PDF stored first when there is none
    try:
        with transaction.atomic():
            result, email_errors = finalize_cycle(lock_cycle(cycle), force_send=True)
    except Exception as e:
        logger.exception('Error sending the report email of cycle %s', cycle.id)
        messages.error(request, _('Failed to send email: %(error)s') % {'error': str(e)})
        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    if result in EMAIL_SENT:
        messages.success(request, _('Report email sent to %(name)s at %(email)s.') % {'name': cycle.reviewee.name, 'email': cycle.reviewee.email})
    elif email_errors:
        for error in email_errors:
            messages.error(request, _('Failed to send email: %(error)s') % {'error': error})
    else:
        messages.error(request, _('Failed to send email.'))

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
@can_manage_organization_required
def settings_view(request):
    """Organization and SMTP settings page"""
    # Use the organization from the middleware (set based on user's profile)
    organization = request.organization

    if not organization:
        messages.error(request, _('No organization found. Please run setup first.'))
        return redirect('admin_dashboard')

    # Fields the environment owns are read-only here — setup_organization
    # rewrites them on every container start, so an edit made here would
    # silently disappear on the next restart.
    locked = env_managed_fields(organization)

    def editable(field):
        return field not in locked

    if request.method == 'POST':
        # Check permission to modify organization settings
        if not request.user.has_perm('accounts.can_manage_organization'):
            messages.error(request, _('You do not have permission to modify organization settings.'))
            return redirect('settings')

        # Get which section is being updated
        section = request.POST.get('section', 'all')

        try:
            if section == 'organization':
                # Update organization details
                if editable('name'):
                    organization.name = request.POST.get('name', organization.name)
                if editable('email'):
                    organization.email = request.POST.get('email', organization.email)
                if editable('default_language') and is_language(request.POST.get('default_language')):
                    organization.default_language = request.POST['default_language']
                organization.save()
                messages.success(request, _('Organization details updated successfully.'))

            elif section == 'registration':
                # New user settings
                organization.default_users_can_create_cycles = request.POST.get('default_users_can_create_cycles') == 'on'
                organization.save()
                messages.success(request, _('New user settings updated successfully.'))

            elif section == 'chart':
                # How far down the org chart direct-report reviewers come from.
                raw = request.POST.get('chart_depth', '').strip()
                if request.POST.get('chart_depth_all') == 'on':
                    organization.chart_depth = None
                elif raw.isdigit() and 1 <= int(raw) <= 99:
                    organization.chart_depth = int(raw)
                else:
                    messages.error(request, _('The number of levels must be a number from 1 to 99.'))
                    return redirect('settings')
                organization.chart_managers_only = request.POST.get('chart_who') != 'teams'
                organization.save()
                messages.success(request, _('Org chart settings updated successfully.'))

            elif section == 'reports':
                # Update report settings
                min_responses = request.POST.get('min_responses_for_anonymity', 3)
                try:
                    organization.min_responses_for_anonymity = int(min_responses)
                except (ValueError, TypeError):
                    organization.min_responses_for_anonymity = 3
                organization.hide_below_threshold_from_managers = request.POST.get('hide_below_threshold_from_managers') == 'on'
                organization.auto_send_report_email = request.POST.get('auto_send_report_email') == 'on'
                organization.attach_report_pdf = request.POST.get('attach_report_pdf') == 'on'
                retention = request.POST.get('report_pdf_retention_days', '').strip()
                if not retention:
                    organization.report_pdf_retention_days = None
                else:
                    try:
                        days = int(retention)
                    except ValueError:
                        days = None
                    if days is not None and 1 <= days <= 3650:
                        organization.report_pdf_retention_days = days
                    else:
                        messages.error(request, _('Report PDF retention must be a number of days from 1 to 3650.'))
                organization.save()
                messages.success(request, _('Report settings updated successfully.'))

            elif section == 'email':
                # Update SMTP settings
                if editable('smtp_host'):
                    organization.smtp_host = request.POST.get('smtp_host', '')
                if editable('smtp_port'):
                    try:
                        organization.smtp_port = int(request.POST.get('smtp_port', 587))
                    except (ValueError, TypeError):
                        organization.smtp_port = 587
                if editable('smtp_username'):
                    organization.smtp_username = request.POST.get('smtp_username', '')

                # Only update password if provided
                smtp_password = request.POST.get('smtp_password', '')
                if smtp_password and editable('smtp_password'):
                    organization.smtp_password = smtp_password

                if editable('smtp_use_tls'):
                    organization.smtp_use_tls = request.POST.get('smtp_use_tls') == 'on'
                if editable('from_email'):
                    organization.from_email = request.POST.get('from_email', organization.from_email)
                organization.save()
                messages.success(request, _('Email settings updated successfully.'))

            if locked:
                messages.info(request, _(
                    'Some settings are managed by environment variables and were '
                    'not changed: %(fields)s'
                ) % {'fields': ', '.join(sorted(set(locked.values())))})

            return redirect('settings')
        except Exception as e:
            messages.error(request, _('Error updating settings: %(error)s') % {'error': str(e)})

    # Check if current user has organization admin permission
    is_org_admin = request.user.has_perm('accounts.can_manage_organization')

    # Count total admin users
    admin_profiles = UserProfile.objects.for_organization(organization).select_related('user')
    admin_count = sum(1 for p in admin_profiles if p.user.has_perm('accounts.can_manage_organization'))

    # Get API tokens and webhooks for this organization
    api_tokens = APIToken.objects.for_organization(organization).order_by('-created_at')
    webhooks = WebhookEndpoint.objects.for_organization(organization).order_by('-created_at')

    # Check if there's a newly created token to display
    new_token = request.session.pop('new_api_token', None)
    new_token_name = request.session.pop('new_api_token_name', None)

    context = {
        'organization': organization,
        'is_org_admin': is_org_admin,
        'admin_count': admin_count,
        'is_last_admin': is_org_admin and admin_count == 1,
        'api_tokens': api_tokens,
        'webhooks': webhooks,
        'new_token': new_token,
        'new_token_name': new_token_name,
        'locked_fields': locked,
        'default_report_pdf_retention_days': settings.REPORT_PDF_RETENTION_DAYS,
        **billing_context(organization, request.user),
    }

    return render(request, 'admin_dashboard/settings.html', context)


@login_required
def gdpr_management(request):
    """GDPR data management and deletion for organization admins"""
    # Check permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to access GDPR management.'))
        return redirect('team_list')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('admin_dashboard')

    # Get tab parameter (users or reviewees)
    active_tab = request.GET.get('tab', 'reviewees')

    # Get per_page from request
    per_page = request.GET.get('per_page', '25')
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25

    if active_tab == 'users':
        # List users with data summaries (include GDPR-deleted for audit purposes)
        users_qs = UserProfile.objects.for_organization(
            org, include_deleted=True
        ).select_related('user').order_by('-user__date_joined')

        # Paginate
        paginator = Paginator(users_qs, per_page)
        page = request.GET.get('page')
        try:
            users = paginator.page(page)
        except PageNotAnInteger:
            users = paginator.page(1)
        except EmptyPage:
            users = paginator.page(paginator.num_pages)

        # Add data summaries
        for user_profile in users:
            try:
                user_profile.gdpr_summary = GDPRDeletionService.get_user_data_summary(user_profile.user.id)
            except:
                user_profile.gdpr_summary = None

        context = {
            'active_tab': 'users',
            'users': users,
            'reviewees': None,
            'per_page': per_page,
        }
    else:
        # List reviewees with data summaries (include GDPR-deleted for audit purposes)
        reviewees_qs = Reviewee.objects.for_organization(org, include_deleted=True).select_related('organization').order_by('-created_at')

        # Paginate
        paginator = Paginator(reviewees_qs, per_page)
        page = request.GET.get('page')
        try:
            reviewees = paginator.page(page)
        except PageNotAnInteger:
            reviewees = paginator.page(1)
        except EmptyPage:
            reviewees = paginator.page(paginator.num_pages)

        # Add data summaries
        for reviewee in reviewees:
            try:
                reviewee.gdpr_summary = GDPRDeletionService.get_reviewee_data_summary(reviewee.id)
            except:
                reviewee.gdpr_summary = None

        context = {
            'active_tab': 'reviewees',
            'users': None,
            'reviewees': reviewees,
            'per_page': per_page,
        }

    return render(request, 'admin_dashboard/gdpr_management.html', context)


@login_required
@require_POST
def gdpr_delete_user_view(request, user_id):
    """Delete or anonymize a user (GDPR)"""
    # Check permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to delete users.'))
        return redirect('gdpr_management')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('admin_dashboard')

    try:
        # Get the user profile to verify organization
        user_profile = get_object_or_404(UserProfile, user_id=user_id, organization=org)
        target_user = user_profile.user

        # Prevent self-deletion
        if target_user.id == request.user.id:
            messages.error(request, _('You cannot delete your own account.'))
            return redirect('gdpr_management')

        # Prevent deleting superusers
        if target_user.is_superuser:
            messages.error(request, _('Cannot delete super admin accounts.'))
            return redirect('gdpr_management')

        # Get deletion type from POST
        deletion_type = request.POST.get('deletion_type', 'soft')
        hard_delete = (deletion_type == 'hard')

        # Perform deletion
        result = GDPRDeletionService.delete_user(
            user_id=target_user.id,
            hard_delete=hard_delete,
            performed_by=request.user
        )

        if result['status'] == 'deleted':
            messages.success(request, _('User %(username)s has been permanently deleted.') % {'username': result['username']})
        else:
            messages.success(request, _('User %(username)s has been anonymized.') % {'username': result['username']})

    except Exception as e:
        messages.error(request, _('Error deleting user: %(error)s') % {'error': str(e)})

    return HttpResponseRedirect(reverse('gdpr_management') + '?tab=users')


@login_required
@require_POST
def gdpr_delete_reviewee_view(request, reviewee_uuid):
    """Delete or anonymize a reviewee (GDPR)"""
    # Check permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to delete reviewees.'))
        return redirect('gdpr_management')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('admin_dashboard')

    try:
        # Get the reviewee to verify organization
        reviewee = get_object_or_404(Reviewee, uuid=reviewee_uuid, organization=org)

        # Get deletion type from POST
        deletion_type = request.POST.get('deletion_type', 'soft')

        if deletion_type == 'full_anonymization':
            # Full anonymization (reviewee + reviewer emails)
            result = GDPRDeletionService.delete_reviewee_and_anonymize_reviewer_emails(
                reviewee_id=reviewee.id,
                performed_by=request.user
            )
            messages.success(
                request,
                _('Reviewee %(name)s and all associated reviewer emails have been anonymized. '
                  '%(count)s reviewer email(s) anonymized.')
                % {'name': result['name'], 'count': result.get('reviewer_emails_anonymized', 0)}
            )
        else:
            # Soft or hard delete
            hard_delete = (deletion_type == 'hard')
            result = GDPRDeletionService.delete_reviewee(
                reviewee_id=reviewee.id,
                hard_delete=hard_delete,
                performed_by=request.user
            )

            if result['status'] == 'deleted':
                messages.success(
                    request,
                    _('Reviewee %(name)s has been permanently deleted along with '
                      '%(count)s review cycle(s) and all associated data.')
                    % {'name': result['name'], 'count': result['review_cycles_affected']}
                )
            else:
                messages.success(
                    request,
                    _('Reviewee %(name)s has been anonymized. '
                      '%(count)s review cycle(s) preserved.')
                    % {'name': result['name'], 'count': result['review_cycles_affected']}
                )

    except Exception as e:
        messages.error(request, _('Error deleting reviewee: %(error)s') % {'error': str(e)})

    return redirect('gdpr_management')


# ============================================================================
# PRODUCT REVIEW MANAGEMENT
# ============================================================================

@login_required
def product_review_list(request):
    """List and manage product reviews"""
    # Reviews of Blik from every customer: platform staff only.
    if not request.user.is_superuser:
        raise Http404
    org = request.organization

    # Get all product reviews (not org-scoped - these are reviews of Blik as a product)
    # Use .all() to explicitly avoid any organization filtering from the manager
    reviews_qs = ProductReview.objects.all().filter(is_active=True)

    # Filter by status if provided
    status_filter = request.GET.get('status', '')
    if status_filter:
        reviews_qs = reviews_qs.filter(status=status_filter)

    # Order by created date (newest first) to show pending reviews at top
    # Pending reviews don't have published_date, so ordering by created_at ensures they appear first
    reviews_qs = reviews_qs.order_by('-created_at')

    # Calculate aggregate stats
    stats = reviews_qs.aggregate(
        avg_rating=Avg('rating'),
        total_count=Count('id'),
        approved_count=Count('id', filter=Q(status='approved')),
        pending_count=Count('id', filter=Q(status='pending')),
    )

    # Get per_page from request, default to 25
    per_page = request.GET.get('per_page', '25')
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25

    # Paginate reviews
    paginator = Paginator(reviews_qs, per_page)
    page = request.GET.get('page')
    try:
        reviews = paginator.page(page)
    except PageNotAnInteger:
        reviews = paginator.page(1)
    except EmptyPage:
        reviews = paginator.page(paginator.num_pages)

    context = {
        'reviews': reviews,
        'stats': stats,
        'status_filter': status_filter,
        'per_page': per_page,
    }

    return render(request, 'admin_dashboard/product_review_list.html', context)


@login_required
def product_review_create(request):
    """Create a new product review"""
    if not request.user.is_superuser:
        messages.error(request, _('You do not have permission to create product reviews.'))
        return redirect('product_review_list')

    if request.method == 'POST':
        rating = request.POST.get('rating')
        review_title = request.POST.get('review_title')
        review_text = request.POST.get('review_text')
        reviewer_name = request.POST.get('reviewer_name')
        reviewer_title = request.POST.get('reviewer_title', '')
        reviewer_company = request.POST.get('reviewer_company', '')
        reviewer_email = request.POST.get('reviewer_email')
        verified_customer = request.POST.get('verified_customer') == 'on'
        featured = request.POST.get('featured') == 'on'
        status = request.POST.get('status', 'pending')
        source = request.POST.get('source', '')
        notes = request.POST.get('notes', '')

        # Validation
        if not all([rating, review_title, review_text, reviewer_name, reviewer_email]):
            messages.error(request, _('Please fill in all required fields.'))
            return render(request, 'admin_dashboard/product_review_form.html', {
                'action': 'Create',
                'review': request.POST,
            })

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError('Rating must be between 1 and 5')
        except (ValueError, TypeError):
            messages.error(request, _('Invalid rating value.'))
            return render(request, 'admin_dashboard/product_review_form.html', {
                'action': 'Create',
                'review': request.POST,
            })

        # Create the review
        review = ProductReview.objects.create(
            organization=request.organization,
            rating=rating,
            review_title=review_title,
            review_text=review_text,
            reviewer_name=reviewer_name,
            reviewer_title=reviewer_title,
            reviewer_company=reviewer_company,
            reviewer_email=reviewer_email,
            verified_customer=verified_customer,
            featured=featured,
            status=status,
            source=source,
            notes=notes,
            published_date=date.today() if status == 'approved' else None,
        )

        messages.success(request, _('Product review from "%(name)s" created successfully.') % {'name': reviewer_name})
        return redirect('product_review_detail', review_id=review.id)

    return render(request, 'admin_dashboard/product_review_form.html', {'action': 'Create'})


@login_required
def product_review_detail(request, review_id):
    """View product review details"""
    # Reviews of Blik from every customer: platform staff only.
    if not request.user.is_superuser:
        raise Http404
    review = get_object_or_404(
        ProductReview.objects,
        id=review_id
    )

    context = {
        'review': review,
    }

    return render(request, 'admin_dashboard/product_review_detail.html', context)


@login_required
def product_review_edit(request, review_id):
    """Edit an existing product review"""
    if not request.user.is_superuser:
        messages.error(request, _('You do not have permission to edit product reviews.'))
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    if request.method == 'POST':
        rating = request.POST.get('rating')
        review_title = request.POST.get('review_title')
        review_text = request.POST.get('review_text')
        reviewer_name = request.POST.get('reviewer_name')
        reviewer_title = request.POST.get('reviewer_title', '')
        reviewer_company = request.POST.get('reviewer_company', '')
        reviewer_email = request.POST.get('reviewer_email')
        verified_customer = request.POST.get('verified_customer') == 'on'
        featured = request.POST.get('featured') == 'on'
        status = request.POST.get('status', 'pending')
        source = request.POST.get('source', '')
        notes = request.POST.get('notes', '')

        # Validation
        if not all([rating, review_title, review_text, reviewer_name, reviewer_email]):
            messages.error(request, _('Please fill in all required fields.'))
            return render(request, 'admin_dashboard/product_review_form.html', {
                'action': 'Edit',
                'review': review,
            })

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError('Rating must be between 1 and 5')
        except (ValueError, TypeError):
            messages.error(request, _('Invalid rating value.'))
            return render(request, 'admin_dashboard/product_review_form.html', {
                'action': 'Edit',
                'review': review,
            })

        # Update the review
        old_status = review.status
        review.rating = rating
        review.review_title = review_title
        review.review_text = review_text
        review.reviewer_name = reviewer_name
        review.reviewer_title = reviewer_title
        review.reviewer_company = reviewer_company
        review.reviewer_email = reviewer_email
        review.verified_customer = verified_customer
        review.featured = featured
        review.status = status
        review.source = source
        review.notes = notes

        # Set published date when approved
        if status == 'approved' and old_status != 'approved':
            review.published_date = date.today()

        review.save()

        messages.success(request, _('Product review updated successfully.'))
        return redirect('product_review_detail', review_id=review.id)

    return render(request, 'admin_dashboard/product_review_form.html', {
        'action': 'Edit',
        'review': review,
    })


@login_required
def product_review_delete(request, review_id):
    """Delete (soft delete) a product review"""
    if not request.user.is_superuser:
        messages.error(request, _('You do not have permission to delete product reviews.'))
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    if request.method == 'POST':
        # Soft delete
        review.is_active = False
        review.save()

        messages.success(request, _('Product review from "%(name)s" has been deleted.') % {'name': review.reviewer_name})
        return redirect('product_review_list')

    return render(request, 'admin_dashboard/product_review_confirm_delete.html', {
        'review': review,
    })


@login_required
def quick_product_review(request):
    """
    Quick review submission for logged-in users.
    Pre-fills user information from their profile.
    """
    user = request.user
    org = request.organization

    # Check if user has already submitted a review (global, not org-scoped)
    existing_review = ProductReview.objects.filter(
        reviewer_email=user.email,
        is_active=True
    ).first()

    if request.method == 'POST':
        rating = request.POST.get('rating')
        review_title = request.POST.get('review_title', '').strip()
        review_text = request.POST.get('review_text', '').strip()

        # Validation - only rating is required
        if not rating:
            messages.error(request, _('Please select a rating.'))
            return render(request, 'admin_dashboard/quick_product_review.html', {
                'existing_review': existing_review,
            })

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError('Rating must be between 1 and 5')
        except (ValueError, TypeError):
            messages.error(request, _('Invalid rating value.'))
            return render(request, 'admin_dashboard/quick_product_review.html', {
                'existing_review': existing_review,
            })

        # Generate default title/text if not provided
        if not review_title:
            review_title = f"{rating}-star review"
        if not review_text:
            review_text = f"Rated {rating} out of 5 stars."

        # Get user profile info
        user_profile = user.userprofile if hasattr(user, 'userprofile') else None
        # The username is often an email; never store that as the public name.
        reviewer_name = anonymous_name(user.get_full_name() or user.username)
        reviewer_email = user.email

        # Create or update review
        if existing_review:
            # Update existing review
            existing_review.rating = rating
            existing_review.review_title = review_title
            existing_review.review_text = review_text
            existing_review.status = 'pending'  # Reset to pending for re-approval
            existing_review.save()
            messages.success(request, _('Your review has been updated and is pending approval. Thank you!'))
        else:
            # Create new review
            ProductReview.objects.create(
                organization=org,
                rating=rating,
                review_title=review_title,
                review_text=review_text,
                reviewer_name=reviewer_name,
                reviewer_email=reviewer_email,
                verified_customer=True,  # They're logged-in users, so verified
                status='pending',
                source='Dashboard Quick Review',
            )
            messages.success(request, _('Thank you for your review! It will be published after approval.'))

        return redirect('admin_dashboard')

    context = {
        'existing_review': existing_review,
        'user_name': user.get_full_name() or user.username,
        'user_email': user.email,
    }

    return render(request, 'admin_dashboard/quick_product_review.html', context)


@login_required
@require_POST
def product_review_approve(request, review_id):
    """Quick approve a product review"""
    if not request.user.is_superuser:
        messages.error(request, _('You do not have permission to approve reviews.'))
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    review.status = 'approved'
    if not review.published_date:
        review.published_date = date.today()
    review.save()

    messages.success(request, _('Review from "%(name)s" approved successfully.') % {'name': review.reviewer_name})
    return redirect('product_review_list')


@login_required
@require_POST
def product_review_reject(request, review_id):
    """Quick reject a product review"""
    if not request.user.is_superuser:
        messages.error(request, _('You do not have permission to reject reviews.'))
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    review.status = 'rejected'
    review.save()

    messages.success(request, _('Review from "%(name)s" rejected.') % {'name': review.reviewer_name})
    return redirect('product_review_list')


# =============================================================================
# API TOKEN & WEBHOOK MANAGEMENT
# =============================================================================

@login_required
@can_manage_organization_required
def create_api_token(request):
    """Create a new API token"""
    if request.method != 'POST':
        return redirect('settings')

    if not can_use_api(request.user):
        messages.error(request, _('Permission denied.'))
        return redirect('settings')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('settings')

    name = request.POST.get('name')
    rate_limit = request.POST.get('rate_limit', 1000)
    is_active = request.POST.get('is_active') == 'on'

    try:
        token = APIToken.objects.create(
            organization=org,
            created_by=request.user,
            name=name,
            rate_limit=int(rate_limit),
            is_active=is_active
        )

        # Redirect to settings with token in session (will be displayed in modal)
        request.session['new_api_token'] = token.raw_token
        request.session['new_api_token_name'] = name
    except Exception as e:
        messages.error(request, _('Error creating API token: %(error)s') % {'error': str(e)})

    return redirect('settings')


@login_required
@can_manage_organization_required
def update_api_token(request, token_id):
    """Update an existing API token"""
    if request.method != 'POST':
        return redirect('settings')

    if not can_use_api(request.user):
        messages.error(request, _('Permission denied.'))
        return redirect('settings')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('settings')

    try:
        token = APIToken.objects.for_organization(org).get(id=token_id)

        token.name = request.POST.get('name', token.name)
        token.rate_limit = int(request.POST.get('rate_limit', token.rate_limit))
        token.is_active = request.POST.get('is_active') == 'on'
        token.save()

        messages.success(request, _('API token updated successfully.'))
    except APIToken.DoesNotExist:
        messages.error(request, _('API token not found.'))
    except Exception as e:
        messages.error(request, _('Error updating API token: %(error)s') % {'error': str(e)})

    return redirect('settings')


@login_required
@can_manage_organization_required
def delete_api_token(request, token_id):
    """Delete (revoke) an API token"""
    if request.method != 'POST':
        return redirect('settings')

    if not can_use_api(request.user):
        messages.error(request, _('Permission denied.'))
        return redirect('settings')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('settings')

    try:
        token = APIToken.objects.for_organization(org).get(id=token_id)
        token_name = token.name
        token.delete()

        messages.success(request, _('API token "%(name)s" revoked successfully.') % {'name': token_name})
    except APIToken.DoesNotExist:
        messages.error(request, _('API token not found.'))
    except Exception as e:
        messages.error(request, _('Error revoking API token: %(error)s') % {'error': str(e)})

    return redirect('settings')


@login_required
@can_manage_organization_required
def create_webhook(request):
    """Create a new webhook endpoint"""
    if request.method != 'POST':
        return redirect('settings')

    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('Permission denied.'))
        return redirect('settings')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('settings')

    name = request.POST.get('name')
    url = request.POST.get('url')
    events = request.POST.getlist('events')  # Get multiple checkboxes
    is_active = request.POST.get('is_active') == 'on'

    try:
        webhook = WebhookEndpoint.objects.create(
            organization=org,
            created_by=request.user,
            name=name,
            url=url,
            events=events,
            is_active=is_active
        )

        messages.success(request, _('Webhook "%(name)s" created successfully.') % {'name': name})
    except Exception as e:
        messages.error(request, _('Error creating webhook: %(error)s') % {'error': str(e)})

    return redirect('settings')


@login_required
@can_manage_organization_required
def update_webhook(request, webhook_id):
    """Update an existing webhook endpoint"""
    if request.method != 'POST':
        return redirect('settings')

    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('Permission denied.'))
        return redirect('settings')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('settings')

    try:
        webhook = WebhookEndpoint.objects.for_organization(org).get(id=webhook_id)

        webhook.name = request.POST.get('name', webhook.name)
        webhook.url = request.POST.get('url', webhook.url)
        webhook.events = request.POST.getlist('events')
        webhook.is_active = request.POST.get('is_active') == 'on'
        webhook.save()

        messages.success(request, _('Webhook "%(name)s" updated successfully.') % {'name': webhook.name})
    except WebhookEndpoint.DoesNotExist:
        messages.error(request, _('Webhook not found.'))
    except Exception as e:
        messages.error(request, _('Error updating webhook: %(error)s') % {'error': str(e)})

    return redirect('settings')


@login_required
@can_manage_organization_required
def delete_webhook(request, webhook_id):
    """Delete a webhook endpoint"""
    if request.method != 'POST':
        return redirect('settings')

    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('Permission denied.'))
        return redirect('settings')

    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('settings')

    try:
        webhook = WebhookEndpoint.objects.for_organization(org).get(id=webhook_id)
        webhook_name = webhook.name
        webhook.delete()

        messages.success(request, _('Webhook "%(name)s" deleted successfully.') % {'name': webhook_name})
    except WebhookEndpoint.DoesNotExist:
        messages.error(request, _('Webhook not found.'))
    except Exception as e:
        messages.error(request, _('Error deleting webhook: %(error)s') % {'error': str(e)})

    return redirect('settings')


# ============================================================================
# Org chart views
# ============================================================================


def _build_org_tree(organization):
    """
    Load every unit and membership for the org, then derive a tree:
      - A unit's parent is the (lowest display_order) unit in which this
        unit's first manager is a MEMBER.
      - Units whose manager is on no other unit (or who have no manager yet)
        are roots.
      - A rare cycle (A-manages-B-manages-A) is broken by dropping the
        offending parent edge so the cycle-causer becomes a root.

    Returns a dict:
      {
        'roots': [OrgUnit, ...],
        'children_of': {unit.id: [OrgUnit, ...]},
        'mships_by_unit': {unit.id: [OrgUnitMembership sorted by (row, col)]},
        'sibling_names_by_reviewee': {reviewee_id: [unit_name, ...]},
      }
    """
    units = list(
        OrgUnit.objects.for_organization(organization).order_by('display_order', 'name')
    )
    if not units:
        return {
            'roots': [], 'children_of': {}, 'mships_by_unit': {},
            'sibling_names_by_reviewee': {},
        }

    unit_ids = [t.id for t in units]
    memberships = list(
        OrgUnitMembership.objects
        .filter(unit_id__in=unit_ids)
        .select_related('reviewee', 'unit')
        .order_by('row', 'col')
    )

    mships_by_unit = {t.id: [] for t in units}
    member_units_by_reviewee = {}  # reviewee_id -> [unit_id where they're MEMBER]
    unit_names_by_reviewee = {}    # reviewee_id -> [unit_name, ...] (all roles)
    for m in memberships:
        mships_by_unit[m.unit_id].append(m)
        unit_names_by_reviewee.setdefault(m.reviewee_id, []).append(m.unit.name)
        if m.role == OrgUnitMembership.MEMBER:
            member_units_by_reviewee.setdefault(m.reviewee_id, []).append(m.unit_id)

    unit_by_id = {t.id: t for t in units}

    # Parent inference
    parent_of = {}
    for t in units:
        managers = [m for m in mships_by_unit[t.id]
                    if m.role == OrgUnitMembership.MANAGER]
        if not managers:
            continue
        first_mgr_rid = managers[0].reviewee_id
        candidate_ids = [
            tid for tid in member_units_by_reviewee.get(first_mgr_rid, [])
            if tid != t.id
        ]
        if candidate_ids:
            candidates = [unit_by_id[cid] for cid in candidate_ids]
            candidates.sort(key=lambda x: (x.display_order, x.name))
            parent_of[t.id] = candidates[0].id

    # Break cycles: walk the parent chain from each node; if we revisit,
    # drop the offending edge.
    def _has_cycle(start):
        seen, curr = set(), start
        while curr is not None:
            if curr in seen:
                return True
            seen.add(curr)
            curr = parent_of.get(curr)
        return False
    for tid in list(parent_of.keys()):
        if _has_cycle(tid):
            del parent_of[tid]

    children_of = {t.id: [] for t in units}
    for tid, pid in parent_of.items():
        children_of[pid].append(unit_by_id[tid])
    for pid in children_of:
        children_of[pid].sort(key=lambda x: (x.display_order, x.name))

    roots = [t for t in units if t.id not in parent_of]

    # Sibling-unit labels for the ▣ badge tooltip (names of any other unit
    # the reviewee also belongs to, regardless of role).
    sibling_names_by_reviewee = {}
    for rid, names in unit_names_by_reviewee.items():
        if len(names) >= 2:
            sibling_names_by_reviewee[rid] = names

    return {
        'roots': roots,
        'children_of': children_of,
        'mships_by_unit': mships_by_unit,
        'sibling_names_by_reviewee': sibling_names_by_reviewee,
    }


def _org_nodes(tree):
    """The tree as nested dicts for the chart and outline templates."""
    other_units = tree['sibling_names_by_reviewee']

    def person(m):
        return {
            'membership': m,
            'reviewee': m.reviewee,
            'other_units': ', '.join(sorted(n for n in other_units.get(m.reviewee_id, []) if n != m.unit.name)),
        }

    def node(unit):
        memberships = tree['mships_by_unit'].get(unit.id, [])
        return {
            'unit': unit,
            'managers': [person(m) for m in memberships if m.role == OrgUnitMembership.MANAGER],
            'members': [person(m) for m in memberships if m.role == OrgUnitMembership.MEMBER],
            'children': [node(c) for c in tree['children_of'].get(unit.id, [])],
        }

    return [node(u) for u in tree['roots']]


def _org_chart_context(organization):
    tree = _build_org_tree(organization)
    return {
        'nodes': _org_nodes(tree),
        'unplaced': (
            Reviewee.objects.for_organization(organization)
            .filter(is_active=True, unit_memberships__isnull=True)
            .order_by('name')
        ),
    }


def import_preview_nodes(organization, stats):
    """
    The chart as it is after an import, for the preview. `stats` are the stats of
    the import. A unit has `is_new`, and `changed` when it is new or has a marked
    person. A person has `change`: 'new' or 'reactivated' for the person, 'moved'
    when they did not have this place in this unit before, or None.
    """
    marks = {row['email'].lower(): row['kind'] for row in stats['people'] if row['kind'] in ('new', 'reactivated')}
    new_units = set(stats['units_created'])

    def mark(node):
        people = node['managers'] + node['members']
        for person in people:
            membership = person['membership']
            moved = (membership.reviewee_id, membership.role, membership.unit_id) in stats['placed']
            person['change'] = marks.get(person['reviewee'].email.lower()) or ('moved' if moved else None)
        node['is_new'] = node['unit'].name in new_units
        node['changed'] = node['is_new'] or any(person['change'] for person in people)
        for child in node['children']:
            mark(child)

    nodes = _org_nodes(_build_org_tree(organization))
    for node in nodes:
        mark(node)
    return nodes


def _chart_change_response(organization):
    """
    Response after any mutation: both views and the unplaced pool, rendered
    again in full. Any membership change can move units in the hierarchy, so
    patching parts of the page would go stale.
    """
    context = _org_chart_context(organization)
    context['can_manage'] = True  # only people who may edit the chart get this response
    return JsonResponse({
        'chart_html': render_to_string('admin_dashboard/org_chart/_chart.html', context),
        'outline_html': render_to_string('admin_dashboard/org_chart/_outline.html', context),
        'unplaced_html': render_to_string('admin_dashboard/org_chart/_unplaced.html', context),
    })


def _manage_required(request):
    """Return a JSON 403 response if the user lacks manage permission."""
    if not request.user.has_perm('accounts.can_manage_organization'):
        return JsonResponse(
            {'error': 'You do not have permission to edit the org chart.'},
            status=403,
        )
    return None


@login_required
def org_chart(request):
    """Render the org chart editor page."""
    org = request.organization
    if not org:
        messages.error(request, _('No organization found.'))
        return redirect('admin_dashboard')

    context = _org_chart_context(org)
    context['can_manage'] = request.user.has_perm('accounts.can_manage_organization')
    if context['can_manage']:
        context['placeable'] = []
        for person, manager, unit_name, new_unit in unplaced_with_manager(org):
            also = chart_relation(manager, person)['also_managers']
            context['placeable'].append({
                'person': person, 'manager': manager, 'unit_name': unit_name, 'new_unit': new_unit,
                'also_managers': also, 'also_names': ', '.join(m.name for m in also)})
    if request.user.has_perm('accounts.can_invite_members'):
        managers = context['managers_without_account'] = managers_without_account(org)
        context['managers_to_invite'] = sum(not m.invited for m in managers)
        if context['managers_to_invite']:
            context['invite_language_name'] = language_name(default_language(org))
    return render(request, 'admin_dashboard/org_chart/index.html', context)


@login_required
@require_POST
def org_chart_place(request):
    """
    Place people whose reviewer list names one manager in that manager's unit.
    The server picks the manager from the list; the POST only names the person
    (`person=<uuid>`) or asks for all of them (`all=1`).
    """
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to edit the org chart.'))
        return redirect('org_chart')
    org = request.organization
    pairs = unplaced_with_manager(org)
    if not request.POST.get('all'):
        pairs = [pair for pair in pairs if str(pair[0].uuid) == request.POST.get('person')]
    placed = 0
    with transaction.atomic():
        for person, manager, _unit_name, _new_unit in pairs:
            try:
                with transaction.atomic():
                    apply_chart_choice(manager, person, 'place')
            except ValueError:
                continue
            placed += 1
    messages.success(request, ngettext('%(count)d person placed in the org chart.',
                                       '%(count)d people placed in the org chart.', placed) % {'count': placed})
    return redirect('org_chart')


@login_required
@require_POST
def org_chart_import(request):
    """Read an uploaded CSV file and continue to the column mapping."""
    from accounts.org_import import read_table

    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to edit the org chart.'))
        return redirect('org_chart')
    upload = request.FILES.get('file')
    if not upload:
        messages.error(request, _('Choose a CSV file.'))
        return redirect('org_chart')
    if upload.size > 1024 * 1024:  # ponytail: about 10,000 rows; raise if a customer needs more
        messages.error(request, _('The file is too large.'))
        return redirect('org_chart')
    try:
        headers, rows = read_table(upload.read())
    except (UnicodeDecodeError, ValueError):
        messages.error(request, _('The file is not a readable CSV file. Save it as CSV (UTF-8).'))
        return redirect('org_chart')
    if not rows:
        messages.error(request, _('The file has no rows.'))
        return redirect('org_chart')

    # The table waits in the session until the admin has mapped the columns.
    request.session['org_import'] = {'filename': upload.name, 'headers': headers, 'rows': rows}
    return redirect('org_chart_import_map')


@login_required
def org_chart_import_map(request):
    """Map the columns of the uploaded CSV file, then import it."""
    from accounts.org_import import FIELDS, count_new_people, guess_mapping, import_org_chart, map_rows
    from subscriptions.utils import employee_headroom

    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to edit the org chart.'))
        return redirect('org_chart')
    upload = request.session.get('org_import')
    if not upload:
        return redirect('org_chart')
    headers, rows = upload['headers'], upload['rows']

    errors = []
    over_limit = None
    changes = mapping_key = None
    if request.method == 'POST':
        mapping = {}
        for field, _label in FIELDS:
            try:
                mapping[field] = int(request.POST.get(field, ''))
            except ValueError:
                mapping[field] = None
        mapped, errors = map_rows(headers, rows, mapping)
        if not errors:
            # Say up front how far the file exceeds the plan, instead of
            # failing on the first person past the cap.
            headroom = employee_headroom(request.organization)
            new_people = count_new_people(request.organization, mapped)
            if headroom is not None and new_people > headroom:
                over_limit = {'new': new_people, 'allowed': headroom}
        # The people who are not in the file are deactivated, unless the admin clears
        # the checkbox in the preview. The first preview has no checkbox yet.
        deactivate = 'confirm' not in request.POST or bool(request.POST.get('deactivate_missing'))
        # The import runs only on a preview of this same mapping and this same choice:
        # 'confirm' holds what the admin saw the preview for.
        mapping_key = ','.join('' if mapping[field] is None else str(mapping[field]) for field, _label in FIELDS)
        confirmed = request.POST.get('confirm') == f'{mapping_key},{int(deactivate)}'
        if not errors and not over_limit:
            stats, errors = import_org_chart(
                request.organization, mapped, deactivate_missing=deactivate, dry_run=not confirmed,
                preview=lambda stats: import_preview_nodes(request.organization, stats))
            if not errors and confirmed:
                del request.session['org_import']
                messages.success(
                    request,
                    _('Imported %(units)s units: %(created)s new people, %(updated)s updated.')
                    % {**stats, 'created': len(stats['created'])},
                )
                if stats['deactivated']:
                    messages.info(request, ngettext(
                        '%(count)s person who is not in the file was deactivated.',
                        '%(count)s people who are not in the file were deactivated.',
                        stats['deactivated']) % {'count': stats['deactivated']})
                return redirect('org_chart')
            if not errors:
                changes = stats
                # Nobody is missing: the page has no checkbox, so it posts no choice.
                mapping_key += f',{int(bool(stats["deactivated"]))}'
                changes['active_without_missing'] = stats['active'] - len(stats['missing'])
                changes['nothing'] = not (stats['people'] or stats['units_created']
                                          or stats['units_removed'] or stats['missing'])
    else:
        mapping = guess_mapping(headers)

    return render(request, 'admin_dashboard/org_chart/import_map.html', {
        'filename': upload['filename'],
        'headers': headers,
        'preview': rows[:5],
        'row_count': len(rows),
        'fields': [(field, label, mapping.get(field)) for field, label in FIELDS],
        'errors': errors[:20],
        'more_errors': max(0, len(errors) - 20),
        'over_limit': over_limit,
        'changes': changes,
        'mapping_key': mapping_key,
        'plan': get_subscription_status(request.organization),
    })


@login_required
@require_POST
def org_chart_unit_create(request):
    """Create a new unit."""
    err = _manage_required(request)
    if err:
        return err

    org = request.organization
    name = (request.POST.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': _('Unit name is required.')}, status=400)

    if OrgUnit.objects.filter(organization=org, name=name).exists():
        return JsonResponse(
            {'error': f'A unit named "{name}" already exists.'},
            status=400,
        )

    # New units sort to the bottom by default.
    max_order = (
        OrgUnit.objects.filter(organization=org).aggregate(m=Max('display_order'))['m']
        or 0
    )
    OrgUnit.objects.create(
        organization=org,
        name=name,
        display_order=max_order + 1,
    )
    return _chart_change_response(org)


@login_required
@require_POST
def org_chart_unit_update(request, unit_uuid):
    """Rename a unit. (Shape has no config anymore.)"""
    err = _manage_required(request)
    if err:
        return err

    org = request.organization
    unit = get_object_or_404(
        OrgUnit.objects.for_organization(org),
        uuid=unit_uuid,
    )

    if 'name' in request.POST:
        name = (request.POST.get('name') or '').strip()
        if not name:
            return JsonResponse({'error': _('Unit name is required.')}, status=400)
        if (
            OrgUnit.objects.filter(organization=org, name=name)
            .exclude(pk=unit.pk).exists()
        ):
            return JsonResponse(
                {'error': f'A unit named "{name}" already exists.'},
                status=400,
            )
        unit.name = name
        unit.save()

    return _chart_change_response(org)


@login_required
@require_POST
def org_chart_unit_delete(request, unit_uuid):
    """Delete a unit and all its memberships."""
    err = _manage_required(request)
    if err:
        return err

    org = request.organization
    unit = get_object_or_404(
        OrgUnit.objects.for_organization(org),
        uuid=unit_uuid,
    )
    unit.delete()
    return _chart_change_response(org)


def _collect_descendants(unit_id, children_of):
    """Return the set of unit ids reachable as descendants of `unit_id`."""
    out = set()
    stack = [t.id for t in children_of.get(unit_id, [])]
    while stack:
        tid = stack.pop()
        if tid in out:
            continue
        out.add(tid)
        stack.extend(t.id for t in children_of.get(tid, []))
    return out


@login_required
@require_POST
def org_chart_unit_set_parent(request, unit_uuid):
    """
    Make this unit report to another unit.

    Mechanically: add the child unit's first manager as a member of the
    parent unit. The tree inference then picks `parent` as the child's
    parent (since the child's first-manager is now a MEMBER of parent).

    Required POST: parent_unit_uuid (UUID of the target parent unit)

    Refuses when:
      - child has no managers yet (user should add one first)
      - parent == child (would be self-referencing)
      - parent is a descendant of child in the current tree (would cycle)
      - child's first manager is already a MANAGER of parent (would make
        them both a manager and a member of the same unit — the data
        model forbids duplicate memberships per unit)
    """
    err = _manage_required(request)
    if err:
        return err

    org = request.organization
    child = get_object_or_404(
        OrgUnit.objects.for_organization(org),
        uuid=unit_uuid,
    )
    parent_uuid = request.POST.get('parent_unit_uuid')
    if not parent_uuid:
        return JsonResponse(
            {'error': 'parent_unit_uuid is required.'},
            status=400,
        )
    parent = get_object_or_404(
        OrgUnit.objects.for_organization(org),
        uuid=parent_uuid,
    )

    if parent.pk == child.pk:
        return JsonResponse(
            {'error': "A unit can't report to itself."},
            status=400,
        )

    first_mgr = (
        child.memberships.filter(role=OrgUnitMembership.MANAGER)
        .order_by('col').first()
    )
    if not first_mgr:
        return JsonResponse({
            'error': (
                f'Add a manager to "{child.name}" first — we use that '
                f'person as the bridge to the parent unit.'
            ),
        }, status=400)

    tree = _build_org_tree(org)
    descendants = _collect_descendants(child.id, tree['children_of'])
    if parent.id in descendants:
        return JsonResponse({
            'error': (
                f'"{parent.name}" currently reports to "{child.name}" '
                f'(directly or indirectly). That would create a loop.'
            ),
        }, status=400)

    # If the first manager is already on the parent unit, either it's
    # already a member (no-op — tree will show it) or a manager (conflict).
    existing = parent.memberships.filter(reviewee=first_mgr.reviewee).first()
    if existing and existing.role == OrgUnitMembership.MANAGER:
        return JsonResponse({
            'error': (
                f'{first_mgr.reviewee.name} manages "{parent.name}" — '
                f'they can\'t also report to it. Pick a different parent, '
                f'or change "{child.name}"\'s manager.'
            ),
        }, status=400)

    if existing is None:
        next_col = (
            parent.memberships.filter(row=1).aggregate(m=Max('col'))['m']
        )
        col = 0 if next_col is None else next_col + 1
        OrgUnitMembership.objects.create(
            unit=parent,
            reviewee=first_mgr.reviewee,
            row=1,
            col=col,
        )

    return _chart_change_response(org)


@login_required
@require_POST
def org_chart_membership_create(request):
    """
    Add or move a membership into a unit.

    Required POST params:
        unit_uuid, reviewee_uuid, role   (role = "manager" | "member")
    Optional:
        mode = "copy" (default) | "move"
        source_unit_uuid (required if mode=move)

    Row/col are computed by the server: row = 0 for manager, 1 for member;
    col = next unused position in that row. Clients don't need to track
    slot coordinates.
    """
    err = _manage_required(request)
    if err:
        return err

    org = request.organization

    unit = get_object_or_404(
        OrgUnit.objects.for_organization(org),
        uuid=request.POST.get('unit_uuid'),
    )
    reviewee = get_object_or_404(
        Reviewee.objects.for_organization(org),
        uuid=request.POST.get('reviewee_uuid'),
    )

    role = request.POST.get('role', OrgUnitMembership.MEMBER)
    if role not in (OrgUnitMembership.MANAGER, OrgUnitMembership.MEMBER):
        return JsonResponse(
            {'error': 'role must be "manager" or "member".'},
            status=400,
        )

    mode = request.POST.get('mode', 'copy')

    with transaction.atomic():
        # Move first, so moving within one unit changes the role (member to
        # manager) instead of tripping over the existing membership.
        if mode == 'move':
            src_unit_uuid = request.POST.get('source_unit_uuid')
            src_unit = get_object_or_404(
                OrgUnit.objects.for_organization(org),
                uuid=src_unit_uuid,
            )
            src_unit.memberships.filter(reviewee=reviewee).delete()

        if unit.memberships.filter(reviewee=reviewee).exists():
            transaction.set_rollback(True)
            return JsonResponse(
                {'error': _('%(name)s is already in this unit.') % {'name': reviewee.name}},
                status=400,
            )

        append_membership(unit, reviewee, role)

    return _chart_change_response(org)


@login_required
@require_POST
def org_chart_membership_delete(request, membership_id):
    """Remove a reviewee from a unit."""
    err = _manage_required(request)
    if err:
        return err

    org = request.organization
    membership = get_object_or_404(
        OrgUnitMembership.objects.select_related('unit'),
        pk=membership_id,
        unit__organization=org,
    )
    membership.delete()
    return _chart_change_response(org)


# ============================================================================
# Cycle-create chart integration
# ============================================================================


@login_required
def derive_reviewers_for_cycle(request):
    """
    AJAX endpoint that returns the reviewer list of a reviewee UUID: the saved
    list, else the org chart, else the previous review; `source=chart` or
    `source=previous` forces one of the last two.

    Response:
        {
            'self':           [{'uuid', 'name', 'email'}, ...],
            'manager':        [...],
            'peer':           [...],
            'direct_report':  [...],
            'emails':         {'manager': [email, ...], 'peer': [...], 'direct_report': [...]},
            'source':         'saved' | 'chart' | 'previous' | 'empty',
            'flags':          {'include_self': bool, ...},
            'questionnaire':  id or null,
        }
    """
    org = request.organization
    if not org:
        return JsonResponse({'error': 'No organization context.'}, status=400)

    reviewee_uuid = request.GET.get('reviewee')
    if not reviewee_uuid:
        return JsonResponse({'error': 'reviewee query param is required.'}, status=400)

    try:
        reviewee = Reviewee.objects.for_organization(org).get(uuid=reviewee_uuid)
    except Reviewee.DoesNotExist:
        return JsonResponse({'error': 'Reviewee not found.'}, status=404)

    shown = {c: [] for c in ('manager', 'peer', 'direct_report')}
    emails = {c: [] for c in shown}
    flags = {f'include_{c}': True for c in CATEGORY_ORDER}
    source, questionnaire = 'chart', None
    # The saved list and the previous review hold more than the chart (emails
    # someone typed): only a user who may start a cycle for the person gets them.
    if creatable_reviewees(request.user, org).filter(pk=reviewee.pk).exists():
        setup = review_setup(reviewee, source=request.GET.get('source'))
        shown, emails, flags, source = setup.people, setup.emails, setup.flags, setup.source
        questionnaire = setup.questionnaire.id if setup.questionnaire else None
    else:
        shown = {c: people for c, people in derive_reviewers(reviewee).items() if c != 'self'}

    return JsonResponse({
        'self': [{'uuid': str(reviewee.uuid), 'name': reviewee.name, 'email': reviewee.email}],
        **{
            cat: [{'uuid': str(r.uuid), 'name': r.name, 'email': r.email} for r in people]
            for cat, people in shown.items()
        },
        'emails': emails,
        'source': source,
        'flags': flags,
        'questionnaire': questionnaire,
    })
