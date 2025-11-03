"""
Admin dashboard views for Blik
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Count, Q, Max
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.http import HttpResponseRedirect
from datetime import timedelta

from accounts.models import Reviewee, UserProfile, OrganizationInvitation
from reviews.models import ReviewCycle, ReviewerToken
from reviews.services import assign_tokens_to_emails, send_reviewer_invitations
from questionnaires.models import Questionnaire
from reports.models import Report
from core.models import Organization
from core.gdpr import GDPRDeletionService


def get_cycle_or_404(cycle_id, organization):
    """
    Get a ReviewCycle by ID, filtered by organization to prevent cross-org access.
    Returns 404 if cycle doesn't exist or belongs to a different organization.
    """
    cycles_qs = ReviewCycle.objects.select_related('reviewee', 'questionnaire', 'created_by')
    if organization:
        cycles_qs = cycles_qs.filter(reviewee__organization=organization)
    return get_object_or_404(cycles_qs, id=cycle_id)


@login_required
def dashboard(request):
    """Admin dashboard homepage"""
    from subscriptions.utils import get_subscription_status

    org = request.organization

    # Get statistics filtered by organization
    reviewees_qs = Reviewee.objects.for_organization(org).filter(is_active=True)
    cycles_qs = ReviewCycle.objects.for_organization(org).select_related('reviewee', 'questionnaire')

    total_reviewees = reviewees_qs.count()
    active_cycles = cycles_qs.filter(status='active').count()
    completed_cycles = cycles_qs.filter(status='completed').count()

    # Get subscription status
    subscription_status = get_subscription_status(org) if org else None

    # Recent activity
    recent_cycles = cycles_qs.all()[:5]

    # Pending reviews (tokens not completed)
    pending_tokens = ReviewerToken.objects.for_organization(org).filter(
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
    from productreviews.models import ProductReview
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
    from subscriptions.utils import get_subscription_status

    org = request.organization

    if not org:
        messages.error(request, 'No organization found.')
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
    }

    return render(request, 'admin_dashboard/team.html', context)


@login_required
@require_POST
def update_user_permissions(request):
    """Update user permissions and role"""
    from accounts.permissions import assign_organization_admin, assign_organization_member
    from django.contrib.auth.models import Group

    # Check if requester has permission to manage organization
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, 'You do not have permission to manage user permissions.')
        return redirect('team_list')

    org = request.organization
    if not org:
        messages.error(request, 'No organization found.')
        return redirect('admin_dashboard')

    try:
        user_profile_id = request.POST.get('user_profile_id')
        role = request.POST.get('role')  # 'admin' or 'member'
        can_create_cycles_for_others = request.POST.get('can_create_cycles_for_others') == 'on'

        if not user_profile_id or not role:
            messages.error(request, 'Invalid request: missing required fields.')
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
            messages.error(request, 'You cannot modify your own permissions.')
            return redirect('team_list')

        if target_user.is_superuser:
            messages.error(request, 'Cannot modify permissions for super admins.')
            return redirect('team_list')

        # Check if this would be the last admin
        if target_user.has_perm('accounts.can_manage_organization') and role == 'member':
            # Count users with organization admin permission
            admin_profiles = UserProfile.objects.filter(organization=org).select_related('user')
            admin_count = sum(1 for p in admin_profiles if p.user.has_perm('accounts.can_manage_organization'))

            if admin_count <= 1:
                messages.error(request, 'Cannot demote the last organization administrator.')
                return redirect('team_list')

        # Update role and permissions
        if role == 'admin':
            assign_organization_admin(target_user)
            messages.success(request, f'Successfully promoted {target_user.username} to Organization Admin.')
        else:  # member
            # Remove admin permissions
            assign_organization_member(target_user, can_create_cycles_for_others=False)
            messages.success(request, f'Successfully updated {target_user.username} to Member role.')

        # Update can_create_cycles_for_others permission separately
        # (this can be set independently of role)
        user_profile.refresh_from_db()
        user_profile.can_create_cycles_for_others = can_create_cycles_for_others
        user_profile.save()

        if can_create_cycles_for_others:
            messages.success(request, f'{target_user.username} can now create review cycles for others.')

    except Exception as e:
        messages.error(request, f'Error updating permissions: {str(e)}')

    return redirect('team_list')


@login_required
def reviewee_list(request):
    """List and manage reviewees"""
    from subscriptions.utils import get_subscription_status
    from questionnaires.models import Questionnaire

    org = request.organization
    # Filter out anonymized reviewees (those with @deleted.invalid emails)
    reviewees_qs = Reviewee.objects.for_organization(org).filter(is_active=True).annotate(
        cycle_count=Count('review_cycles')
    ).order_by('name')

    # Get per_page from request, default to 25
    per_page = request.GET.get('per_page', '25')
    try:
        per_page = int(per_page)
        if per_page not in [25, 50, 100]:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25

    # Paginate reviewees
    paginator = Paginator(reviewees_qs, per_page)
    page = request.GET.get('page')
    try:
        reviewees = paginator.page(page)
    except PageNotAnInteger:
        reviewees = paginator.page(1)
    except EmptyPage:
        reviewees = paginator.page(paginator.num_pages)

    # Get subscription status
    subscription_status = get_subscription_status(org) if org else None

    # Get available questionnaires for quick cycle creation
    questionnaires = Questionnaire.objects.for_organization(org).filter(is_active=True).order_by('-is_default', 'name')

    # Annotate each reviewee with their latest cycle info
    reviewees_with_latest = []
    for reviewee in reviewees:
        latest_cycle = reviewee.review_cycles.select_related('questionnaire').order_by('-created_at').first()
        reviewees_with_latest.append({
            'reviewee': reviewee,
            'latest_questionnaire': latest_cycle.questionnaire if latest_cycle else None,
        })

    context = {
        'reviewees_with_latest': reviewees_with_latest,
        'reviewees': reviewees,  # Paginated object
        'questionnaires': questionnaires,
        'subscription_status': subscription_status,
        'per_page': per_page,
    }

    return render(request, 'admin_dashboard/reviewee_list.html', context)


@login_required
def reviewee_create(request):
    """Create a new reviewee"""
    from subscriptions.utils import check_employee_limit
    from accounts.permissions import is_organization_admin

    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        department = request.POST.get('department', '')

        if name and email:
            organization = request.organization or Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please run setup first.')
                return redirect('admin_dashboard')

            # Non-admins can only create reviewees for themselves
            if not is_organization_admin(request.user):
                if email.lower() != request.user.email.lower():
                    messages.error(request, 'You can only create a reviewee profile for yourself.')
                    return redirect('reviewee_list')

            # Check employee limit
            allowed, error_message = check_employee_limit(request)
            if not allowed:
                messages.error(request, error_message)
                return redirect('reviewee_list')

            try:
                reviewee = Reviewee.objects.create(
                    organization=organization,
                    name=name,
                    email=email,
                    department=department
                )
                messages.success(request, f'Reviewee "{reviewee.name}" created successfully.')
                return redirect('reviewee_list')
            except Exception as e:
                messages.error(request, f'Error creating reviewee: {str(e)}')
        else:
            messages.error(request, 'Name and email are required.')

    return render(request, 'admin_dashboard/reviewee_form.html', {'action': 'Create'})


@login_required
def reviewee_edit(request, reviewee_id):
    """Edit an existing reviewee - admin only"""
    from accounts.permissions import organization_admin_required

    # Check admin permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(
            request,
            'You do not have permission to edit reviewees. Only organization administrators can access this feature.'
        )
        return redirect('reviewee_list')

    reviewee = get_object_or_404(Reviewee, id=reviewee_id)

    if request.method == 'POST':
        reviewee.name = request.POST.get('name', reviewee.name)
        reviewee.email = request.POST.get('email', reviewee.email)
        reviewee.department = request.POST.get('department', '')

        try:
            reviewee.save()
            messages.success(request, f'Reviewee "{reviewee.name}" updated successfully.')
            return redirect('reviewee_list')
        except Exception as e:
            messages.error(request, f'Error updating reviewee: {str(e)}')

    context = {
        'reviewee': reviewee,
        'action': 'Edit',
    }

    return render(request, 'admin_dashboard/reviewee_form.html', context)


@login_required
def reviewee_delete(request, reviewee_id):
    """Soft delete a reviewee - admin only"""
    from accounts.permissions import organization_admin_required

    # Check admin permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(
            request,
            'You do not have permission to delete reviewees. Only organization administrators can access this feature.'
        )
        return redirect('reviewee_list')

    reviewee = get_object_or_404(Reviewee, id=reviewee_id)

    if request.method == 'POST':
        reviewee.is_active = False
        reviewee.save()
        messages.success(request, f'Reviewee "{reviewee.name}" deactivated.')
        return redirect('reviewee_list')

    context = {
        'reviewee': reviewee,
    }

    return render(request, 'admin_dashboard/reviewee_confirm_delete.html', context)


@login_required
@require_POST
def quick_cycle_create(request, reviewee_id):
    """
    Quick cycle creation from reviewee list.
    Creates a cycle with default token counts (1 self, 3 peers, 1 manager, 0 direct reports).
    """
    from accounts.permissions import organization_admin_required

    # Check admin permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(
            request,
            'You do not have permission to create review cycles. Only organization administrators can access this feature.'
        )
        return redirect('reviewee_list')

    org = request.organization
    reviewee = get_object_or_404(Reviewee, id=reviewee_id, organization=org, is_active=True)
    questionnaire_id = request.POST.get('questionnaire_id')

    if not questionnaire_id:
        messages.error(request, 'Questionnaire is required.')
        return redirect('reviewee_list')

    try:
        questionnaire = Questionnaire.objects.get(id=questionnaire_id, organization=org)
    except Questionnaire.DoesNotExist:
        messages.error(request, 'Invalid questionnaire selected.')
        return redirect('reviewee_list')

    # Create the cycle with default token counts
    cycle = ReviewCycle.objects.create(
        reviewee=reviewee,
        questionnaire=questionnaire,
        created_by=request.user,
        status='active'
    )

    # Default token distribution: 1 self, 3 peers, 1 manager, 0 direct reports
    token_distribution = [
        ('self', 1),
        ('peer', 3),
        ('manager', 1),
        ('direct_report', 0),
    ]

    total_tokens = 0
    for category, count in token_distribution:
        for _ in range(count):
            ReviewerToken.objects.create(
                cycle=cycle,
                category=category
            )
            total_tokens += count

    messages.success(
        request,
        f'Review cycle created for "{reviewee.name}" using "{questionnaire.name}" with {total_tokens} reviewer tokens. '
        f'Go to the cycle details to assign reviewers and send invitations.'
    )

    # Redirect to cycle detail page to manage tokens
    return redirect('review_cycle_detail', cycle_id=cycle.id)


@login_required
def questionnaire_list(request):
    """List available questionnaires"""
    from django.db.models import Subquery, OuterRef
    from questionnaires.models import Question

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
    ).order_by('-is_default', 'name')

    context = {
        'questionnaires': questionnaires,
    }

    return render(request, 'admin_dashboard/questionnaire_list.html', context)


@login_required
def questionnaire_preview(request, questionnaire_id):
    """Preview a questionnaire"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    sections = questionnaire.sections.prefetch_related('questions').all()

    context = {
        'questionnaire': questionnaire,
        'sections': sections,
    }

    return render(request, 'admin_dashboard/questionnaire_preview.html', context)


