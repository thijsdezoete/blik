"""
Admin dashboard views for Blik
"""
import json
import logging
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
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from accounts.models import Reviewee, UserProfile, OrganizationInvitation, OrgUnit, OrgUnitMembership
from accounts.permissions import (
    assign_organization_admin,
    assign_organization_member,
    can_manage_organization_required,
    can_manage_questionnaires_required,
    can_view_all_reports,
    is_organization_admin,
    login_required,
    reviewee_emails_below,
    set_user_permission,
    visible_cycles,
)
from api.models import APIToken, WebhookEndpoint
from core.env_config import env_managed_fields
from core.languages import default_language, is_language, language_name
from core.gdpr import GDPRDeletionService
from core.models import Organization
from productreviews.models import ProductReview, anonymous_name
from questionnaires.action_items import add_action_item_keys
from questionnaires.answer_options import DEFAULT_LIKERT_SCALE, DEFAULT_RATING_LABELS, save_options
from questionnaires.models import Question, QuestionSection, Questionnaire
from questionnaires.ordering import save_layout
from questionnaires.presentation import questionnaire_report_features
from questionnaires.translations import (
    LanguageState,
    get_language_states,
    get_text_translations,
    has_translation,
    save_text_translations,
)
from notifications.lifecycle import cycle_summary, send_cycle_summary
from reports.dreyfus_service import (
    agency_profile_with_texts,
    calculate_dreyfus_quadrant,
    quadrant_with_texts,
    skill_profile_with_texts,
    _level_to_stage,
)
from reports.models import Report
from reports.services import generate_report, self_vs_others_gap, send_report_ready_notification
from reviews.models import CATEGORY_ORDER, ReviewCycle, ReviewerToken
from reviews.services import (
    assign_tokens_to_emails,
    derive_reviewers,
    send_invitation_links_email,
    send_reminder_emails,
    send_reviewee_notifications,
    send_reviewer_invitations,
)
from subscriptions.models import Subscription
from subscriptions.utils import (
    NoCycleCredits,
    billing_context,
    check_employee_limit,
    cycle_credits,
    get_subscription_status,
)

logger = logging.getLogger(__name__)


def get_default_labels(questionnaire):
    """The default likert scale and rating labels of a new question, in the questionnaire's source language."""

    with translation.override(questionnaire.source_language):
        likert_scale = [f'{label}' for label in DEFAULT_LIKERT_SCALE]
        rating_labels = {key: f'{label}' for key, label in DEFAULT_RATING_LABELS.items()}

    return likert_scale, rating_labels


def get_cycle_or_404(request, cycle_uuid):
    """
    Get a ReviewCycle by UUID, filtered by organization and by what the current
    user is allowed to see. Returns 404 for cycles in another organization or
    belonging to another reviewee.
    """
    cycles_qs = ReviewCycle.objects.select_related('reviewee', 'questionnaire', 'created_by')
    if request.organization:
        cycles_qs = cycles_qs.filter(reviewee__organization=request.organization)
    return get_object_or_404(visible_cycles(request.user, cycles_qs), uuid=cycle_uuid)


@login_required
def legacy_id_redirect(request, pk, model, url_name):
    """Send an old integer-id URL (bookmark) to its UUID URL, own organization only."""
    obj = get_object_or_404(model, pk=pk, organization=request.organization)
    return redirect(url_name, obj.uuid, permanent=True)


def collect_reviewer_emails(request, organization, categories):
    """
    Merge reviewer selections from the picker and the email textareas into
    {category: [email, ...]}, deduplicated by normalized email.

    Picker hidden inputs are named `<category>_reviewees` and carry Reviewee
    UUIDs. Textareas are named `<category>_emails` and carry comma/newline
    separated emails. Categories not in `categories` come back empty.

    Per the anonymity invariant, only emails are returned: the Reviewee
    identity is dropped here and never stored on the token.

    Returns (email_assignments, warnings).
    """
    email_assignments = {code: [] for code, _label in ReviewerToken.CATEGORY_CHOICES}
    warnings = []
    labels = dict(ReviewerToken.CATEGORY_CHOICES)

    # One query for the chips of all categories.
    all_uuids = set()
    for code in categories:
        all_uuids.update(request.POST.getlist(f'{code}_reviewees'))
    uuid_to_email = {}
    if all_uuids and organization:
        valid = []
        for u in all_uuids:
            try:
                valid.append(UUID(str(u)))
            except ValueError:
                continue
        uuid_to_email = {
            str(r.uuid): r.email
            for r in Reviewee.objects.for_organization(organization).filter(uuid__in=valid)
        }

    for code in categories:
        seen = set()
        collected = []

        # Unknown UUIDs (stale page, deleted reviewee, other org) are skipped.
        for u in request.POST.getlist(f'{code}_reviewees'):
            email = (uuid_to_email.get(str(u)) or '').strip().lower()
            if email and email not in seen:
                seen.add(email)
                collected.append(email)

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
                collected.append(normalized)

        email_assignments[code] = collected

    return email_assignments, warnings


