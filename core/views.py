from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from .models import Organization
from .forms import SetupAdminForm, SetupOrganizationForm, SetupEmailForm

User = get_user_model()


def is_setup_complete():
    """Check if initial setup has been completed."""
    # Setup is complete if there's at least one superuser and one organization
    has_superuser = User.objects.filter(is_superuser=True).exists()
    has_organization = Organization.objects.exists()
    return has_superuser and has_organization


def setup_welcome(request):
    """Welcome page for the setup wizard."""
    if is_setup_complete():
        return redirect('setup_complete')

    # Skip to admin setup if not complete
    return redirect('setup_admin')


@require_http_methods(['GET', 'POST'])
def setup_admin(request):
    """Step 1: Create the first admin user."""
    if is_setup_complete():
        return redirect('setup_complete')

    if request.method == 'POST':
        form = SetupAdminForm(request.POST)
        if form.is_valid():
            # Create the superuser
            user = User.objects.create_superuser(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password']
            )
            # Log the user in
            login(request, user)
            messages.success(request, f'Admin account "{user.username}" created successfully!')
            return redirect('setup_organization')
    else:
        form = SetupAdminForm()

    return render(request, 'setup/admin.html', {
        'form': form,
        'step': 1,
        'total_steps': 3,
        'progress_percentage': 33,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def setup_organization(request):
    """Step 2: Configure organization details."""
    if Organization.objects.exists():
        return redirect('setup_email')

    if not request.user.is_superuser:
        messages.error(request, 'You must be an administrator to complete setup.')
        return redirect('/')

    if request.method == 'POST':
        form = SetupOrganizationForm(request.POST)
        if form.is_valid():
            organization = form.save(commit=False)
            organization.is_active = True
            organization.save()
            messages.success(request, f'Organization "{organization.name}" created successfully!')
            return redirect('setup_email')
    else:
        form = SetupOrganizationForm()

    return render(request, 'setup/organization.html', {
        'form': form,
        'step': 2,
        'total_steps': 3,
        'progress_percentage': 66,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def setup_email(request):
    """Step 3: Configure email settings."""
    if not request.user.is_superuser:
        messages.error(request, 'You must be an administrator to complete setup.')
        return redirect('/')

    organization = Organization.objects.first()
    if not organization:
        return redirect('setup_organization')

    if request.method == 'POST':
        form = SetupEmailForm(request.POST)
        if form.is_valid():
            if not form.cleaned_data.get('skip_email_setup'):
                # Update organization with email settings
                organization.smtp_host = form.cleaned_data['smtp_host']
                organization.smtp_port = form.cleaned_data['smtp_port']
                organization.smtp_username = form.cleaned_data.get('smtp_username', '')
                organization.smtp_password = form.cleaned_data.get('smtp_password', '')
                organization.smtp_use_tls = form.cleaned_data.get('smtp_use_tls', True)
                organization.from_email = form.cleaned_data['from_email']
                organization.save()
                messages.success(request, 'Email settings configured successfully!')
            else:
                messages.info(request, 'Email setup skipped. You can configure it later in the admin panel.')

            return redirect('setup_complete')
    else:
        # Pre-fill with existing organization data
        initial_data = {
            'smtp_host': organization.smtp_host or '',
            'smtp_port': organization.smtp_port or 587,
            'smtp_username': organization.smtp_username or '',
            'smtp_use_tls': organization.smtp_use_tls,
            'from_email': organization.from_email or organization.email,
        }
        form = SetupEmailForm(initial=initial_data)

    return render(request, 'setup/email.html', {
        'form': form,
        'step': 3,
        'total_steps': 3,
        'progress_percentage': 100,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def setup_complete(request):
    """Final step: Setup completion and next steps."""
    if not is_setup_complete():
        return redirect('setup_welcome')

    organization = Organization.objects.first()

    # Load default questionnaire on first visit
    from questionnaires.models import Questionnaire
    from django.core.management import call_command

    if not Questionnaire.objects.exists():
        try:
            call_command('loaddata', 'professional_skills_questionnaire')
            call_command('loaddata', 'software_engineering_questionnaire')
            messages.success(request, 'Default questionnaires loaded successfully!')
        except Exception as e:
            messages.warning(request, f'Could not load default questionnaires: {e}')

    # Handle test data generation
    if request.method == 'POST' and request.POST.get('generate_test_data'):
        try:
            from accounts.models import Reviewee
            from reviews.models import ReviewCycle, ReviewerToken, Response
            from questionnaires.models import Questionnaire, Question
            from reports.services import generate_report
            from django.utils import timezone
            import uuid
            import random

            # Get both questionnaires
            professional_q = Questionnaire.objects.filter(name__icontains='Professional Skills').first()
            software_q = Questionnaire.objects.filter(name__icontains='Software Engineering').first()

            if not professional_q and not software_q:
                professional_q = Questionnaire.objects.first()

            if not professional_q and not software_q:
                messages.error(request, 'No questionnaire available. Please create one first.')
            else:
                # Create test reviewees with diverse roles
                reviewee1 = Reviewee.objects.create(
                    name='Sarah Johnson',
                    email='sarah.johnson@example.com',
                    department='Engineering',
                    organization=organization
                )
                reviewee2 = Reviewee.objects.create(
                    name='Michael Chen',
                    email='michael.chen@example.com',
                    department='Product',
                    organization=organization
                )
                reviewee3 = Reviewee.objects.create(
                    name='Emily Rodriguez',
                    email='emily.rodriguez@example.com',
                    department='Engineering',
                    organization=organization
                )
                reviewee4 = Reviewee.objects.create(
                    name='David Park',
                    email='david.park@example.com',
                    department='Sales',
                    organization=organization
                )
                reviewee5 = Reviewee.objects.create(
                    name='Lisa Anderson',
                    email='lisa.anderson@example.com',
                    department='Engineering',
                    organization=organization
                )

                def create_completed_cycle(reviewee, questionnaire_to_use, pattern='balanced'):
                    """Helper to create a completed cycle with responses"""
                    cycle = ReviewCycle.objects.create(
                        reviewee=reviewee,
                        questionnaire=questionnaire_to_use,
                        created_by=request.user,
                        status='completed'
                    )

                    # Create tokens and complete them
                    categories = ['self', 'peer', 'peer', 'peer', 'manager', 'direct_report', 'direct_report']
                    tokens = []
                    for category in categories:
                        token = ReviewerToken.objects.create(
                            cycle=cycle,
                            category=category,
                            token=uuid.uuid4(),
                            completed_at=timezone.now(),
                            claimed_at=timezone.now()
                        )
                        tokens.append(token)

                    # Create responses for all questions
                    questions = Question.objects.filter(section__questionnaire=questionnaire_to_use)
                    for token in tokens:
                        for question in questions:
                            if question.question_type == 'rating' or question.question_type == 'likert':
                                # Different patterns for different reviewees
                                if pattern == 'imposter_syndrome':
                                    # Self-ratings much lower than others
                                    if token.category == 'self':
                                        rating = random.randint(2, 3)
                                    else:
                                        rating = random.randint(4, 5)
                                elif pattern == 'overconfident':
                                    # Self-ratings higher than others
                                    if token.category == 'self':
                                        rating = random.randint(4, 5)
                                    else:
                                        rating = random.randint(2, 3)
                                elif pattern == 'high_performer':
                                    # High across the board
                                    rating = random.randint(4, 5)
                                elif pattern == 'needs_development':
                                    # Lower ratings, opportunity for growth
                                    rating = random.randint(2, 3)
                                else:  # balanced
                                    # Varied ratings showing strengths and areas to develop
                                    if token.category == 'self':
                                        rating = random.randint(3, 4)
                                    elif token.category == 'manager':
                                        rating = random.randint(4, 5)
                                    else:
                                        rating = random.randint(3, 5)

                                # For likert questions, map rating to scale item
                                if question.question_type == 'likert':
                                    scale = question.config.get('scale', [])
                                    if scale:
                                        # Map rating (1-5) to scale index (0-based)
                                        scale_index = min(rating - 1, len(scale) - 1)
                                        answer_data = {'value': scale[scale_index]}
                                    else:
                                        answer_data = {'value': rating}
                                else:
                                    answer_data = {'value': rating}
                            elif question.question_type == 'text':
                                # Choose responses based on questionnaire type
                                if 'Software Engineering' in questionnaire_to_use.name:
                                    sample_responses = [
                                        'Strong technical expertise and deep understanding of software architecture.',
                                        'Writes clean, maintainable code and follows best practices consistently.',
                                        'Excellent at debugging complex issues and finding root causes.',
                                        'Demonstrates solid grasp of algorithms and data structures.',
                                        'Could improve on code documentation and knowledge sharing.',
                                        'Always stays current with new technologies and frameworks.',
                                        'Great at technical mentoring and explaining complex concepts.',
                                        'Would benefit from more focus on testing and quality assurance.',
                                        'Strong problem-solving skills and creative technical solutions.',
                                    ]
                                else:  # Professional Skills
                                    sample_responses = [
                                        'Excellent communication and consistently clear in explanations.',
                                        'Strong collaborative skills and always willing to help the team.',
                                        'Great at problem solving and thinking strategically.',
                                        'Demonstrates professionalism and dedication to quality work.',
                                        'Would benefit from taking more initiative on complex projects.',
                                        'Shows strong leadership potential and influences others positively.',
                                        'Builds positive relationships across teams effectively.',
                                        'Adapts well to change and handles uncertainty with grace.',
                                        'Could improve on delegation and trusting team members more.',
                                        'Consistently delivers high-quality results on time.',
                                    ]
                                answer_data = {'value': random.choice(sample_responses)}
                            else:
                                answer_data = {}

                            Response.objects.create(
                                cycle=cycle,
                                question=question,
                                token=token,
                                category=token.category,
                                answer_data=answer_data
                            )

                    # Generate report
                    generate_report(cycle)
                    return cycle

                # Cycle 1: Software Engineer - Completed (imposter syndrome pattern)
                if software_q:
                    create_completed_cycle(reviewee1, software_q, 'imposter_syndrome')

                # Cycle 2: Product Manager - Active with partial completion
                if professional_q:
                    cycle2 = ReviewCycle.objects.create(
                        reviewee=reviewee2,
                        questionnaire=professional_q,
                        created_by=request.user,
                        status='active'
                    )
                    ReviewerToken.objects.create(cycle=cycle2, category='self', token=uuid.uuid4(), claimed_at=timezone.now())
                    ReviewerToken.objects.create(cycle=cycle2, category='peer', token=uuid.uuid4())
                    token_completed = ReviewerToken.objects.create(cycle=cycle2, category='manager', token=uuid.uuid4(), claimed_at=timezone.now())
                    token_completed.completed_at = timezone.now()
                    token_completed.save()

                # Cycle 3: Engineering Manager - Completed (high performer)
                if software_q:
                    create_completed_cycle(reviewee3, software_q, 'high_performer')

                # Cycle 4: Sales Director - Completed (balanced professional skills)
                if professional_q:
                    create_completed_cycle(reviewee4, professional_q, 'balanced')

                # Cycle 5: Junior Developer - Active, no completion yet
                if software_q:
                    cycle5 = ReviewCycle.objects.create(
                        reviewee=reviewee5,
                        questionnaire=software_q,
                        created_by=request.user,
                        status='active'
                    )
                    ReviewerToken.objects.create(cycle=cycle5, category='self', token=uuid.uuid4())
                    ReviewerToken.objects.create(cycle=cycle5, category='peer', token=uuid.uuid4())
                    ReviewerToken.objects.create(cycle=cycle5, category='peer', token=uuid.uuid4())
                    ReviewerToken.objects.create(cycle=cycle5, category='manager', token=uuid.uuid4())

                messages.success(request, 'Test data generated successfully! 5 reviewees with diverse roles and both questionnaires. Check the dashboard to explore completed reports and active cycles.')
        except Exception as e:
            messages.error(request, f'Failed to generate test data: {e}')

        return redirect('admin_dashboard')

    return render(request, 'setup/complete.html', {
        'organization': organization,
        'user': request.user,
    })