@login_required
def questionnaire_create(request):
    """Create a new questionnaire"""
    from questionnaires.models import QuestionSection, Question

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        is_default = request.POST.get('is_default') == 'on'

        if not name:
            messages.error(request, 'Questionnaire name is required.')
            return render(request, 'admin_dashboard/questionnaire_form.html', {'action': 'Create'})

        try:
            # Get organization from request context
            org = getattr(request, 'organization', None)

            questionnaire = Questionnaire.objects.create(
                name=name,
                description=description,
                is_default=is_default,
                organization=org
            )
            messages.success(request, f'Questionnaire "{questionnaire.name}" created successfully.')
            return redirect('questionnaire_edit', questionnaire_id=questionnaire.id)
        except Exception as e:
            messages.error(request, f'Error creating questionnaire: {str(e)}')

    context = {
        'action': 'Create',
    }

    return render(request, 'admin_dashboard/questionnaire_form.html', context)


@login_required
def questionnaire_edit(request, questionnaire_id):
    """Edit an existing questionnaire"""
    from questionnaires.models import QuestionSection, Question

    # Get organization from request context
    org = getattr(request, 'organization', None)

    # Filter by organization to prevent cross-org access
    questionnaire = get_object_or_404(
        Questionnaire,
        id=questionnaire_id,
        organization=org
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_info':
            questionnaire.name = request.POST.get('name', questionnaire.name)
            questionnaire.description = request.POST.get('description', '')
            questionnaire.is_default = request.POST.get('is_default') == 'on'

            try:
                questionnaire.save()
                messages.success(request, f'Questionnaire "{questionnaire.name}" updated successfully.')
            except Exception as e:
                messages.error(request, f'Error updating questionnaire: {str(e)}')

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
                    messages.success(request, f'Section "{section_title}" added.')
                except Exception as e:
                    messages.error(request, f'Error adding section: {str(e)}')

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
                    messages.success(request, f'Section "{section_title}" updated successfully.')
                except QuestionSection.DoesNotExist:
                    messages.error(request, 'Section not found.')
                except Exception as e:
                    messages.error(request, f'Error updating section: {str(e)}')

        elif action == 'add_question':
            section_id = request.POST.get('section_id')
            question_text = request.POST.get('question_text')
            question_type = request.POST.get('question_type', 'rating')
            required = request.POST.get('required') == 'on'

            if section_id and question_text:
                try:
                    section = QuestionSection.objects.get(id=section_id, questionnaire=questionnaire)
                    max_order = section.questions.aggregate(Max('order'))['order__max']
                    next_order = (max_order + 1) if max_order is not None else 0

                    # Build config based on question type
                    config = {}
                    if question_type == 'rating':
                        config = {
                            'min': 1,
                            'max': 5,
                            'labels': {
                                '1': 'Strongly Disagree',
                                '2': 'Disagree',
                                '3': 'Neutral',
                                '4': 'Agree',
                                '5': 'Strongly Agree'
                            }
                        }
                    elif question_type == 'likert':
                        scale_raw = request.POST.get('likert_scale', '')
                        if scale_raw:
                            scale = [s.strip() for s in scale_raw.split('\n') if s.strip()]
                        else:
                            scale = ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree']
                        config = {'scale': scale}
                    elif question_type == 'single_choice' or question_type == 'multiple_choice':
                        choices_raw = request.POST.get('choices', '')
                        choices = [c.strip() for c in choices_raw.split('\n') if c.strip()]
                        config = {'choices': choices}

                        # Check if scoring is enabled and weights are provided
                        enable_scoring = request.POST.get('enable_scoring') == 'on'
                        if enable_scoring:
                            weights_raw = request.POST.getlist('weights[]')
                            try:
                                # Parse weights as floats
                                weights = [float(w) for w in weights_raw if w.strip()]
                                # Validate: weights must match choices length
                                if len(weights) == len(choices):
                                    config['weights'] = weights
                                    config['scoring_enabled'] = True
                                else:
                                    messages.warning(request, 'Weights count did not match choices count. Scoring disabled for this question.')
                            except (ValueError, TypeError):
                                messages.warning(request, 'Invalid weight values. Scoring disabled for this question.')
                    elif question_type == 'scale':
                        try:
                            min_val = int(request.POST.get('scale_min', 1))
                            max_val = int(request.POST.get('scale_max', 100))
                            step_val = int(request.POST.get('scale_step', 1))
                            min_label = request.POST.get('scale_min_label', '').strip()
                            max_label = request.POST.get('scale_max_label', '').strip()

                            config = {
                                'min': min_val,
                                'max': max_val,
                                'step': step_val
                            }
                            if min_label:
                                config['min_label'] = min_label
                            if max_label:
                                config['max_label'] = max_label
                        except (ValueError, TypeError):
                            # Use defaults if parsing fails
                            config = {'min': 1, 'max': 100, 'step': 1}
                            messages.warning(request, 'Invalid scale values. Using defaults (1-100, step 1).')

                    Question.objects.create(
                        section=section,
                        question_text=question_text,
                        question_type=question_type,
                        config=config,
                        required=required,
                        order=next_order
                    )
                    messages.success(request, 'Question added successfully.')
                except Exception as e:
                    messages.error(request, f'Error adding question: {str(e)}')

        elif action == 'delete_section':
            section_id = request.POST.get('section_id')
            try:
                section = QuestionSection.objects.get(id=section_id, questionnaire=questionnaire)
                section_title = section.title
                section.delete()
                messages.success(request, f'Section "{section_title}" deleted.')
            except Exception as e:
                messages.error(request, f'Error deleting section: {str(e)}')

        elif action == 'delete_question':
            question_id = request.POST.get('question_id')
            try:
                question = Question.objects.get(id=question_id, section__questionnaire=questionnaire)
                question.delete()
                messages.success(request, 'Question deleted.')
            except Exception as e:
                messages.error(request, f'Error deleting question: {str(e)}')

        elif action == 'edit_question':
            question_id = request.POST.get('question_id')
            question_text = request.POST.get('question_text')
            question_type = request.POST.get('question_type', 'rating')
            required = request.POST.get('required') == 'on'

            if question_id and question_text:
                try:
                    question = Question.objects.get(id=question_id, section__questionnaire=questionnaire)

                    # Update basic fields
                    question.question_text = question_text
                    question.question_type = question_type
                    question.required = required

                    # Build config based on question type
                    config = {}
                    if question_type == 'rating':
                        config = {
                            'min': 1,
                            'max': 5,
                            'labels': {
                                '1': 'Strongly Disagree',
                                '2': 'Disagree',
                                '3': 'Neutral',
                                '4': 'Agree',
                                '5': 'Strongly Agree'
                            }
                        }
                    elif question_type == 'likert':
                        scale_raw = request.POST.get('likert_scale', '')
                        if scale_raw:
                            scale = [s.strip() for s in scale_raw.split('\n') if s.strip()]
                        else:
                            scale = ['Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree']
                        config = {'scale': scale}
                    elif question_type == 'single_choice' or question_type == 'multiple_choice':
                        choices_raw = request.POST.get('choices', '')
                        choices = [c.strip() for c in choices_raw.split('\n') if c.strip()]
                        config = {'choices': choices}

                        # Check if scoring is enabled and weights are provided
                        enable_scoring = request.POST.get('enable_scoring') == 'on'
                        if enable_scoring:
                            weights_raw = request.POST.getlist('weights[]')
                            try:
                                # Parse weights as floats
                                weights = [float(w) for w in weights_raw if w.strip()]
                                # Validate: weights must match choices length
                                if len(weights) == len(choices):
                                    config['weights'] = weights
                                    config['scoring_enabled'] = True
                                else:
                                    messages.warning(request, 'Weights count did not match choices count. Scoring disabled for this question.')
                            except (ValueError, TypeError):
                                messages.warning(request, 'Invalid weight values. Scoring disabled for this question.')
                    elif question_type == 'scale':
                        try:
                            min_val = int(request.POST.get('scale_min', 1))
                            max_val = int(request.POST.get('scale_max', 100))
                            step_val = int(request.POST.get('scale_step', 1))
                            min_label = request.POST.get('scale_min_label', '').strip()
                            max_label = request.POST.get('scale_max_label', '').strip()

                            config = {
                                'min': min_val,
                                'max': max_val,
                                'step': step_val
                            }
                            if min_label:
                                config['min_label'] = min_label
                            if max_label:
                                config['max_label'] = max_label
                        except (ValueError, TypeError):
                            # Use defaults if parsing fails
                            config = {'min': 1, 'max': 100, 'step': 1}
                            messages.warning(request, 'Invalid scale values. Using defaults (1-100, step 1).')

                    question.config = config
                    question.save()

                    messages.success(request, 'Question updated successfully.')
                except Exception as e:
                    messages.error(request, f'Error updating question: {str(e)}')

        return redirect('questionnaire_edit', questionnaire_id=questionnaire.id)

    sections = questionnaire.sections.prefetch_related('questions').all()

    context = {
        'action': 'Edit',
        'questionnaire': questionnaire,
        'sections': sections,
    }

    return render(request, 'admin_dashboard/questionnaire_form.html', context)


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

    cycles_qs = cycles_qs.annotate(
        token_count=Count('tokens'),
        completed_count=Count('tokens', filter=Q(tokens__completed_at__isnull=False))
    ).order_by('-created_at')

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
    questionnaires = Questionnaire.objects.for_organization(org).filter(is_active=True).order_by('-is_default', 'name')

    # Enhance cycles with latest questionnaire info for each reviewee
    cycles_with_latest = []
    for cycle in cycles:
        latest_cycle = cycle.reviewee.review_cycles.select_related('questionnaire').order_by('-created_at').first()
        cycles_with_latest.append({
            'cycle': cycle,
            'latest_questionnaire': latest_cycle.questionnaire if latest_cycle else None,
        })

    context = {
        'cycles_with_latest': cycles_with_latest,
        'cycles': cycles,  # Paginated object
        'questionnaires': questionnaires,
        'per_page': per_page,
    }

    return render(request, 'admin_dashboard/review_cycle_list.html', context)


@login_required
def review_cycle_create(request):
    """Create a new review cycle (single or bulk)"""
    if request.method == 'POST':
        creation_mode = request.POST.get('creation_mode', 'single')
        questionnaire_id = request.POST.get('questionnaire')

        if not questionnaire_id:
            messages.error(request, 'Questionnaire is required.')
            return redirect('review_cycle_create')

        try:
            # Get organization from request context
            org = getattr(request, 'organization', None)

            # Filter by organization to prevent cross-org access
            questionnaire = Questionnaire.objects.get(
                id=questionnaire_id,
                organization=org
            )
            created_cycles = []

            if creation_mode == 'bulk':
                # Create cycles for all active reviewees
                reviewees = Reviewee.objects.for_organization(org).filter(is_active=True)

                for reviewee in reviewees:
                    cycle = ReviewCycle.objects.create(
                        reviewee=reviewee,
                        questionnaire=questionnaire,
                        created_by=request.user,
                        status='active'
                    )

                    created_cycles.append(cycle)

                    # Send notification emails to reviewee
                    from reviews.services import send_reviewee_notifications
                    send_reviewee_notifications(cycle, request)

                messages.success(
                    request,
                    f'Created {len(created_cycles)} review cycles for all active reviewees. Notification emails sent.'
                )
                return redirect('review_cycle_list')

            else:
                # Single reviewee mode
                reviewee_id = request.POST.get('reviewee')
                if not reviewee_id:
                    messages.error(request, 'Reviewee is required for single cycle creation.')
                    return redirect('review_cycle_create')

                reviewee = Reviewee.objects.for_organization(org).get(id=reviewee_id)

                # Create review cycle (no tokens created here)
                cycle = ReviewCycle.objects.create(
                    reviewee=reviewee,
                    questionnaire=questionnaire,
                    created_by=request.user,
                    status='active'
                )

                # Send notification emails to reviewee
                from reviews.services import send_reviewee_notifications
                email_stats = send_reviewee_notifications(cycle, request)

                # Check if user provided reviewer emails
                from django.core.validators import validate_email
                from django.core.exceptions import ValidationError
                import re

                email_assignments = {}
                has_emails = False

                for category_code, category_display in ReviewerToken.CATEGORY_CHOICES:
                    emails_data = request.POST.get(f'{category_code}_emails', '').strip()
                    if emails_data:
                        emails = re.split(r'[,\n]+', emails_data)
                        validated_emails = []
                        for e in emails:
                            e = e.strip()
                            if e:
                                try:
                                    validate_email(e)
                                    validated_emails.append(e)
                                    has_emails = True
                                except ValidationError:
                                    messages.warning(request, f'Invalid email skipped in {category_display}: {e}')
                        email_assignments[category_code] = validated_emails
                    else:
                        email_assignments[category_code] = []

                # If emails were provided, create tokens and assign them
                if has_emails:
                    # Create tokens dynamically based on email count
                    for category_code, emails in email_assignments.items():
                        if emails:
                            for _ in range(len(emails)):
                                ReviewerToken.objects.create(
                                    cycle=cycle,
                                    category=category_code
                                )

                    # Assign tokens to emails with randomization
                    assign_stats = assign_tokens_to_emails(cycle, email_assignments)

                    # Check if user wants to send invitations immediately
                    send_now = request.POST.get('send_invitations_now') == '1'
                    if send_now and assign_stats['assigned'] > 0:
                        send_stats = send_reviewer_invitations(cycle)
                        if send_stats['sent'] > 0:
                            messages.success(
                                request,
                                f'Review cycle created for "{reviewee.name}" with {assign_stats["assigned"]} reviewer(s) invited. {send_stats["sent"]} invitation email(s) sent.'
                            )
                            # Redirect to cycle detail since invitations were sent
                            return redirect('review_cycle_detail', cycle_id=cycle.id)
                        else:
                            messages.success(
                                request,
                                f'Review cycle created for "{reviewee.name}" with {assign_stats["assigned"]} reviewer(s) assigned.'
                            )
                            # Redirect to invitations page since emails weren't sent
                            return redirect('manage_invitations', cycle_id=cycle.id)
                    else:
                        messages.success(
                            request,
                            f'Review cycle created for "{reviewee.name}" with {assign_stats["assigned"]} reviewer(s) assigned. Visit the invitations page to send emails.'
                        )
                        # Redirect to invitations page to send emails
                        return redirect('manage_invitations', cycle_id=cycle.id)
                else:
                    # No emails provided, show success and redirect to invitations
                    success_msg = f'Review cycle created for "{reviewee.name}".'
                    if email_stats['sent'] > 0:
                        success_msg += f' {email_stats["sent"]} notification email(s) sent.'
                    if email_stats['errors']:
                        success_msg += f' (Email errors: {", ".join(email_stats["errors"])})'

                    messages.success(request, success_msg)
                    # Redirect to invitations page to add reviewers
                    return redirect('manage_invitations', cycle_id=cycle.id)

        except Exception as e:
            messages.error(request, f'Error creating review cycle: {str(e)}')
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

    # Only show questionnaires from user's organization
    questionnaires = Questionnaire.objects.for_organization(org).order_by('-is_default', 'name')

    context = {
        'reviewees': reviewees,
        'questionnaires': questionnaires,
        'can_create_for_others': hasattr(request.user, 'profile') and request.user.profile.can_create_cycles_for_others,
    }

    return render(request, 'admin_dashboard/review_cycle_form.html', context)


@login_required
def review_cycle_detail(request, cycle_id):
    """View details of a review cycle"""
    cycle = get_cycle_or_404(cycle_id, request.organization)

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
def generate_report_view(request, cycle_id):
    """Generate or regenerate report for a review cycle"""
    from reports.services import generate_report, send_report_ready_notification

    cycle = get_cycle_or_404(cycle_id, request.organization)

    try:
        report = generate_report(cycle)

        # Send notification email to reviewee
        email_stats = send_report_ready_notification(report, request)

        success_msg = f'Report generated successfully for {cycle.reviewee.name}.'
        if email_stats['sent'] > 0:
            success_msg += ' Notification email sent.'
        if email_stats['errors']:
            success_msg += f' (Email errors: {", ".join(email_stats["errors"])})'

        messages.success(request, success_msg)
    except Exception as e:
        messages.error(request, f'Error generating report: {str(e)}')

    return redirect('review_cycle_detail', cycle_id=cycle.id)


@login_required
def close_cycle(request, cycle_id):
    """Close/complete a review cycle and generate report if possible"""
    if request.method != 'POST':
        return redirect('review_cycle_detail', cycle_id=cycle_id)

    cycle = get_cycle_or_404(cycle_id, request.organization)

    if cycle.status != 'active':
        messages.warning(request, 'This cycle is already completed.')
        return redirect('review_cycle_detail', cycle_id=cycle_id)

    # Check if there are any completed reviews
    completed_count = cycle.tokens.filter(completed_at__isnull=False).count()

    if completed_count == 0:
        messages.error(request, 'Cannot close cycle: No reviews have been completed yet.')
        return redirect('review_cycle_detail', cycle_id=cycle_id)

    # Remove unclaimed tokens (tokens that are still active but not claimed)
    # Keep claimed tokens as an indication that the report was closed while people were still working
    unclaimed_tokens = cycle.tokens.filter(claimed_at__isnull=True, completed_at__isnull=True)
    unclaimed_count = unclaimed_tokens.count()
    unclaimed_tokens.delete()

    # Mark cycle as completed
    cycle.status = 'completed'
    cycle.save()

    # Generate report
    from reports.services import generate_report, send_report_ready_notification
    try:
        report = generate_report(cycle)

        # Send notification email to reviewee
        email_stats = send_report_ready_notification(report, request)

        success_msg = f'Cycle closed and report generated for {cycle.reviewee.name}.'
        if email_stats['sent'] > 0:
            success_msg += ' Notification email sent.'

        messages.success(request, success_msg)
    except Exception as e:
        messages.error(request, f'Cycle closed but error generating report: {str(e)}')

    return redirect('review_cycle_detail', cycle_id=cycle_id)


@login_required
def send_reminder_form(request, cycle_id):
    """Show form to send reminders for pending reviews"""
    cycle = get_cycle_or_404(cycle_id, request.organization)

    # Get pending tokens
    pending_tokens = cycle.tokens.filter(completed_at__isnull=True).order_by('category')

    context = {
        'cycle': cycle,
        'pending_tokens': pending_tokens,
    }

    return render(request, 'admin_dashboard/send_reminder.html', context)


@login_required
def manage_invitations(request, cycle_id):
    """Manage reviewer invitations for a cycle"""
    cycle = get_cycle_or_404(cycle_id, request.organization)

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
        'completed_tokens': completed_tokens,
    }

    return render(request, 'admin_dashboard/manage_invitations.html', context)