@login_required
def dashboard(request):
    """Admin dashboard homepage"""
    org = request.organization

    # Get statistics filtered by organization
    reviewees_qs = Reviewee.objects.for_organization(org).filter(is_active=True)
    cycles_qs = visible_cycles(
        request.user,
        ReviewCycle.objects.for_organization(org).select_related('reviewee', 'questionnaire')
    )

    total_reviewees = reviewees_qs.count()
    active_cycles = cycles_qs.filter(status='active').count()
    completed_cycles = cycles_qs.filter(status='completed').count()

    # Get subscription status
    subscription_status = get_subscription_status(org) if org else None

    # Recent activity
    recent_cycles = cycles_qs.all()[:5]

    # Pending reviews (tokens not completed)
    pending_tokens = ReviewerToken.objects.filter(
        cycle__in=cycles_qs,
        completed_at__isnull=True,
        cycle__status='active'
    ).count()

    # Completion stats for active cycles
    active_cycles_data = []
    for cycle in cycles_qs.filter(status='active').select_related('reviewee'):
        total_tokens = cycle.tokens.count()
        completed_tokens = cycle.tokens.filter(completed_at__isnull=False).count()
        completion_rate = (completed_tokens / total_tokens * 100) if total_tokens > 0 else 0

        active_cycles_data.append({
            'cycle': cycle,
            'total_tokens': total_tokens,
            'completed_tokens': completed_tokens,
            'completion_rate': completion_rate,
        })

    # Completed cycles with report availability
    completed_cycles_data = []
    for cycle in cycles_qs.filter(status='completed').select_related('reviewee').order_by('-created_at')[:10]:
        # Check if report exists
        report_exists = Report.objects.filter(cycle=cycle).exists()

        completed_cycles_data.append({
            'cycle': cycle,
            'report_exists': report_exists,
        })

    # Check if user has seen welcome modal
    has_seen_welcome = False
    try:
        has_seen_welcome = request.user.profile.has_seen_welcome
    except UserProfile.DoesNotExist:
        pass

    # Check if user has submitted a product review (global, not org-scoped)
    user_has_reviewed = ProductReview.objects.filter(
        reviewer_email=request.user.email,
        is_active=True
    ).exists()

    context = {
        'total_reviewees': total_reviewees,
        'active_cycles': active_cycles,
        'completed_cycles': completed_cycles,
        'pending_tokens': pending_tokens,
        'recent_cycles': recent_cycles,
        'active_cycles_data': active_cycles_data,
        'completed_cycles_data': completed_cycles_data,
        'subscription_status': subscription_status,
        'has_seen_welcome': has_seen_welcome,
        'user_has_reviewed': user_has_reviewed,
    }

    return render(request, 'admin_dashboard/dashboard.html', context)


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

        # Prevent self-demotion or demoting superusers
        if target_user.id == request.user.id:
            messages.error(request, _('You cannot modify your own permissions.'))
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


