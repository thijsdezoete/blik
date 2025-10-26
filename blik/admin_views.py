"""
Admin dashboard views for Blik
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Q, Max
from django.utils import timezone
from datetime import timedelta

from accounts.models import Reviewee, UserProfile, OrganizationInvitation
from reviews.models import ReviewCycle, ReviewerToken
from reviews.services import assign_tokens_to_emails, send_reviewer_invitations
from questionnaires.models import Questionnaire
from reports.models import Report
from core.models import Organization


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

    context = {
        'total_reviewees': total_reviewees,
        'active_cycles': active_cycles,
        'completed_cycles': completed_cycles,
        'pending_tokens': pending_tokens,
        'recent_cycles': recent_cycles,
        'active_cycles_data': active_cycles_data,
        'completed_cycles_data': completed_cycles_data,
        'subscription_status': subscription_status,
    }

    return render(request, 'admin_dashboard/dashboard.html', context)


@login_required
def team_list(request):
    """Team management - users and invitations"""
    org = request.organization

    if not org:
        messages.error(request, 'No organization found.')
        return redirect('admin_dashboard')

    # Get all users in this organization
    users = UserProfile.objects.filter(
        organization=org
    ).select_related('user').order_by('-user__date_joined')

    # Get pending invitations
    invitations = OrganizationInvitation.objects.filter(
        organization=org,
        accepted_at__isnull=True
    ).order_by('-created_at')

    context = {
        'users': users,
        'invitations': invitations,
    }

    return render(request, 'admin_dashboard/team.html', context)


@login_required
def reviewee_list(request):
    """List and manage reviewees"""
    org = request.organization
    reviewees = Reviewee.objects.for_organization(org).filter(is_active=True).annotate(
        cycle_count=Count('review_cycles')
    ).order_by('name')

    context = {
        'reviewees': reviewees,
    }

    return render(request, 'admin_dashboard/reviewee_list.html', context)


@login_required
def reviewee_create(request):
    """Create a new reviewee"""
    from subscriptions.utils import check_employee_limit

    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        department = request.POST.get('department', '')

        if name and email:
            organization = request.organization or Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please run setup first.')
                return redirect('admin_dashboard')

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
    """Edit an existing reviewee"""
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
    """Soft delete a reviewee"""
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
                    elif question_type == 'multiple_choice':
                        choices_raw = request.POST.get('choices', '')
                        choices = [c.strip() for c in choices_raw.split('\n') if c.strip()]
                        config = {'choices': choices}

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
    cycles_qs = ReviewCycle.objects.select_related(
        'reviewee', 'questionnaire', 'created_by'
    )

    if org:
        cycles_qs = cycles_qs.filter(reviewee__organization=org)

    cycles = cycles_qs.annotate(
        token_count=Count('tokens'),
        completed_count=Count('tokens', filter=Q(tokens__completed_at__isnull=False))
    ).order_by('-created_at')

    context = {
        'cycles': cycles,
    }

    return render(request, 'admin_dashboard/review_cycle_list.html', context)


@login_required
def review_cycle_create(request):
    """Create a new review cycle (single or bulk)"""
    if request.method == 'POST':
        creation_mode = request.POST.get('creation_mode', 'single')
        questionnaire_id = request.POST.get('questionnaire')

        # Get number of tokens for each category
        self_count = int(request.POST.get('self_count', 0))
        peer_count = int(request.POST.get('peer_count', 0))
        manager_count = int(request.POST.get('manager_count', 0))
        direct_report_count = int(request.POST.get('direct_report_count', 0))

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

                    # Create tokens
                    categories = [
                        ('self', self_count),
                        ('peer', peer_count),
                        ('manager', manager_count),
                        ('direct_report', direct_report_count),
                    ]

                    for category, count in categories:
                        for _ in range(count):
                            ReviewerToken.objects.create(
                                cycle=cycle,
                                category=category
                            )

                    created_cycles.append(cycle)

                    # Send notification emails to reviewee
                    from reviews.services import send_reviewee_notifications
                    send_reviewee_notifications(cycle, request)

                total_tokens = sum([
                    self_count + peer_count + manager_count + direct_report_count
                    for _ in created_cycles
                ])

                messages.success(
                    request,
                    f'Created {len(created_cycles)} review cycles for all active reviewees with {total_tokens} total tokens. Notification emails sent.'
                )
                return redirect('review_cycle_list')

            else:
                # Single reviewee mode
                reviewee_id = request.POST.get('reviewee')
                if not reviewee_id:
                    messages.error(request, 'Reviewee is required for single cycle creation.')
                    return redirect('review_cycle_create')

                reviewee = Reviewee.objects.for_organization(org).get(id=reviewee_id)

                # Create review cycle
                cycle = ReviewCycle.objects.create(
                    reviewee=reviewee,
                    questionnaire=questionnaire,
                    created_by=request.user,
                    status='active'
                )

                # Create tokens
                categories = [
                    ('self', self_count),
                    ('peer', peer_count),
                    ('manager', manager_count),
                    ('direct_report', direct_report_count),
                ]

                total_tokens = 0
                for category, count in categories:
                    for _ in range(count):
                        ReviewerToken.objects.create(
                            cycle=cycle,
                            category=category
                        )
                        total_tokens += 1

                # Send notification emails to reviewee
                from reviews.services import send_reviewee_notifications
                email_stats = send_reviewee_notifications(cycle, request)

                success_msg = f'Review cycle created for "{reviewee.name}" with {total_tokens} reviewer tokens.'
                if email_stats['sent'] > 0:
                    success_msg += f' {email_stats["sent"]} notification email(s) sent.'
                if email_stats['errors']:
                    success_msg += f' (Email errors: {", ".join(email_stats["errors"])})'

                messages.success(request, success_msg)
                return redirect('review_cycle_detail', cycle_id=cycle.id)

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
        'can_create_for_others': request.user.is_staff or (hasattr(request.user, 'profile') and request.user.profile.can_create_cycles_for_others),
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
    """Assign email addresses to reviewer tokens"""
    cycle = get_cycle_or_404(cycle_id, request.organization)

    if request.method == 'POST':
        # Parse email assignments by category
        import re
        email_assignments = {}

        for category_code, category_display in ReviewerToken.CATEGORY_CHOICES:
            emails_data = request.POST.get(f'{category_code}_emails', '').strip()
            if emails_data:
                emails = re.split(r'[,\n]+', emails_data)
                email_assignments[category_code] = [e.strip() for e in emails if e.strip()]
            else:
                email_assignments[category_code] = []

        # Assign tokens to emails with randomization
        stats = assign_tokens_to_emails(cycle, email_assignments)

        if stats['errors']:
            for error in stats['errors']:
                messages.error(request, error)

        if stats['assigned'] > 0:
            messages.success(request, f'Successfully assigned {stats["assigned"]} email(s) to reviewer tokens.')

        return redirect('manage_invitations', cycle_id=cycle.id)

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

        return redirect('manage_invitations', cycle_id=cycle.id)

    return redirect('manage_invitations', cycle_id=cycle.id)


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

    # Check if current user is staff (can delete org)
    is_org_admin = request.user.is_staff

    # Count total admin users
    from accounts.models import UserProfile
    admin_count = UserProfile.objects.for_organization(organization).filter(
        user__is_staff=True
    ).count()

    context = {
        'organization': organization,
        'subscription': subscription,
        'is_org_admin': is_org_admin,
        'admin_count': admin_count,
        'is_last_admin': is_org_admin and admin_count == 1,
    }

    return render(request, 'admin_dashboard/settings.html', context)
