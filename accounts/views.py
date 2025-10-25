from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from core.models import Organization
from accounts.models import UserProfile

User = get_user_model()


@require_http_methods(["GET"])
def login_view(request):
    """User login view - shows registration link if enabled."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    # Check if registration is enabled
    registration_enabled = Organization.objects.filter(
        allow_registration=True,
        is_active=True
    ).exists()

    return render(request, 'accounts/login.html', {
        'registration_enabled': registration_enabled
    })


@require_http_methods(["GET"])
def register_view(request):
    """User registration view - redirects to allauth signup."""
    if request.user.is_authenticated:
        return redirect('admin_dashboard')

    # Get the first active organization (for now - until we implement proper multitenancy)
    organization = Organization.objects.filter(
        allow_registration=True,
        is_active=True
    ).first()

    if not organization:
        messages.warning(request, 'Registration is currently disabled.')
        return redirect('login')

    return render(request, 'accounts/register.html', {
        'organization': organization
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
        'organization': profile.organization
    }
    return render(request, 'accounts/profile.html', context)