@login_required
def reviewee_create(request):
    """Create a new reviewee"""
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        department = request.POST.get('department', '')
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
                reviewee = Reviewee.objects.create(
                    organization=organization,
                    name=name,
                    email=email,
                    department=department,
                    language=language if is_language(language) else '',
                )
                messages.success(request, _('Reviewee "%(name)s" created successfully.') % {'name': reviewee.name})
                return redirect('reviewee_list')
            except Exception as e:
                messages.error(request, _('Error creating reviewee: %(error)s') % {'error': str(e)})
        else:
            messages.error(request, _('Name and email are required.'))

    return render(request, 'admin_dashboard/reviewee_form.html', {
        'action': 'Create',
        'default_language_name': language_name(default_language(request.organization)),
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

    # Create the cycle
    try:
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=request.user,
            status='active',
            **category_flags
        )
    except NoCycleCredits as e:
        messages.error(request, str(e))
        return redirect('reviewee_list')

    transaction.on_commit(lambda c=cycle: send_reviewee_notifications(c, request))

    total_tokens = 0
    email_invited_count = 0

    if previous_cycle:
        # Copy tokens from previous cycle, including email assignments. The self-assessment
        # token comes from send_reviewee_notifications above.
        previous_tokens = previous_cycle.tokens.filter(category__in=cycle.active_categories).exclude(category='self')

        for prev_token in previous_tokens:
            new_token = ReviewerToken.objects.create(
                cycle=cycle,
                category=prev_token.category,
                reviewer_email=prev_token.reviewer_email
            )
            total_tokens += 1
            if prev_token.reviewer_email:
                email_invited_count += 1

        # Send invitations to all email-assigned tokens
        if email_invited_count > 0:
            send_stats = send_reviewer_invitations(cycle)

            messages.success(
                request,
                _('Review cycle created for "%(name)s" using "%(questionnaire)s". '
                  'Copied %(count)s reviewer(s) from previous cycle. '
                  '%(sent)s email invitation(s) sent.')
                % {'name': reviewee.name, 'questionnaire': questionnaire.name,
                   'count': total_tokens, 'sent': send_stats['sent']}
            )
        else:
            messages.success(
                request,
                _('Review cycle created for "%(name)s" using "%(questionnaire)s" with %(count)s reviewer token(s). '
                  'Go to the cycle details to assign reviewers and send invitations.')
                % {'name': reviewee.name, 'questionnaire': questionnaire.name, 'count': total_tokens}
            )
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

        messages.success(
            request,
            _('Review cycle created for "%(name)s" using "%(questionnaire)s" with %(count)s reviewer token(s). '
              'Go to the cycle details to assign reviewers and send invitations.')
            % {'name': reviewee.name, 'questionnaire': questionnaire.name, 'count': total_tokens}
        )

    messages.info(request, _('Notification emails are being sent to the reviewee.'))

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


@login_required
def questionnaire_preview(request, questionnaire_uuid):
    """Preview a questionnaire in its source language, or in the language that ?lang= picks."""
    questionnaire = get_object_or_404(
        Questionnaire, uuid=questionnaire_uuid, organization=request.organization)
    language = request.GET.get('lang')

    if not is_language(language):
        language = questionnaire.source_language

    questionnaire = questionnaire.translated(language)

    context = {
        'questionnaire': questionnaire,
        'sections': questionnaire.sections.all(),
        'preview_language': language,
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
            return render(request, 'admin_dashboard/questionnaire_form.html', {
                'action': 'Create',
                'source_language': source_language,
            })

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
        'action': 'Create',
        # New questionnaires are most likely written in the language their author works in
        'source_language': translation.get_language(),
    }

    return render(request, 'admin_dashboard/questionnaire_form.html', context)


def posted_labels(post, question_type):
    """The rating or scale labels the question editor posted, without the empty ones."""

    if question_type == 'rating':
        fields = {key: f'rating_label_{key}' for key in DEFAULT_RATING_LABELS}
    elif question_type == 'scale':
        fields = {'min': 'scale_min_label', 'max': 'scale_max_label'}
    else:
        return {}

    labels = {key: post.get(field, '').strip() for key, field in fields.items()}

    return {key: label for key, label in labels.items() if label}


def posted_descriptions(post, question_type):
    """The descriptions of the rating values the question editor posted, without the empty ones."""

    if question_type != 'rating' or post.get('rating_descriptions') != 'on':
        return {}

    descriptions = {key: post.get(f'rating_description_{key}', '').strip() for key in DEFAULT_RATING_LABELS}

    return {key: text for key, text in descriptions.items() if text}


def posted_option_rows(post, prefix, with_weights=False):
    """The answer options the question editor posted, as [(id or None, label, weight), ...].

    Each row posts the id of its option (empty for a new one), its label and, for choice questions, its weight. Rows
    without a label are dropped. Raises ValueError for a weight that is not a number.
    """

    ids = post.getlist(f'{prefix}_option_id')
    labels = post.getlist(f'{prefix}_option_label')
    weights = post.getlist(f'{prefix}_option_weight') if with_weights else [''] * len(labels)
    rows = []

    for posted_id, label, weight in zip(ids, labels, weights):
        if label := label.strip():
            option_id = int(posted_id) if posted_id.isdigit() else None
            rows.append((option_id, label, float(weight) if with_weights else None))

    return rows


@login_required
@can_manage_questionnaires_required
def questionnaire_edit(request, questionnaire_uuid):
    """Edit an existing questionnaire"""
    # Get organization from request context
    org = getattr(request, 'organization', None)

    # Filter by organization to prevent cross-org access
    questionnaire = get_object_or_404(
        Questionnaire,
        uuid=questionnaire_uuid,
        organization=org
    )

    default_likert_scale, default_rating_labels = get_default_labels(questionnaire)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_info':
            source_language = request.POST.get('source_language')

            if not is_language(source_language):
                source_language = questionnaire.source_language

            # The source language cannot also have a translation
            if source_language != questionnaire.source_language and has_translation(questionnaire, source_language):
                messages.error(
                    request,
                    _('This questionnaire is already translated into %(language)s. Empty that translation first to '
                      'make %(language)s its source language.') % {'language': language_name(source_language)},
                )
                return redirect('questionnaire_edit', questionnaire_uuid=questionnaire.uuid)

            questionnaire.name = request.POST.get('name', questionnaire.name)
            questionnaire.description = request.POST.get('description', '')
            questionnaire.is_default = request.POST.get('is_default') == 'on'
            questionnaire.source_language = source_language

            try:
                questionnaire.save()
                messages.success(request, _('Questionnaire "%(name)s" updated successfully.') % {'name': questionnaire.name})
            except Exception as e:
                messages.error(request, _('Error updating questionnaire: %(error)s') % {'error': str(e)})

        elif action == 'reorder':
            try:
                save_layout(questionnaire, json.loads(request.POST.get('layout', '')))
            except (ValueError, TypeError, KeyError):
                return JsonResponse({
                    'success': False,
                    'message': _('The new order could not be saved. Reload the page and try again.'),
                }, status=400)

            return JsonResponse({'success': True})

        elif action == 'add_section':
            section_title = request.POST.get('section_title')
            section_description = request.POST.get('section_description', '')

            if section_title:
                max_order = questionnaire.sections.aggregate(Max('order'))['order__max']
                next_order = (max_order + 1) if max_order is not None else 0
                try:
                    QuestionSection.objects.create(
                        questionnaire=questionnaire,
                        title=section_title,
                        description=section_description,
                        order=next_order
                    )
                    messages.success(request, _('Section "%(title)s" added.') % {'title': section_title})
                except Exception as e:
                    messages.error(request, _('Error adding section: %(error)s') % {'error': str(e)})

        elif action == 'edit_section':
            section_id = request.POST.get('section_id')
            section_title = request.POST.get('section_title')
            section_description = request.POST.get('section_description', '')

            if section_id and section_title:
                try:
                    section = QuestionSection.objects.get(id=section_id, questionnaire=questionnaire)
                    section.title = section_title
                    section.description = section_description
                    section.save()
                    messages.success(request, _('Section "%(title)s" updated successfully.') % {'title': section_title})
                except QuestionSection.DoesNotExist:
                    messages.error(request, _('Section not found.'))
                except Exception as e:
                    messages.error(request, _('Error updating section: %(error)s') % {'error': str(e)})

        elif action == 'add_question':
            section_id = request.POST.get('section_id')
            question_text = request.POST.get('question_text')
            question_type = request.POST.get('question_type', 'rating')
            required = request.POST.get('required') == 'on'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            if section_id and question_text:
                try:
                    section = QuestionSection.objects.get(id=section_id, questionnaire=questionnaire)
                    max_order = section.questions.aggregate(Max('order'))['order__max']
                    next_order = (max_order + 1) if max_order is not None else 0

                    # Build config based on question type
                    config = {}
                    option_rows = []
                    labels = posted_labels(request.POST, question_type)
                    if question_type == 'rating':
                        config = {'min': 1, 'max': 5}
                        labels = labels or default_rating_labels
                    elif question_type == 'likert':
                        option_rows = posted_option_rows(request.POST, 'likert')

                        if not option_rows:
                            option_rows = [(None, label, None) for label in default_likert_scale]
                    elif question_type == 'single_choice' or question_type == 'multiple_choice':
                        # Weights only count with scoring enabled
                        enable_scoring = request.POST.get('enable_scoring') == 'on'

                        try:
                            option_rows = posted_option_rows(request.POST, 'choice', with_weights=enable_scoring)
                        except ValueError:
                            option_rows = posted_option_rows(request.POST, 'choice')
                            messages.warning(request, _('Invalid weight values. Scoring disabled for this question.'))
                        else:
                            config = {'scoring_enabled': True} if enable_scoring else {}
                    elif question_type == 'scale':
                        try:
                            min_val = int(request.POST.get('scale_min', 1))
                            max_val = int(request.POST.get('scale_max', 100))
                            step_val = int(request.POST.get('scale_step', 1))

                            config = {
                                'min': min_val,
                                'max': max_val,
                                'step': step_val
                            }
                        except (ValueError, TypeError):
                            # Use defaults if parsing fails
                            config = {'min': 1, 'max': 100, 'step': 1}
                            messages.warning(request, _('Invalid scale values. Using defaults (1-100, step 1).'))

                    # Add Dreyfus/Agency configuration if provided
                    skill_weight = request.POST.get('add_skill_weight', 0)
                    agency_weight = request.POST.get('add_agency_weight', 0)

                    if skill_weight or agency_weight:
                        config['dreyfus_mapping'] = {
                            'skill': float(skill_weight),
                            'agency': float(agency_weight)
                        }

                    # Parse action items for new question
                    action_items = []
                    action_item_indices = set()

                    # Extract all action item indices from POST data
                    for key in request.POST.keys():
                        if key.startswith('add_action_items[') and '][text]' in key:
                            idx_str = key.split('[')[1].split(']')[0]
                            action_item_indices.add(idx_str)

                    # Build action items list
                    for idx in sorted(action_item_indices, key=int):
                        text = request.POST.get(f'add_action_items[{idx}][text]', '').strip()
                        threshold = request.POST.get(f'add_action_items[{idx}][threshold]', 3.0)
                        stages_raw = request.POST.getlist(f'add_action_items[{idx}][stages][]')

                        if text:
                            item = {
                                'text': text,
                                'threshold': float(threshold)
                            }
                            if stages_raw:
                                item['stages'] = [int(s) for s in stages_raw]
                            action_items.append(item)

                    question = Question.objects.create(
                        section=section,
                        question_text=question_text,
                        question_type=question_type,
                        config=config,
                        labels=labels,
                        descriptions=posted_descriptions(request.POST, question_type),
                        required=required,
                        order=next_order,
                        action_items=add_action_item_keys(action_items)
                    )
                    save_options(question, option_rows)

                    if is_ajax:
                        question_html = render_to_string(
                            'admin_dashboard/partials/question_card.html',
                            {'question': question},
                            request=request,
                        )
                        return JsonResponse({
                            'success': True,
                            'message': _('Question added successfully.'),
                            'section_id': section.id,
                            'question_id': question.id,
                            'question_html': question_html,
                        })

                    messages.success(request, _('Question added successfully.'))
                except Exception as e:
                    logger.exception('Error adding question')
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'message': _('Error adding question. Please try again.'),
                        }, status=400)
                    messages.error(request, _('Error adding question. Please try again.'))

        elif action == 'delete_section':
            section_id = request.POST.get('section_id')
            try:
                section = QuestionSection.objects.get(id=section_id, questionnaire=questionnaire)
                section_title = section.title
                section.delete()
                messages.success(request, _('Section "%(title)s" deleted.') % {'title': section_title})
            except Exception as e:
                messages.error(request, _('Error deleting section: %(error)s') % {'error': str(e)})

        elif action == 'delete_question':
            question_id = request.POST.get('question_id')
            try:
                question = Question.objects.get(id=question_id, section__questionnaire=questionnaire)
                question.delete()
                messages.success(request, _('Question deleted.'))
            except Exception as e:
                messages.error(request, _('Error deleting question: %(error)s') % {'error': str(e)})

        elif action == 'edit_question':
            question_id = request.POST.get('question_id')
            question_text = request.POST.get('question_text')
            question_type = request.POST.get('question_type', 'rating')
            required = request.POST.get('required') == 'on'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            if question_id and question_text:
                try:
                    question = Question.objects.get(id=question_id, section__questionnaire=questionnaire)
                    previous_config = question.config

                    # Update basic fields
                    question.question_text = question_text
                    question.question_type = question_type
                    question.required = required

                    # Build config based on question type
                    config = {}
                    option_rows = []
                    labels = posted_labels(request.POST, question_type)
                    if question_type == 'rating':
                        config = {'min': 1, 'max': 5}
                        labels = labels or default_rating_labels
                    elif question_type == 'likert':
                        option_rows = posted_option_rows(request.POST, 'likert')

                        if not option_rows:
                            option_rows = [(None, label, None) for label in default_likert_scale]
                    elif question_type == 'single_choice' or question_type == 'multiple_choice':
                        # Weights only count with scoring enabled
                        enable_scoring = request.POST.get('enable_scoring') == 'on'

                        try:
                            option_rows = posted_option_rows(request.POST, 'choice', with_weights=enable_scoring)
                        except ValueError:
                            option_rows = posted_option_rows(request.POST, 'choice')
                            messages.warning(request, _('Invalid weight values. Scoring disabled for this question.'))
                        else:
                            config = {'scoring_enabled': True} if enable_scoring else {}
                    elif question_type == 'scale':
                        try:
                            min_val = int(request.POST.get('scale_min', 1))
                            max_val = int(request.POST.get('scale_max', 100))
                            step_val = int(request.POST.get('scale_step', 1))

                            config = {
                                'min': min_val,
                                'max': max_val,
                                'step': step_val
                            }
                        except (ValueError, TypeError):
                            # Use defaults if parsing fails
                            config = {'min': 1, 'max': 100, 'step': 1}
                            messages.warning(request, _('Invalid scale values. Using defaults (1-100, step 1).'))

                    # The dialog doesn't show the Dreyfus weights, so keep them
                    if 'dreyfus_mapping' in previous_config:
                        config['dreyfus_mapping'] = previous_config['dreyfus_mapping']

                    question.config = config
                    question.labels = labels
                    question.descriptions = posted_descriptions(request.POST, question_type)
                    question.save()
                    save_options(question, option_rows)

                    if is_ajax:
                        return JsonResponse({
                            'success': True,
                            'message': _('Question updated successfully.'),
                            'question': {
                                'id': question.id,
                                'question_text': question.question_text,
                                'question_type': question.question_type,
                                'question_type_display': question.get_question_type_display(),
                                'required': question.required,
                                'config': question.config,
                                'options': question.options_data,
                                'labels': question.labels,
                                'descriptions': question.descriptions,
                            },
                        })

                    messages.success(request, _('Question updated successfully.'))
                except Exception as e:
                    logger.exception('Error updating question')
                    if is_ajax:
                        return JsonResponse({
                            'success': False,
                            'message': _('Error updating question. Please try again.'),
                        }, status=400)
                    messages.error(request, _('Error updating question. Please try again.'))

        elif action == 'update_dreyfus_config':
            question_id = request.POST.get('question_id')
            skill_weight = request.POST.get('skill_weight', 0)
            agency_weight = request.POST.get('agency_weight', 0)

            if question_id:
                try:
                    question = Question.objects.get(id=question_id, section__questionnaire=questionnaire)

                    # Update dreyfus_mapping in config
                    if 'dreyfus_mapping' not in question.config:
                        question.config['dreyfus_mapping'] = {}

                    question.config['dreyfus_mapping']['skill'] = float(skill_weight)
                    question.config['dreyfus_mapping']['agency'] = float(agency_weight)

                    # Parse action items from form
                    action_items = []
                    action_item_indices = set()
                    # A posted key may only name an item the question has, so the client cannot set keys of its own
                    known_keys = {item.get('key') for item in question.action_items if isinstance(item, dict)}

                    # Extract all action item indices from the POST data
                    for key in request.POST.keys():
                        if key.startswith('action_items[') and '][text]' in key:
                            # Extract index from key like "action_items[0][text]"
                            idx_str = key.split('[')[1].split(']')[0]
                            action_item_indices.add(idx_str)

                    # Build action items list
                    for idx in sorted(action_item_indices, key=int):
                        text = request.POST.get(f'action_items[{idx}][text]', '').strip()
                        threshold = request.POST.get(f'action_items[{idx}][threshold]', 3.0)
                        stages_raw = request.POST.getlist(f'action_items[{idx}][stages][]')
                        key = request.POST.get(f'action_items[{idx}][key]', '').strip()

                        if text:  # Only add if text is not empty
                            item = {
                                'text': text,
                                'threshold': float(threshold)
                            }

                            if key in known_keys:
                                item['key'] = key

                            # Add stages if any are selected
                            if stages_raw:
                                item['stages'] = [int(s) for s in stages_raw]

                            action_items.append(item)

                    question.action_items = add_action_item_keys(action_items)
                    question.save()

                    messages.success(request, _('Dreyfus/Agency configuration updated successfully.'))
                except Question.DoesNotExist:
                    messages.error(request, _('Question not found.'))
                except Exception as e:
                    messages.error(request, _('Error updating Dreyfus configuration: %(error)s') % {'error': str(e)})

        return redirect('questionnaire_edit', questionnaire_uuid=questionnaire.uuid)

    context = {
        'action': 'Edit',
        'questionnaire': questionnaire,
        'source_language': questionnaire.source_language,
        'translation_states': get_language_states(questionnaire),
        # The translation states prefetched the sections, questions and options
        'sections': questionnaire.sections.all(),
        'default_likert_scale': default_likert_scale,
        'default_rating_labels': default_rating_labels,
    }

    return render(request, 'admin_dashboard/questionnaire_form.html', context)


