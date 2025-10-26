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
    # Setup is complete if there's at least one user with a profile and one organization
    from accounts.models import UserProfile
    has_user_with_profile = UserProfile.objects.exists()
    has_organization = Organization.objects.exists()
    return has_user_with_profile and has_organization


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
            # Create regular user (not superuser)
            user = User.objects.create_user(
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
    # Check if user already has an organization (e.g., from Stripe signup)
    organization = None
    if hasattr(request.user, 'profile') and request.user.profile.organization:
        organization = request.user.profile.organization

    if request.method == 'POST':
        if organization:
            # Update existing organization
            form = SetupOrganizationForm(request.POST, instance=organization)
        else:
            # Create new organization
            form = SetupOrganizationForm(request.POST)

        if form.is_valid():
            organization = form.save(commit=False)
            organization.is_active = True
            organization.save()

            # Create UserProfile for the setup admin if needed
            from accounts.models import UserProfile
            if not hasattr(request.user, 'profile'):
                UserProfile.objects.create(
                    user=request.user,
                    organization=organization,
                    can_create_cycles_for_others=True
                )

            messages.success(request, f'Organization "{organization.name}" configured successfully!')
            return redirect('setup_email')
    else:
        # Pre-fill form with existing organization data if available
        if organization:
            form = SetupOrganizationForm(instance=organization)
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
    organization = request.organization
    if not organization:
        messages.error(request, 'No organization found. Please complete organization setup first.')
        return redirect('setup_organization')

    # Check if user has a SaaS subscription
    from subscriptions.models import Subscription
    has_subscription = Subscription.objects.filter(organization=organization).exists()

    if request.method == 'POST':
        form = SetupEmailForm(request.POST)

        # Auto-skip for SaaS customers if they choose to use Blik mailer
        use_blik_mailer = request.POST.get('use_blik_mailer') == 'true'

        if use_blik_mailer and has_subscription:
            # Use default Blik email settings (already configured in Django settings)
            messages.success(request, 'Using Blik\'s managed email service. All set!')
            return redirect('setup_complete')

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
        'has_subscription': has_subscription,
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

    # Use the organization from the user's profile
    organization = request.organization
    if not organization:
        messages.error(request, 'No organization found. Please run setup first.')
        return redirect('setup_welcome')

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
            from io import StringIO

            # Call the management command to generate demo data for this organization
            out = StringIO()
            call_command(
                'generate_demo_data',
                '--reviewees', '15',
                '--organization', str(organization.id),
                stdout=out
            )

            # Show success message
            messages.success(request, 'Demo data generated successfully! Created 15 reviewees with diverse review cycles in various states. Check the dashboard to explore.')
        except Exception as e:
            messages.error(request, f'Failed to generate demo data: {e}')

        return redirect('admin_dashboard')

    return render(request, 'setup/complete.html', {
        'organization': organization,
        'user': request.user,
    })