@login_required
def assign_invitations(request, cycle_id):
    """Assign email addresses to reviewer tokens (creating tokens dynamically)"""
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    cycle = get_cycle_or_404(cycle_id, request.organization)

    if request.method == 'POST':
        # Parse email assignments by category
        import re
        email_assignments = {}

        for category_code, category_display in ReviewerToken.CATEGORY_CHOICES:
            emails_data = request.POST.get(f'{category_code}_emails', '').strip()
            if emails_data:
                emails = re.split(r'[,\n]+', emails_data)
                validated_emails = []
                for e in emails:
                    e = e.strip()
                    if e:
                        try:
                            validate_email(e)
                            validated_emails.append(e)
                        except ValidationError:
                            messages.warning(request, f'Invalid email skipped in {category_display}: {e}')
                email_assignments[category_code] = validated_emails
            else:
                email_assignments[category_code] = []

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
                for _ in range(needed_count - existing_unassigned):
                    ReviewerToken.objects.create(
                        cycle=cycle,
                        category=category_code
                    )
                    tokens_created += 1

        # Assign tokens to emails with randomization
        stats = assign_tokens_to_emails(cycle, email_assignments)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        # Check if user wants to send invitations immediately
        action = request.POST.get('action', 'assign')
        if action == 'assign' and stats['assigned'] > 0:
            # Send invitations immediately
            send_stats = send_reviewer_invitations(cycle)

            if send_stats['sent'] > 0:
                messages.success(request, f'Successfully invited {stats["assigned"]} reviewer(s) and sent {send_stats["sent"]} email(s).')
            else:
                messages.success(request, f'Successfully assigned {stats["assigned"]} email(s). Invitations will be sent separately.')

            if send_stats['errors']:
                for error in send_stats['errors']:
                    messages.error(request, error)
        elif stats['assigned'] > 0:
            messages.success(request, f'Successfully assigned {stats["assigned"]} email(s). No invitations sent yet.')

        return redirect('review_cycle_detail', cycle_id=cycle.id)

    return redirect('manage_invitations', cycle_id=cycle.id)