@login_required
@can_manage_questionnaires_required
def questionnaire_translate(request, questionnaire_uuid, language):
    """Translate the texts of a questionnaire into another language, next to its source texts."""

    questionnaire = get_object_or_404(
        Questionnaire,
        uuid=questionnaire_uuid,
        organization=request.organization,
    )

    if not is_language(language) or language == questionnaire.source_language:
        raise Http404

    if request.method == 'POST':
        if errors := save_text_translations(questionnaire, language, request.POST):
            for error in errors:
                messages.error(request, error)
        else:
            messages.success(request, _('Translation saved.'))

        return redirect('questionnaire_translate', questionnaire_uuid=questionnaire.uuid, language=language)

    texts = get_text_translations(questionnaire, language)
    context = {
        'questionnaire': questionnaire,
        'texts': texts,
        'state': LanguageState.from_texts(language, texts),
        'source_language_name': language_name(questionnaire.source_language),
    }

    return render(request, 'admin_dashboard/questionnaire_translate.html', context)


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


@login_required(as_json=True)
@can_manage_questionnaires_required(as_json=True)
def question_dreyfus_config_api(request, question_id):
    """API endpoint to get Dreyfus/Agency configuration for a question"""
    try:
        # Get the organization from request
        org = getattr(request, 'organization', None)

        # Get question and verify it belongs to the user's organization
        question = Question.objects.select_related('section__questionnaire').get(
            id=question_id,
            section__questionnaire__organization=org
        )

        # Extract dreyfus_mapping from config
        dreyfus_mapping = question.config.get('dreyfus_mapping', {})

        # Return configuration
        return JsonResponse({
            'dreyfus_mapping': dreyfus_mapping,
            'action_items': question.action_items
        })

    except Question.DoesNotExist:
        return JsonResponse({'error': _('Question not found')}, status=404)
    except Exception as e:
        logger.exception('Error fetching Dreyfus config')
        return JsonResponse({'error': _('Internal server error')}, status=500)


