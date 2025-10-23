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
            call_command('loaddata', 'default_questionnaire')
            messages.success(request, 'Default 360 questionnaire loaded successfully!')
        except Exception as e:
            messages.warning(request, f'Could not load default questionnaire: {e}')

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

            # Get default questionnaire
            questionnaire = Questionnaire.objects.filter(is_default=True).first()
            if not questionnaire:
                questionnaire = Questionnaire.objects.first()

            if not questionnaire:
                messages.error(request, 'No questionnaire available. Please create one first.')
            else:
                # Create test reviewees
                reviewee1 = Reviewee.objects.create(
                    name='Jane Smith',
                    email='jane.smith@example.com',
                    department='Engineering',
                    organization=organization
                )
                reviewee2 = Reviewee.objects.create(
                    name='John Doe',
                    email='john.doe@example.com',
                    department='Product',
                    organization=organization
                )
                reviewee3 = Reviewee.objects.create(
                    name='Sarah Johnson',
                    email='sarah.johnson@example.com',
                    department='Engineering',
                    organization=organization
                )

                # Cycle 1: Active cycle with partial completion (Jane Smith)
                cycle1 = ReviewCycle.objects.create(
                    reviewee=reviewee1,
                    questionnaire=questionnaire,
                    created_by=request.user,
                    status='active'
                )
                ReviewerToken.objects.create(cycle=cycle1, category='self', token=uuid.uuid4())
                ReviewerToken.objects.create(cycle=cycle1, category='peer', token=uuid.uuid4())
                token_completed = ReviewerToken.objects.create(cycle=cycle1, category='manager', token=uuid.uuid4())
                token_completed.completed_at = timezone.now()
                token_completed.save()

                # Cycle 2: Active cycle with no completion (John Doe)
                cycle2 = ReviewCycle.objects.create(
                    reviewee=reviewee2,
                    questionnaire=questionnaire,
                    created_by=request.user,
                    status='active'
                )
                ReviewerToken.objects.create(cycle=cycle2, category='self', token=uuid.uuid4())
                ReviewerToken.objects.create(cycle=cycle2, category='peer', token=uuid.uuid4())
                ReviewerToken.objects.create(cycle=cycle2, category='peer', token=uuid.uuid4())
                ReviewerToken.objects.create(cycle=cycle2, category='direct_report', token=uuid.uuid4())

                # Cycle 3: Completed cycle with full responses and report (Sarah Johnson)
                cycle3 = ReviewCycle.objects.create(
                    reviewee=reviewee3,
                    questionnaire=questionnaire,
                    created_by=request.user,
                    status='completed'
                )

                # Create tokens and complete them
                categories = ['self', 'peer', 'peer', 'peer', 'manager', 'direct_report', 'direct_report']
                tokens = []
                for category in categories:
                    token = ReviewerToken.objects.create(
                        cycle=cycle3,
                        category=category,
                        token=uuid.uuid4(),
                        completed_at=timezone.now()
                    )
                    tokens.append(token)

                # Create responses for all questions in all tokens
                questions = Question.objects.filter(section__questionnaire=questionnaire)
                for token in tokens:
                    for question in questions:
                        if question.question_type == 'rating':
                            # Vary ratings by category for interesting perception gaps
                            if token.category == 'self':
                                # Self-ratings slightly lower (imposter syndrome pattern)
                                rating = random.randint(3, 4)
                            elif token.category == 'manager':
                                # Manager ratings higher
                                rating = random.randint(4, 5)
                            else:
                                # Peer/direct report ratings in middle
                                rating = random.randint(3, 5)
                            answer_data = {'value': rating}
                        elif question.question_type == 'text':
                            # Sample text responses
                            sample_responses = [
                                'Excellent communication and leadership skills.',
                                'Strong technical expertise and always willing to help team members.',
                                'Great at problem solving and thinking outside the box.',
                                'Demonstrates consistent professionalism and dedication.',
                                'Would benefit from more delegation to develop team members.',
                            ]
                            answer_data = {'value': random.choice(sample_responses)}
                        else:
                            answer_data = {}

                        Response.objects.create(
                            cycle=cycle3,
                            question=question,
                            token=token,
                            category=token.category,
                            answer_data=answer_data
                        )

                # Generate report for completed cycle
                generate_report(cycle3)

                messages.success(request, 'Test data generated successfully! Check the dashboard to explore the system with various cycle states.')
        except Exception as e:
            messages.error(request, f'Failed to generate test data: {e}')

        return redirect('admin_dashboard')

    return render(request, 'setup/complete.html', {
        'organization': organization,
        'user': request.user,
    })