@login_required
def send_invitations(request, cycle_id):
    """Send email invitations to assigned reviewers"""
    cycle = get_cycle_or_404(cycle_id, request.organization)

    if request.method == 'POST':
        # Send invitations
        stats = send_reviewer_invitations(cycle)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        if stats['sent'] > 0:
            messages.success(request, f'Successfully sent {stats["sent"]} invitation email(s).')
        elif stats['sent'] == 0 and not stats['errors']:
            messages.info(request, 'No pending invitations to send.')

        return redirect('review_cycle_detail', cycle_id=cycle.id)

    return redirect('review_cycle_detail', cycle_id=cycle.id)


@login_required
def send_reminder(request, cycle_id):
    """Send reminder emails for pending reviews"""
    from reviews.services import send_reminder_emails

    cycle = get_cycle_or_404(cycle_id, request.organization)

    if request.method == 'POST':
        # Send reminders
        stats = send_reminder_emails(cycle)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        if stats['sent'] > 0:
            messages.success(request, f'Successfully sent {stats["sent"]} reminder(s).')
        elif stats['sent'] == 0 and not stats['errors']:
            messages.info(request, 'No pending reminders to send.')

        return redirect('review_cycle_detail', cycle_id=cycle.id)

    return redirect('send_reminder_form', cycle_id=cycle.id)