# Where a cycle stands, from its status and response counts. Together the
# stages cover every cycle exactly once. Conditions use the token_count and
# completed_count annotations of review_cycle_list.
CYCLE_STAGES = {
    'waiting': (gettext_lazy('No responses yet'), Q(status='active', completed_count=0)),
    'in_progress': (gettext_lazy('In progress'),
                    Q(status='active', completed_count__gt=0, completed_count__lt=F('token_count'))),
    'all_responded': (gettext_lazy('All responded'),
                      Q(status='active', completed_count__gt=0, completed_count=F('token_count'))),
    'completed': (gettext_lazy('Completed'), Q(status='completed')),
}

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
        # Filter out cycles for anonymized reviewees
        cycles_qs = ReviewCycle.objects.for_organization(org).select_related(
            'reviewee', 'questionnaire', 'created_by'
        )
    else:
        cycles_qs = ReviewCycle.objects.select_related(
            'reviewee', 'questionnaire', 'created_by'
        )

    below = set() if can_view_all_reports(request.user) else reviewee_emails_below(request.user, org)
    if below:
        # Managers also see the cycles of the people below them in the org
        # chart, but only to read the report (see report_only below).
        own = visible_cycles(request.user, cycles_qs).values('pk')
        cycles_qs = cycles_qs.annotate(reviewee_email_lower=Lower('reviewee__email')).filter(
            Q(pk__in=own) | Q(reviewee_email_lower__in=below))
    else:
        cycles_qs = visible_cycles(request.user, cycles_qs)
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

    cycles_qs = cycles_qs.prefetch_related(
        'questionnaire__sections__questions'
    ).annotate(
        token_count=Count('tokens'),
        completed_count=Count('tokens', filter=Q(tokens__completed_at__isnull=False)),
        reviewee_has_active_cycle=Exists(
            ReviewCycle.objects.filter(reviewee=OuterRef('reviewee'), status='active')),
    )

    # Counts follow the search and questionnaire filters, so each stage
    # button shows what clicking it would give.
    stage_counts = {stage: cycles_qs.filter(cond).count() for stage, (_label, cond) in CYCLE_STAGES.items()}
    stage = request.GET.get('stage', '')
    if stage in CYCLE_STAGES:
        cycles_qs = cycles_qs.filter(CYCLE_STAGES[stage][1])
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
        cycle.report_only = cycle.reviewee.email.lower() in below
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
        'stages': [(key, label, stage_counts[key]) for key, (label, _cond) in CYCLE_STAGES.items()],
        'total_count': sum(stage_counts.values()),
        'sort': sort,
        'sorts': [(key, label) for key, (label, _fields) in CYCLE_SORTS.items()],
        'is_filtered': bool(q or questionnaire_filter or stage),
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


