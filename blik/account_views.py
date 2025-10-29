"""Account and organization management views."""
import json
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_http_methods
from accounts.services import export_organization_data, delete_user_account, delete_organization
from accounts.import_service import (
    import_organization_data,
    validate_import_data,
    generate_import_preview
)
from accounts.permissions import can_delete_organization_required
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
def preview_import(request):
    """
    Preview import data without actually importing.
    Returns validation results and preview information.
    """
    org = request.organization
    if not org:
        return JsonResponse({'error': 'Organization not found'}, status=404)

    # Check if user is org admin
    if not request.user.has_perm('accounts.can_manage_organization'):
        return JsonResponse({'error': 'Only organization administrators can import data'}, status=403)

    try:
        import_file = request.FILES.get('import_file')
        if not import_file:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        # Validate file size (max 50MB)
        max_size = 50 * 1024 * 1024
        if import_file.size > max_size:
            return JsonResponse({'error': f'File too large (max {max_size // (1024*1024)}MB)'}, status=400)

        # Validate file type
        if not import_file.name.endswith('.json'):
            return JsonResponse({'error': 'Only JSON files are allowed'}, status=400)

        # Parse JSON
        try:
            data = json.load(import_file)
        except json.JSONDecodeError as e:
            return JsonResponse({'error': f'Invalid JSON format: {str(e)}'}, status=400)

        # Validate structure
        validation = validate_import_data(data)
        if not validation['valid']:
            return JsonResponse({
                'valid': False,
                'errors': validation['errors'],
                'warnings': validation.get('warnings', [])
            })

        # Generate preview
        preview = generate_import_preview(data)

        return JsonResponse({
            'valid': True,
            'errors': [],
            'warnings': validation.get('warnings', []),
            'preview': preview
        })

    except Exception as e:
        return JsonResponse({'error': f'Preview failed: {str(e)}'}, status=500)


@login_required
@require_POST
def import_data(request):
    """
    Import organization data from uploaded JSON file.
    """
    org = request.organization
    if not org:
        messages.error(request, 'Organization not found')
        return redirect('settings')

    # Check if user is org admin
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, 'Only organization administrators can import data')
        return redirect('settings')

    try:
        import_file = request.FILES.get('import_file')
        if not import_file:
            messages.error(request, 'No file uploaded')
            return redirect('settings')

        # Validate file size (max 50MB)
        max_size = 50 * 1024 * 1024
        if import_file.size > max_size:
            messages.error(request, f'File too large (max {max_size // (1024*1024)}MB)')
            return redirect('settings')

        # Validate file type
        if not import_file.name.endswith('.json'):
            messages.error(request, 'Only JSON files are allowed')
            return redirect('settings')

        # Parse JSON
        try:
            data = json.load(import_file)
        except json.JSONDecodeError as e:
            messages.error(request, f'Invalid JSON format: {str(e)}')
            return redirect('settings')

        # Get import options from form
        import_options = {
            'users': request.POST.get('import_users') == 'on',
            'reviewees': request.POST.get('import_reviewees') == 'on',
            'questionnaires': request.POST.get('import_questionnaires') == 'on',
            'cycles': request.POST.get('import_cycles') == 'on',
            'reports': request.POST.get('import_reports') == 'on',
        }

        # Get conflict resolution mode
        conflict_resolution = request.POST.get('conflict_resolution', 'skip')

        # Perform import
        result = import_organization_data(
            organization=org,
            data=data,
            mode='merge',
            conflict_resolution=conflict_resolution,
            import_options=import_options,
            importing_user=request.user
        )

        if result['success']:
            messages.success(request, f'Import completed successfully: {result["summary"]}')

            # Show warnings if any
            if result.get('warnings'):
                for warning in result['warnings'][:5]:  # Show first 5 warnings
                    messages.warning(request, warning)
                if len(result['warnings']) > 5:
                    messages.info(request, f'... and {len(result["warnings"]) - 5} more warnings')
        else:
            messages.error(request, 'Import failed')
            for error in result.get('errors', [])[:3]:  # Show first 3 errors
                messages.error(request, error)

        return redirect('settings')

    except Exception as e:
        messages.error(request, f'Import failed: {str(e)}')
        return redirect('settings')


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
@can_delete_organization_required
def delete_organization(request):
    """
    Delete organization and all data.

    Only organization administrators can delete the organization.
    Requires password confirmation and organization name match.
    """
    org = request.organization
    user = request.user

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


@login_required
@require_POST
def mark_welcome_seen(request):
    """Mark the welcome modal as seen for the current user."""
    try:
        profile = request.user.profile
        profile.has_seen_welcome = True
        profile.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