@login_required
@require_POST
def send_individual_reminder(request, cycle_id, token_id):
    """Send a reminder email to a specific reviewer"""
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.conf import settings

    cycle = get_cycle_or_404(cycle_id, request.organization)

    try:
        # Get the specific token
        token = ReviewerToken.objects.get(id=token_id, cycle=cycle)

        # Check if token has email and invitation was sent
        if not token.reviewer_email:
            messages.error(request, 'Cannot send reminder: no email assigned to this reviewer.')
            return redirect('review_cycle_detail', cycle_id=cycle.id)

        if not token.invitation_sent_at:
            messages.error(request, 'Cannot send reminder: invitation not sent yet.')
            return redirect('review_cycle_detail', cycle_id=cycle.id)

        if token.is_completed:
            messages.info(request, 'This reviewer has already completed their feedback.')
            return redirect('review_cycle_detail', cycle_id=cycle.id)

        # Build feedback URL
        feedback_url = request.build_absolute_uri(
            f'/feedback/{token.token}/'
        )

        # Render email
        context = {
            'reviewee_name': cycle.reviewee.name,
            'questionnaire_name': cycle.questionnaire.name,
            'feedback_url': feedback_url,
            'category': token.get_category_display(),
        }

        html_content = render_to_string('emails/reviewer_reminder.html', context)
        text_content = render_to_string('emails/reviewer_reminder.txt', context)

        # Send email
        from_email = settings.DEFAULT_FROM_EMAIL
        subject = f'Reminder: Feedback Request for {cycle.reviewee.name}'

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[token.reviewer_email]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()

        # Update last reminder sent timestamp
        from django.utils import timezone
        token.last_reminder_sent_at = timezone.now()
        token.save()

        messages.success(request, f'Reminder sent to reviewer.')

    except ReviewerToken.DoesNotExist:
        messages.error(request, 'Reviewer token not found.')
    except Exception as e:
        messages.error(request, f'Error sending reminder: {str(e)}')

    return redirect('review_cycle_detail', cycle_id=cycle.id)