@login_required
def review_cycle_create(request):
    """Create a new review cycle (single or bulk)"""
    if request.method == 'POST':
        creation_mode = request.POST.get('creation_mode', 'single')
        questionnaire_id = request.POST.get('questionnaire')

        if not questionnaire_id:
            messages.error(request, _('Questionnaire is required.'))
            return redirect('review_cycle_create')

        category_flags = selected_category_flags(request)
        if category_flags and not any(category_flags.values()):
            messages.error(request, _('Select at least one feedback category.'))
            return redirect('review_cycle_create')

        try:
            # Get organization from request context
            org = getattr(request, 'organization', None)

            # Filter by organization to prevent cross-org access; archived
            # ones are gone from the form and must not come back through POST.
            questionnaire = Questionnaire.objects.get(
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
                reviewees = Reviewee.objects.for_organization(org).filter(is_active=True)

                # Refuse the whole batch up front so the message can say how
                # many credits it needs; the model gate still backs this up.
                credits = cycle_credits(org)
                if credits is not None and reviewees.count() > credits:
                    raise NoCycleCredits(needed=reviewees.count(), available=credits)

                # `bulk_source` controls reviewer-token pre-population:
                #   'chart' — derive from the org chart for each reviewee
                #   'empty' — no tokens yet (admins fill them in per cycle later)
                bulk_source = request.POST.get('bulk_source', 'empty')
                derived_count = 0
                unplaced_count = 0

                with transaction.atomic():
                    for reviewee in reviewees:
                        cycle = ReviewCycle.objects.create(
                            reviewee=reviewee,
                            questionnaire=questionnaire,
                            created_by=request.user,
                            status='active',
                            **category_flags
                        )
                        created_cycles.append(cycle)

                        if bulk_source == 'chart':
                            buckets = derive_reviewers(reviewee)
                            # Build the email_assignments dict the existing
                            # helper expects: emails only, no Reviewee FK.
                            email_assignments = {
                                code: [p.email.lower() for p in buckets.get(code, []) if p.email]
                                for code in cycle.active_categories
                            }
                            if any(email_assignments.values()):
                                for cat_code, emails in email_assignments.items():
                                    for _email in emails:
                                        ReviewerToken.objects.create(cycle=cycle, category=cat_code)
                                assign_tokens_to_emails(cycle, email_assignments)
                                derived_count += 1
                            else:
                                unplaced_count += 1

                # Stash the cycle UUIDs in the session for the send-invitations
                # confirmation step. Session avoids URL-length limits when the
                # org has many reviewees.
                request.session['pending_invitation_cycles'] = [
                    str(c.uuid) for c in created_cycles
                ]
                request.session['pending_bulk_source'] = bulk_source

                if bulk_source == 'chart':
                    messages.success(
                        request,
                        _('Created %(count)s review cycles. %(derived)s got reviewers from the org chart. %(unplaced)s reviewee(s) are not in a unit yet.')
                        % {'count': len(created_cycles), 'derived': derived_count, 'unplaced': unplaced_count}
                    )
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

                reviewee = Reviewee.objects.for_organization(org).get(id=reviewee_id)

                # Create review cycle (no tokens created here)
                cycle = ReviewCycle.objects.create(
                    reviewee=reviewee,
                    questionnaire=questionnaire,
                    created_by=request.user,
                    status='active',
                    **category_flags
                )

                # Reviewer emails from the picker (<category>_reviewees UUIDs)
                # and the email textareas (<category>_emails). The form hides
                # categories this cycle skips; a stale or hand-made POST must
                # not reinstate them.
                email_assignments, warnings = collect_reviewer_emails(
                    request, org, cycle.active_categories,
                )
                for w in warnings:
                    messages.warning(request, w)
                has_emails = any(email_assignments.values())

                # If emails were provided, create tokens and assign them
                if has_emails:
                    # Create tokens dynamically based on email count
                    for category_code, emails in email_assignments.items():
                        if emails:
                            for i in range(len(emails)):
                                ReviewerToken.objects.create(
                                    cycle=cycle,
                                    category=category_code
                                )

                    # Assign tokens to emails with randomization
                    assign_stats = assign_tokens_to_emails(cycle, email_assignments)

                # Send notification emails to reviewee. Defer to after the
                # transaction commits so a slow SMTP backend can't stall this
                # request (matches the pattern in api/signals.py). Without a
                # transaction it runs right here, so it has to come after the
                # tokens: the self-assessment goes to the one the form addressed.
                transaction.on_commit(lambda c=cycle: send_reviewee_notifications(c, request))

                if has_emails:
                    # Check if user wants to send invitations immediately.
                    # Defer the send to after-commit so SMTP latency never
                    # stalls the request.
                    send_now = request.POST.get('send_invitations_now') == '1'
                    if send_now and assign_stats['assigned'] > 0:
                        transaction.on_commit(
                            lambda c=cycle: send_reviewer_invitations(c)
                        )
                        messages.success(
                            request,
                            _('Review cycle created for "%(name)s" with %(assigned)s reviewer(s) invited. Invitation emails are being sent.')
                            % {'name': reviewee.name, 'assigned': assign_stats['assigned']}
                        )
                        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)
                    else:
                        messages.success(
                            request,
                            _('Review cycle created for "%(name)s" with %(assigned)s reviewer(s) assigned. Visit the invitations page to send emails.')
                            % {'name': reviewee.name, 'assigned': assign_stats['assigned']}
                        )
                        # Redirect to invitations page to send emails
                        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)
                else:
                    # No emails provided, show success and redirect to invitations.
                    # Reviewee notifications were queued via on_commit above.
                    messages.success(
                        request,
                        _('Review cycle created for "%(name)s". Notification emails are being sent to the reviewee.')
                        % {'name': reviewee.name}
                    )
                    # Redirect to invitations page to add reviewers
                    return redirect('manage_invitations', cycle_uuid=cycle.uuid)

        except NoCycleCredits as e:
            messages.error(request, str(e))
            return redirect('review_cycle_create')
        except Exception as e:
            messages.error(request, _('Error creating review cycle: %(error)s') % {'error': str(e)})
            return redirect('review_cycle_create')

    # GET request - show form
    org = request.organization or (request.user.profile.organization if hasattr(request.user, 'profile') else None)

    # Filter reviewees based on user permissions
    if hasattr(request.user, 'profile') and not request.user.profile.can_create_cycles_for_others:
        # User can only create cycles for themselves
        reviewees = Reviewee.objects.for_organization(org).filter(
            is_active=True,
            email=request.user.email
        ).order_by('name')
    else:
        reviewees = Reviewee.objects.for_organization(org).filter(is_active=True).order_by('name')

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
    has_org_chart = (
        org is not None
        and OrgUnit.objects.filter(organization=org).exists()
    )

    context = {
        'reviewees': reviewees,
        'questionnaires': questionnaires,
        'can_create_for_others': hasattr(request.user, 'profile') and request.user.profile.can_create_cycles_for_others,
        **billing_context(org, request.user),
        'has_org_chart': has_org_chart,
    }

    return render(request, 'admin_dashboard/review_cycle_form.html', context)


