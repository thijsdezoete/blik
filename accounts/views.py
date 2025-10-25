from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from core.models import Organization
from accounts.models import UserProfile, OrganizationInvitation


@require_http_methods(["GET", "POST"])
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

        if not password1 or len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
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

        # Check if user already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, 'An account with this email already exists. Please login.')
            return redirect('login')

        # Create user
        username = email.split('@')[0]
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password1
        )

        # Create user profile
        UserProfile.objects.create(
            user=user,
            organization=invitation.organization,
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
        login(request, user)

        messages.success(request, f'Welcome to {invitation.organization.name}!')
        return redirect('admin_dashboard')

    # GET request - show form
    return render(request, 'accounts/register.html', {
        'organization': invitation.organization,
        'invitation_email': invitation.email
    })


@login_required
def profile_view(request):
    """User profile view."""
    try:
        profile = request.user.profile
    except UserProfile.DoesNotExist:
        messages.error(request, 'Profile not found. Please contact support.')
        return redirect('admin_dashboard')

    context = {
        'user': request.user,
        'profile': profile,
        'organization': profile.organization,
    }
    return render(request, 'accounts/profile.html', context)