@login_required
@require_POST
def remove_reviewer_token(request, cycle_id, token_id):
    """Remove a reviewer token from a cycle (only if not started)"""
    cycle = get_cycle_or_404(cycle_id, request.organization)

    try:
        # Get the specific token
        token = ReviewerToken.objects.get(id=token_id, cycle=cycle)

        # Only allow deletion if reviewer hasn't started (no claimed_at or completed_at)
        if token.claimed_at or token.completed_at:
            messages.error(request, 'Cannot remove: reviewer has already started or completed their feedback.')
            return redirect('review_cycle_detail', cycle_id=cycle.id)

        # Store info for success message
        category = token.get_category_display()
        email = token.reviewer_email if token.reviewer_email else "unclaimed token"

        # Delete the token
        token.delete()

        messages.success(request, f'Removed {category} reviewer ({email}) from cycle.')

    except ReviewerToken.DoesNotExist:
        messages.error(request, 'Reviewer token not found.')
    except Exception as e:
        messages.error(request, f'Error removing reviewer: {str(e)}')

    return redirect('review_cycle_detail', cycle_id=cycle.id)


@login_required
@require_POST
def send_report_email(request, cycle_id):
    """Send report notification email to reviewee"""
    from reports.services import send_report_ready_notification

    cycle = get_cycle_or_404(cycle_id, request.organization)

    # Check if report exists
    try:
        report = Report.objects.get(cycle=cycle)
    except Report.DoesNotExist:
        messages.error(request, 'No report found for this cycle. Please generate the report first.')
        return redirect('review_cycle_detail', cycle_id=cycle.id)

    # Send notification email
    email_stats = send_report_ready_notification(report, request)

    if email_stats['sent'] > 0:
        messages.success(request, f'Report email sent to {cycle.reviewee.name} at {cycle.reviewee.email}.')
    else:
        if email_stats['errors']:
            for error in email_stats['errors']:
                messages.error(request, f'Failed to send email: {error}')
        else:
            messages.error(request, 'Failed to send email.')

    return redirect('review_cycle_detail', cycle_id=cycle.id)