@login_required
def bulk_send_invitations(request):
    """Confirm + send reviewee notifications for cycles just created in bulk.

    The `review_cycle_create` view stashes the UUIDs of freshly-bulk-created
    cycles in the session under 'pending_invitation_cycles'. This view renders
    them for review on GET and defers the actual send on POST.
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

        # Always send the reviewee's own self-assessment + invite-links email.
        for cycle in cycles:
            transaction.on_commit(
                lambda c=cycle: send_reviewee_notifications(c, request)
            )

        # When the bulk was derived from the chart, tokens already have
        # reviewer_emails — also schedule those invitations so the admin gets
        # a truly one-click bulk experience.
        reviewer_invites_sent = 0
        if bulk_source == 'chart':
            for cycle in cycles:
                if cycle.tokens.filter(reviewer_email__isnull=False).exists():
                    reviewer_invites_sent += 1
                    transaction.on_commit(
                        lambda c=cycle: send_reviewer_invitations(c)
                    )

        # Clear the session once we've scheduled the sends.
        request.session.pop('pending_invitation_cycles', None)
        request.session.pop('pending_bulk_source', None)

        if reviewer_invites_sent:
            messages.success(
                request,
                _('Invitations are being sent for %(count)s review cycle(s), with reviewer invitations for %(reviewers)s of them.')
                % {'count': len(cycles), 'reviewers': reviewer_invites_sent}
            )
        else:
            messages.success(
                request,
                _('Invitations are being sent for %(count)s review cycle(s).') % {'count': len(cycles)}
            )
        return redirect('review_cycle_list')

    # Build per-cycle reviewer count summary so the preview can flag cycles
    # whose reviewees aren't meaningfully on the chart. "Unplaced" here means
    # no external reviewers derived — self-assessment alone doesn't count,
    # because every cycle has one and it would mask truly empty cycles.
    cycle_summaries = []
    for cycle in cycles:
        tokens = list(cycle.tokens.all())
        counts = {'self': 0, 'manager': 0, 'peer': 0, 'direct_report': 0}
        for t in tokens:
            if t.category in counts and t.reviewer_email:
                counts[t.category] += 1
        total = sum(counts.values())
        non_self_total = counts['manager'] + counts['peer'] + counts['direct_report']
        cycle_summaries.append({
            'cycle': cycle,
            'counts': counts,
            'total': total,
            'is_unplaced': (bulk_source == 'chart' and non_self_total == 0),
        })

    context = {
        'cycles': cycles,
        'cycle_summaries': cycle_summaries,
        'bulk_source': bulk_source,
        'derived_from_chart': bulk_source == 'chart',
        'unplaced_count': sum(1 for s in cycle_summaries if s['is_unplaced']),
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
    pending_invites = tokens.filter(reviewer_email__isnull=False, invitation_sent_at__isnull=True).count()
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
        'pending_reminders': pending_reminders,
        'email_invited_count': email_invited_count,
        'completion_rate': completion_rate,
        'claimed_completion_rate': claimed_completion_rate,
        'report_exists': report_exists,
    }

    return render(request, 'admin_dashboard/review_cycle_detail.html', context)


@login_required
def generate_report_view(request, cycle_uuid):
    """Generate or regenerate report for a review cycle"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    try:
        report = generate_report(cycle)

        # Send notification email to reviewee
        email_stats = send_report_ready_notification(report, request)

        success_msg = _('Report generated successfully for %(name)s.') % {'name': cycle.reviewee.name}
        if email_stats['sent'] > 0:
            success_msg += ' ' + _('Notification email sent.')
        if email_stats['errors']:
            success_msg += ' ' + _('(Email errors: %(errors)s)') % {'errors': ', '.join(email_stats['errors'])}

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

    # Mark cycle as completed
    cycle.status = 'completed'
    cycle.save()

    # Generate report
    try:
        report = generate_report(cycle)

        # Send notification email to reviewee
        email_stats = send_report_ready_notification(report, request)

        success_msg = _('Cycle closed and report generated for %(name)s.') % {'name': cycle.reviewee.name}
        if email_stats['sent'] > 0:
            success_msg += ' ' + _('Notification email sent.')

        messages.success(request, success_msg)
    except Exception as e:
        messages.error(request, _('Cycle closed but error generating report: %(error)s') % {'error': str(e)})

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

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        # Check if user wants to send invitations immediately
        action = request.POST.get('action', 'assign')
        if action == 'assign' and stats['assigned'] > 0:
            # Send invitations immediately
            send_stats = send_reviewer_invitations(cycle)

            if send_stats['sent'] > 0:
                messages.success(request, _('Successfully invited %(assigned)s reviewer(s) and sent %(sent)s email(s).') % {'assigned': stats['assigned'], 'sent': send_stats['sent']})
            else:
                messages.success(request, _('Successfully assigned %(assigned)s email(s). Invitations will be sent separately.') % {'assigned': stats['assigned']})

            if send_stats['errors']:
                for error in send_stats['errors']:
                    messages.error(request, error)
        elif stats['assigned'] > 0:
            messages.success(request, _('Successfully assigned %(assigned)s email(s). No invitations sent yet.') % {'assigned': stats['assigned']})

        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    return redirect('manage_invitations', cycle_uuid=cycle.uuid)


