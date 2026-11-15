from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils.translation import gettext as _
from .models import Organization
from .forms import SetupAdminForm, SetupOrganizationForm, SetupEmailForm
from accounts.services import create_user_with_email_as_username
from questionnaires.legacy_config import move_all_texts_out_of_config
from questionnaires.shipped import add_shipped_translations

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
            # Create regular user (organization admin via permissions)
            try:
                user, generated_password = create_user_with_email_as_username(
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password']
                )
            except ValueError as e:
                messages.error(request, _('Failed to create user: %(error)s') % {'error': e})
                return render(request, 'setup/admin.html', {
                    'form': form,
                    'step': 1,
                    'total_steps': 3,
                    'progress_percentage': 33,
                })
            # Log the user in with explicit backend
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, _('Admin account "%(email)s" created successfully!') % {'email': user.email})
            return redirect('setup_organization')
    else:
        form = SetupAdminForm()

    return render(request, 'setup/admin.html', {
        'form': form,
        'step': 1,
        'total_steps': 3,
        'progress_percentage': 33,
    })


def may_run_setup(user):
    """
    The setup pages change the organization. Before the first run no admin
    exists, so any account may use them. After that they are for the people
    who may change the same things in the settings.
    """
    return not is_setup_complete() or user.has_perm('accounts.can_manage_organization')


def _refuse_setup(request):
    messages.error(request, _('You do not have permission to manage organization settings.'))
    return redirect('admin_dashboard')


@login_required
@require_http_methods(['GET', 'POST'])
def setup_organization(request):
    """Step 2: Configure organization details."""
    if not may_run_setup(request.user):
        return _refuse_setup(request)
    # Check if user already has an organization (e.g., from Stripe signup)
    organization = None
    if hasattr(request.user, 'profile') and request.user.profile.organization:
        organization = request.user.profile.organization
    elif not organization:
        # If user has no organization but one exists (e.g., from previous setup attempt),
        # use the first available organization
        organization = Organization.objects.first()

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
            from accounts.permissions import assign_organization_admin

            if not hasattr(request.user, 'profile'):
                UserProfile.objects.create(
                    user=request.user,
                    organization=organization,
                    can_create_cycles_for_others=True
                )

                # Through the group, like every other path that creates an
                # admin. Permissions granted directly here would miss every
                # permission added to the group later on.
                try:
                    assign_organization_admin(request.user)
                except Exception as e:
                    # Log but don't fail setup if permissions aren't available yet
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Could not assign permissions during setup: {e}")

            messages.success(request, _('Organization "%(name)s" configured successfully!') % {'name': organization.name})
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
    if not may_run_setup(request.user):
        return _refuse_setup(request)
    organization = request.organization
    if not organization:
        messages.error(request, _('No organization found. Please complete organization setup first.'))
        return redirect('setup_organization')

    # Managed email is offered to every hosted customer: subscribers and
    # single-round buyers alike, whatever their status or credit balance.
    from subscriptions.utils import is_hosted_customer
    is_hosted = is_hosted_customer(organization)

    if request.method == 'POST':
        form = SetupEmailForm(request.POST)

        # Auto-skip for SaaS customers if they choose to use Blik mailer
        use_blik_mailer = request.POST.get('use_blik_mailer') == 'true'

        if use_blik_mailer and is_hosted:
            # Use default Blik email settings (already configured in Django settings)
            messages.success(request, _("Using Blik's managed email service. All set!"))
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
                messages.success(request, _('Email settings configured successfully!'))
            else:
                messages.info(request, _('Email setup skipped. You can configure it later in the admin panel.'))

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
        'is_hosted': is_hosted,
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
    if not may_run_setup(request.user):
        return _refuse_setup(request)

    # Use the organization from the user's profile
    organization = request.organization
    if not organization:
        messages.error(request, _('No organization found. Please run setup first.'))
        return redirect('setup_welcome')

    # Load default questionnaire on first visit
    from questionnaires.models import Questionnaire
    from django.core.management import call_command

    if not Questionnaire.objects.exists():
        try:
            call_command('loaddata', 'professional_skills_questionnaire')
            call_command('loaddata', 'software_engineering_questionnaire')
            move_all_texts_out_of_config()
            add_shipped_translations()
            messages.success(request, _('Default questionnaires loaded successfully!'))
        except Exception as e:
            messages.warning(request, _('Could not load default questionnaires: %(error)s') % {'error': e})

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
            messages.success(request, _('Demo data generated successfully! Created 15 reviewees with diverse review cycles in various states. Check the dashboard to explore.'))
        except Exception as e:
            messages.error(request, _('Failed to generate demo data: %(error)s') % {'error': e})

        return redirect('admin_dashboard')

    return render(request, 'setup/complete.html', {
        'organization': organization,
        'user': request.user,
    })