@login_required
def settings_view(request):
    """Organization and SMTP settings page"""
    # Use the organization from the middleware (set based on user's profile)
    organization = request.organization

    if not organization:
        messages.error(request, 'No organization found. Please run setup first.')
        return redirect('admin_dashboard')

    if request.method == 'POST':
        # Check permission to modify organization settings
        if not request.user.has_perm('accounts.can_manage_organization'):
            messages.error(request, 'You do not have permission to modify organization settings.')
            return redirect('settings')
        # Update organization details
        organization.name = request.POST.get('name', organization.name)
        organization.email = request.POST.get('email', organization.email)

        # Update report settings
        min_responses = request.POST.get('min_responses_for_anonymity', 3)
        try:
            organization.min_responses_for_anonymity = int(min_responses)
        except (ValueError, TypeError):
            organization.min_responses_for_anonymity = 3

        organization.auto_send_report_email = request.POST.get('auto_send_report_email') == 'on'

        # Update registration settings
        organization.allow_registration = request.POST.get('allow_registration') == 'on'
        organization.default_users_can_create_cycles = request.POST.get('default_users_can_create_cycles') == 'on'

        # Update SMTP settings
        organization.smtp_host = request.POST.get('smtp_host', '')
        organization.smtp_port = int(request.POST.get('smtp_port', 587))
        organization.smtp_username = request.POST.get('smtp_username', '')

        # Only update password if provided
        smtp_password = request.POST.get('smtp_password', '')
        if smtp_password:
            organization.smtp_password = smtp_password

        organization.smtp_use_tls = request.POST.get('smtp_use_tls') == 'on'
        organization.from_email = request.POST.get('from_email', organization.from_email)

        try:
            organization.save()
            messages.success(request, 'Settings updated successfully.')
            return redirect('settings')
        except Exception as e:
            messages.error(request, f'Error updating settings: {str(e)}')

    # Get subscription information if exists
    subscription = None
    try:
        from subscriptions.models import Subscription
        subscription = organization.subscription
        print(f"DEBUG: Found subscription for {organization.name}: {subscription.plan.name} - {subscription.status}")
    except (Subscription.DoesNotExist, AttributeError) as e:
        print(f"DEBUG: No subscription for {organization.name}: {type(e).__name__}")
    except Exception as e:
        print(f"DEBUG: Error getting subscription: {type(e).__name__}: {e}")

    print(f"DEBUG: Passing subscription to template: {subscription}")

    # Check if current user has organization admin permission
    is_org_admin = request.user.has_perm('accounts.can_manage_organization')

    # Count total admin users
    from accounts.models import UserProfile
    admin_profiles = UserProfile.objects.for_organization(organization).select_related('user')
    admin_count = sum(1 for p in admin_profiles if p.user.has_perm('accounts.can_manage_organization'))

    context = {
        'organization': organization,
        'subscription': subscription,
        'is_org_admin': is_org_admin,
        'admin_count': admin_count,
        'is_last_admin': is_org_admin and admin_count == 1,
    }

    return render(request, 'admin_dashboard/settings.html', context)