@login_required
def send_invitations(request, cycle_uuid):
    """Send email invitations to assigned reviewers"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    if request.method == 'POST':
        token_id = request.POST.get('token_id')
        stats = send_reviewer_invitations(cycle, token_ids=[token_id] if token_id else None)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        if stats['sent'] > 0:
            messages.success(request, _('Successfully sent %(sent)s invitation email(s).') % {'sent': stats['sent']})
        elif stats['sent'] == 0 and not stats['errors']:
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

    stats = {'sent': 0, 'errors': []}
    send_invitation_links_email(cycle, categories, stats)

    for error in stats['errors']:
        messages.error(request, error)
    if stats['sent']:
        messages.success(request, _('The links have been sent to %(email)s.') % {'email': cycle.reviewee.email})

    return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)


@login_required
def send_reminder(request, cycle_uuid):
    """Send reminder emails for pending reviews"""
    cycle = get_cycle_or_404(request, cycle_uuid)

    if request.method == 'POST':
        # Send reminders
        stats = send_reminder_emails(cycle)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        if stats['sent'] > 0:
            messages.success(request, _('Successfully sent %(sent)s reminder(s).') % {'sent': stats['sent']})
        elif stats['sent'] == 0 and not stats['errors']:
            messages.info(request, _('No pending reminders to send.'))

        return redirect('review_cycle_detail', cycle_uuid=cycle.uuid)

    return redirect('send_reminder_form', cycle_uuid=cycle.uuid)


@login_required
@require_POST
def send_individual_reminder(request, cycle_uuid, token_id):
    """Send a reminder email to a specific reviewer"""
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

        # The shared reminder picks the reviewer's language and the organization's mail server
        stats = send_reminder_emails(cycle, token_ids=[token.id])

        if stats['sent']:
            messages.success(request, _('Reminder sent to reviewer.'))
        for error in stats['errors']:
            messages.error(request, error)

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
                # Auto-close the cycle
                cycle.status = 'completed'
                cycle.save()

                # Auto-generate report
                try:
                    report = generate_report(cycle)

                    # Send notification email if organization setting enabled
                    organization = cycle.reviewee.organization
                    if organization and organization.auto_send_report_email:
                        email_stats = send_report_ready_notification(report, request)
                        if email_stats.get('errors'):
                            logger.error("Errors sending report email for cycle %s: %s", cycle.id, email_stats['errors'])

                    messages.success(request, _('Cycle automatically closed and report generated (all remaining reviewers completed).'))
                except Exception as e:
                    # Log error but don't fail the removal
                    logger.exception("Error auto-generating report for cycle %s", cycle.id)
                    messages.warning(request, _('Cycle closed but error generating report: %(error)s') % {'error': str(e)})

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

    # Send notification email
    email_stats = send_report_ready_notification(report, request)

    if email_stats['sent'] > 0:
        messages.success(request, _('Report email sent to %(name)s at %(email)s.') % {'name': cycle.reviewee.name, 'email': cycle.reviewee.email})
    else:
        if email_stats['errors']:
            for error in email_stats['errors']:
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
    locked = env_managed_fields()

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
                # Update registration settings
                organization.allow_registration = request.POST.get('allow_registration') == 'on'
                organization.default_users_can_create_cycles = request.POST.get('default_users_can_create_cycles') == 'on'
                organization.save()
                messages.success(request, _('Registration settings updated successfully.'))

            elif section == 'reports':
                # Update report settings
                min_responses = request.POST.get('min_responses_for_anonymity', 3)
                try:
                    organization.min_responses_for_anonymity = int(min_responses)
                except (ValueError, TypeError):
                    organization.min_responses_for_anonymity = 3
                organization.auto_send_report_email = request.POST.get('auto_send_report_email') == 'on'
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

    # Get subscription information if exists
    subscription = None
    try:
        subscription = organization.subscription
    except (Subscription.DoesNotExist, AttributeError):
        pass
    except Exception:
        logger.exception("Error getting subscription for %s", organization.name)

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
        'subscription': subscription,
        'is_org_admin': is_org_admin,
        'admin_count': admin_count,
        'is_last_admin': is_org_admin and admin_count == 1,
        'api_tokens': api_tokens,
        'webhooks': webhooks,
        'new_token': new_token,
        'new_token_name': new_token_name,
        'locked_fields': locked,
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

    if not request.user.has_perm('accounts.can_manage_organization'):
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
        request.session['new_api_token'] = token.token
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

    if not request.user.has_perm('accounts.can_manage_organization'):
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

    if not request.user.has_perm('accounts.can_manage_organization'):
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


def _chart_change_response(organization):
    """
    Response after any mutation: both views and the unplaced pool, rendered
    again in full. Any membership change can move units in the hierarchy, so
    patching parts of the page would go stale.
    """
    context = _org_chart_context(organization)
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
        messages.error(request, 'No organization found.')
        return redirect('admin_dashboard')

    context = _org_chart_context(org)
    return render(request, 'admin_dashboard/org_chart/index.html', context)


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
    from accounts.org_import import FIELDS, guess_mapping, import_org_chart, map_rows

    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('You do not have permission to edit the org chart.'))
        return redirect('org_chart')
    upload = request.session.get('org_import')
    if not upload:
        return redirect('org_chart')
    headers, rows = upload['headers'], upload['rows']

    errors = []
    if request.method == 'POST':
        mapping = {}
        for field, _label in FIELDS:
            try:
                mapping[field] = int(request.POST.get(field, ''))
            except ValueError:
                mapping[field] = None
        mapped, errors = map_rows(headers, rows, mapping)
        if not errors:
            stats, errors = import_org_chart(request.organization, mapped)
            if not errors:
                del request.session['org_import']
                messages.success(
                    request,
                    _('Imported %(units)s units: %(created)s new people, %(updated)s updated.') % stats,
                )
                return redirect('org_chart')
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
        'has_units': OrgUnit.objects.filter(organization=request.organization).exists(),
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
        return JsonResponse({'error': 'Unit name is required.'}, status=400)

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
            return JsonResponse({'error': 'Unit name is required.'}, status=400)
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
    row = 0 if role == OrgUnitMembership.MANAGER else 1

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

        # Append at the next unused col in this row.
        next_col = (
            unit.memberships.filter(row=row)
            .aggregate(m=Max('col'))['m']
        )
        col = 0 if next_col is None else next_col + 1

        OrgUnitMembership.objects.create(
            unit=unit,
            reviewee=reviewee,
            row=row,
            col=col,
        )

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
    AJAX endpoint that returns the four reviewer buckets derived from the org
    chart for a given reviewee UUID.

    Response:
        {
            'self':           [{'uuid', 'name', 'email'}, ...],
            'manager':        [...],
            'peer':           [...],
            'direct_report':  [...],
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

    buckets = derive_reviewers(reviewee)

    return JsonResponse({
        cat: [
            {'uuid': str(r.uuid), 'name': r.name, 'email': r.email}
            for r in people
        ]
        for cat, people in buckets.items()
    })
