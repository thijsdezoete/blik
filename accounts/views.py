from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from core.models import Organization
from accounts.models import UserProfile, OrganizationInvitation, PasswordResetToken
from accounts.services import create_user_with_email_as_username
from accounts.forms import ForgotPasswordForm, ResetPasswordForm


@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def login_view(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    if request.method == 'POST':
        # The template uses 'login' as the field name (your modification)
        username = request.POST.get('login')
        password = request.POST.get('password')

        # Try authenticating with username first, then email
        user = authenticate(request, username=username, password=password)

        if user is None:
            # Try email-based login
            from django.contrib.auth.models import User
            try:
                user_obj = User.objects.get(email=username)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass

        if user is not None:
            login(request, user)
            return redirect('admin_dashboard')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'accounts/login.html')


@require_http_methods(["GET"])
def register_view(request):
    """
    User registration view - disabled.
    Users must register via signup page or invitation.
    """
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    messages.warning(
        request,
        'Please use the signup page to create an account.'
    )
    return redirect('login')


@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def signup_view(request):
    """
    Signup view for invited users.
    Creates account and links to organization from invitation.
    """
    from django.contrib.auth.models import User

    # Check if there's an invitation in session
    invitation_token = request.session.get('invitation_token')
    invitation_email = request.session.get('invitation_email')

    if not invitation_token:
        messages.error(request, 'Invalid signup link. Please use your invitation email.')
        return redirect('login')

    # Get the invitation
    try:
        invitation = OrganizationInvitation.objects.get(token=invitation_token)
        if not invitation.is_valid():
            messages.error(request, 'This invitation has expired.')
            return redirect('login')
    except OrganizationInvitation.DoesNotExist:
        messages.error(request, 'Invalid invitation.')
        return redirect('login')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        # Validate
        if email != invitation.email.lower():
            messages.error(request, f'You must use the invited email: {invitation.email}')
            return render(request, 'accounts/register.html', {
                'organization': invitation.organization,
                'invitation_email': invitation.email
            })

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'accounts/register.html', {
                'organization': invitation.organization,
                'invitation_email': invitation.email
            })

        # Use Django's built-in password validators
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        try:
            validate_password(password1, user=None)
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)
            return render(request, 'accounts/register.html', {
                'organization': invitation.organization,
                'invitation_email': invitation.email
            })

        # Create user using centralized function
        try:
            user, _ = create_user_with_email_as_username(email=email, password=password1)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('login')

        # Create user profile
        UserProfile.objects.create(
            user=user,
            organization=invitation.organization,
            can_create_cycles_for_others=invitation.organization.default_users_can_create_cycles
        )

        # Assign organization member permissions (Django permission system)
        from accounts.permissions import assign_organization_member
        assign_organization_member(
            user,
            can_create_cycles_for_others=invitation.organization.default_users_can_create_cycles
        )

        # Mark invitation as accepted
        invitation.accepted_at = timezone.now()
        invitation.save()

        # Send welcome email
        try:
            from core.email import send_welcome_email
            send_welcome_email(user, invitation.organization)
        except Exception as e:
            print(f"Failed to send welcome email to {user.email}: {e}")

        # Clear session
        del request.session['invitation_token']
        del request.session['invitation_email']

        # Log the user in
        from django.contrib.auth import login
        # Specify the backend explicitly since we have multiple auth backends
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)

        messages.success(request, f'Welcome to {invitation.organization.name}!')
        return redirect('admin_dashboard')

    # GET request - show form
    return render(request, 'accounts/register.html', {
        'organization': invitation.organization,
        'invitation_email': invitation.email
    })


@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='5/h', method='POST', block=True)
def forgot_password_view(request):
    """Handle forgot password requests."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].lower()

            # Try to find user by email
            try:
                user = User.objects.get(email=email)
                # Create password reset token
                token = PasswordResetToken.objects.create(user=user)

                # Send reset email
                try:
                    from core.email import send_password_reset_email
                    send_password_reset_email(user, token)
                except Exception as e:
                    print(f"Failed to send password reset email to {email}: {e}")
            except User.DoesNotExist:
                # Don't reveal if email exists - security best practice
                pass

            # Always show success message to prevent email enumeration
            messages.success(
                request,
                'If an account with that email exists, we\'ve sent password reset instructions.'
            )
            return redirect('login')
    else:
        form = ForgotPasswordForm()

    return render(request, 'accounts/forgot_password.html', {'form': form})


@require_http_methods(["GET", "POST"])
def reset_password_view(request, token):
    """Handle password reset with token."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    # Validate token
    try:
        reset_token = PasswordResetToken.objects.get(token=token)
    except PasswordResetToken.DoesNotExist:
        messages.error(request, 'Invalid or expired password reset link.')
        return redirect('login')

    if not reset_token.is_valid():
        messages.error(request, 'This password reset link has expired. Please request a new one.')
        return redirect('forgot_password')

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            # Update user password
            user = reset_token.user
            user.set_password(form.cleaned_data['password1'])
            user.save()

            # Mark token as used
            reset_token.used_at = timezone.now()
            reset_token.save()

            messages.success(request, 'Your password has been reset successfully. Please log in.')
            return redirect('login')
        else:
            # Show form errors
            for error in form.non_field_errors():
                messages.error(request, error)
    else:
        form = ResetPasswordForm()

    return render(request, 'accounts/reset_password.html', {'form': form, 'token': token})


@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    """User profile view with editing capabilities and cycle reports."""
    from accounts.forms import ProfileEditForm
    from reviews.models import ReviewCycle
    from reports.models import Report
    from reports.services import get_report_summary

    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        messages.error(request, 'Profile not found. Please contact support.')
        return redirect('admin_dashboard')

    # Handle profile edit form
    if request.method == 'POST':
        form = ProfileEditForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('profile')
    else:
        form = ProfileEditForm(instance=request.user)

    # Get user's review cycles - both as reviewee and as creator
    organization = profile.organization

    # Get cycles for the current user as reviewee
    user_cycles = ReviewCycle.objects.filter(
        reviewee__email=request.user.email,
        reviewee__organization=organization
    ).select_related('reviewee', 'questionnaire', 'created_by').order_by('-created_at')

    # Attach report data to each cycle
    cycles_with_reports = []
    for cycle in user_cycles:
        cycle_data = {
            'cycle': cycle,
            'report': None,
            'summary': None,
            'has_report': False
        }

        try:
            report = Report.objects.get(cycle=cycle)
            cycle_data['report'] = report
            cycle_data['summary'] = get_report_summary(report)
            cycle_data['has_report'] = True
        except Report.DoesNotExist:
            pass

        cycles_with_reports.append(cycle_data)

    context = {
        'user': request.user,
        'profile': profile,
        'organization': organization,
        'form': form,
        'cycles_with_reports': cycles_with_reports,
    }
    return render(request, 'accounts/profile.html', context)