@login_required
def gdpr_management(request):
    """GDPR data management and deletion for organization admins"""
    # Check permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, 'You do not have permission to access GDPR management.')
        return redirect('team_list')

    org = request.organization
    if not org:
        messages.error(request, 'No organization found.')
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
        messages.error(request, 'You do not have permission to delete users.')
        return redirect('gdpr_management')

    org = request.organization
    if not org:
        messages.error(request, 'No organization found.')
        return redirect('admin_dashboard')

    try:
        # Get the user profile to verify organization
        user_profile = get_object_or_404(UserProfile, user_id=user_id, organization=org)
        target_user = user_profile.user

        # Prevent self-deletion
        if target_user.id == request.user.id:
            messages.error(request, 'You cannot delete your own account.')
            return redirect('gdpr_management')

        # Prevent deleting superusers
        if target_user.is_superuser:
            messages.error(request, 'Cannot delete super admin accounts.')
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
            messages.success(request, f'User {result["username"]} has been permanently deleted.')
        else:
            messages.success(request, f'User {result["username"]} has been anonymized.')

    except Exception as e:
        messages.error(request, f'Error deleting user: {str(e)}')

    return HttpResponseRedirect(reverse('gdpr_management') + '?tab=users')


@login_required
@require_POST
def gdpr_delete_reviewee_view(request, reviewee_id):
    """Delete or anonymize a reviewee (GDPR)"""
    # Check permission
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, 'You do not have permission to delete reviewees.')
        return redirect('gdpr_management')

    org = request.organization
    if not org:
        messages.error(request, 'No organization found.')
        return redirect('admin_dashboard')

    try:
        # Get the reviewee to verify organization
        reviewee = get_object_or_404(Reviewee, id=reviewee_id, organization=org)

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
                f'Reviewee {result["name"]} and all associated reviewer emails have been anonymized. '
                f'{result.get("reviewer_emails_anonymized", 0)} reviewer email(s) anonymized.'
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
                    f'Reviewee {result["name"]} has been permanently deleted along with '
                    f'{result["review_cycles_affected"]} review cycle(s) and all associated data.'
                )
            else:
                messages.success(
                    request,
                    f'Reviewee {result["name"]} has been anonymized. '
                    f'{result["review_cycles_affected"]} review cycle(s) preserved.'
                )

    except Exception as e:
        messages.error(request, f'Error deleting reviewee: {str(e)}')

    return redirect('gdpr_management')


# ============================================================================
# PRODUCT REVIEW MANAGEMENT
# ============================================================================

@login_required
def product_review_list(request):
    """List and manage product reviews"""
    from productreviews.models import ProductReview
    from django.db.models import Avg, Count

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
    from productreviews.models import ProductReview
    from datetime import date

    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to create product reviews.')
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
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'admin_dashboard/product_review_form.html', {
                'action': 'Create',
                'review': request.POST,
            })

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError('Rating must be between 1 and 5')
        except (ValueError, TypeError):
            messages.error(request, 'Invalid rating value.')
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

        messages.success(request, f'Product review from "{reviewer_name}" created successfully.')
        return redirect('product_review_detail', review_id=review.id)

    return render(request, 'admin_dashboard/product_review_form.html', {'action': 'Create'})


@login_required
def product_review_detail(request, review_id):
    """View product review details"""
    from productreviews.models import ProductReview

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
    from productreviews.models import ProductReview
    from datetime import date

    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to edit product reviews.')
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
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'admin_dashboard/product_review_form.html', {
                'action': 'Edit',
                'review': review,
            })

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError('Rating must be between 1 and 5')
        except (ValueError, TypeError):
            messages.error(request, 'Invalid rating value.')
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

        messages.success(request, f'Product review updated successfully.')
        return redirect('product_review_detail', review_id=review.id)

    return render(request, 'admin_dashboard/product_review_form.html', {
        'action': 'Edit',
        'review': review,
    })


@login_required
def product_review_delete(request, review_id):
    """Delete (soft delete) a product review"""
    from productreviews.models import ProductReview

    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to delete product reviews.')
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    if request.method == 'POST':
        # Soft delete
        review.is_active = False
        review.save()

        messages.success(request, f'Product review from "{review.reviewer_name}" has been deleted.')
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
    from productreviews.models import ProductReview
    from datetime import date

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
            messages.error(request, 'Please select a rating.')
            return render(request, 'admin_dashboard/quick_product_review.html', {
                'existing_review': existing_review,
            })

        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError('Rating must be between 1 and 5')
        except (ValueError, TypeError):
            messages.error(request, 'Invalid rating value.')
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
        reviewer_name = user.get_full_name() or user.username
        reviewer_email = user.email

        # Create or update review
        if existing_review:
            # Update existing review
            existing_review.rating = rating
            existing_review.review_title = review_title
            existing_review.review_text = review_text
            existing_review.status = 'pending'  # Reset to pending for re-approval
            existing_review.save()
            messages.success(request, 'Your review has been updated and is pending approval. Thank you!')
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
            messages.success(request, 'Thank you for your review! It will be published after approval.')

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
    from productreviews.models import ProductReview
    from datetime import date

    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to approve reviews.')
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    review.status = 'approved'
    if not review.published_date:
        review.published_date = date.today()
    review.save()

    messages.success(request, f'Review from "{review.reviewer_name}" approved successfully.')
    return redirect('product_review_list')


@login_required
@require_POST
def product_review_reject(request, review_id):
    """Quick reject a product review"""
    from productreviews.models import ProductReview

    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to reject reviews.')
        return redirect('product_review_list')

    review = get_object_or_404(
        ProductReview.objects.all(),
        id=review_id
    )

    review.status = 'rejected'
    review.save()

    messages.success(request, f'Review from "{review.reviewer_name}" rejected.')
    return redirect('product_review_list')
