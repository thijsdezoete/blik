from django.contrib import messages
from django.contrib.auth import login, authenticate, get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from core.forms import LoginForm, RegistrationForm
from core.models import Organization
from core.email import send_welcome_email
from accounts.models import UserProfile

User = get_user_model()


@require_http_methods(["GET", "POST"])
def login_view(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {username}!')
                next_url = request.GET.get('next', 'admin_dashboard')
                return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()

    # Check if registration is enabled
    registration_enabled = Organization.objects.filter(
        allow_registration=True,
        is_active=True
    ).exists()

    return render(request, 'accounts/login.html', {
        'form': form,
        'registration_enabled': registration_enabled
    })


@require_http_methods(["GET", "POST"])
def register_view(request):
    """User registration view."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    # Check if any organization allows registration
    has_registration_enabled = Organization.objects.filter(
        allow_registration=True,
        is_active=True
    ).exists()

    if not has_registration_enabled and not request.user.is_superuser:
        messages.warning(request, 'Registration is currently disabled.')
        return redirect('login')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            # Create organization
            org_name = form.cleaned_data['organization_name']
            user_email = form.cleaned_data['email']

            # Check if organization exists
            org, created = Organization.objects.get_or_create(
                name=org_name,
                defaults={
                    'email': user_email,
                    'allow_registration': True,
                }
            )

            # If organization exists but doesn't allow registration, deny
            if not created and not org.allow_registration:
                messages.error(
                    request,
                    'This organization does not allow new registrations.'
                )
                return render(request, 'accounts/register.html', {'form': form})

            # Create user
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password']
            )

            # Create user profile
            UserProfile.objects.create(
                user=user,
                organization=org,
                can_create_cycles_for_others=org.default_users_can_create_cycles
            )

            # Log the user in
            login(request, user)

            # Send welcome email
            try:
                send_welcome_email(user, org)
            except Exception as e:
                # Don't fail registration if email fails
                messages.warning(
                    request,
                    'Account created but welcome email could not be sent.'
                )
                print(f"Failed to send welcome email: {e}")

            messages.success(
                request,
                f'Welcome! Your account has been created successfully.'
            )
            return redirect('admin_dashboard')
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


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
        'organization': profile.organization
    }
    return render(request, 'accounts/profile.html', context)
