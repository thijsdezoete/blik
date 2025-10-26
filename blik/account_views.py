"""Account and organization management views."""
import json
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from accounts.services import export_organization_data, delete_user_account, delete_organization
from subscriptions.services import cancel_subscription, reactivate_subscription
from subscriptions.models import Subscription


@login_required
def account_settings(request):
    """Account and organization settings page."""
    org = request.organization
    user = request.user

    # Get subscription if exists
    subscription = None
    if org:
        try:
            subscription = Subscription.objects.get(organization=org)
        except Subscription.DoesNotExist:
            pass

    context = {
        'organization': org,
        'subscription': subscription,
    }

    return render(request, 'account/settings.html', context)


@login_required
@require_POST
def cancel_subscription_view(request):
    """Cancel subscription at period end."""
    org = request.organization
    if not org:
        messages.error(request, 'Organization not found.')
        return redirect('account_settings')

    try:
        subscription = Subscription.objects.get(organization=org)
        cancel_subscription(subscription)
        messages.success(request, 'Subscription will be canceled at the end of the current billing period.')
    except Subscription.DoesNotExist:
        messages.error(request, 'No active subscription found.')
    except Exception as e:
        messages.error(request, f'Error canceling subscription: {str(e)}')

    return redirect('account_settings')


@login_required
@require_POST
def reactivate_subscription_view(request):
    """Reactivate a subscription that was set to cancel."""
    org = request.organization
    if not org:
        messages.error(request, 'Organization not found.')
        return redirect('account_settings')

    try:
        subscription = Subscription.objects.get(organization=org)
        reactivate_subscription(subscription)
        messages.success(request, 'Subscription reactivated successfully.')
    except Subscription.DoesNotExist:
        messages.error(request, 'No subscription found.')
    except Exception as e:
        messages.error(request, f'Error reactivating subscription: {str(e)}')

    return redirect('account_settings')


@login_required
def export_data(request):
    """Export all organization data as JSON."""
    org = request.organization
    if not org:
        return JsonResponse({'error': 'Organization not found'}, status=404)

    try:
        data = export_organization_data(org)

        # Create downloadable JSON response
        response = HttpResponse(
            json.dumps(data, indent=2, ensure_ascii=False),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename="{org.name}_data_export.json"'

        return response

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def delete_account(request):
    """Delete user account."""
    user = request.user

    # Confirm with password
    password = request.POST.get('password')
    if not user.check_password(password):
        messages.error(request, 'Invalid password. Account deletion canceled.')
        return redirect('account_settings')

    try:
        delete_user_account(user)
        logout(request)
        messages.success(request, 'Your account has been deleted.')
        return redirect('landing:home')
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('account_settings')
    except Exception as e:
        messages.error(request, f'Error deleting account: {str(e)}')
        return redirect('account_settings')


@login_required
@require_POST
def delete_organization(request):
    """Delete organization and all data."""
    org = request.organization
    user = request.user

    # Only allow staff users to delete organization
    if not user.is_staff:
        messages.error(request, 'Only administrators can delete the organization.')
        return redirect('account_settings')

    # Confirm with password
    password = request.POST.get('password')
    if not user.check_password(password):
        messages.error(request, 'Invalid password. Organization deletion canceled.')
        return redirect('account_settings')

    # Confirm with organization name
    org_name = request.POST.get('organization_name')
    if org_name != org.name:
        messages.error(request, 'Organization name does not match. Deletion canceled.')
        return redirect('account_settings')

    try:
        from accounts.services import delete_organization as delete_org_service
        delete_org_service(org)
        logout(request)
        messages.success(request, 'Organization and all data have been deleted.')
        return redirect('landing:home')
    except Exception as e:
        messages.error(request, f'Error deleting organization: {str(e)}')
        return redirect('account_settings')
