"""Account and organization management views."""
import json
import logging

logger = logging.getLogger(__name__)
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.http import Http404, JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as _, gettext_lazy
from accounts.services import (
    export_organization_data,
    delete_user_account,
    delete_organization as delete_organization_service,
)
from accounts.import_service import (
    import_organization_data,
    validate_import_data,
    generate_import_preview
)
from accounts.permissions import (
    can_delete_organization_required,
    can_manage_organization_required,
    login_required,
)
from subscriptions.services import cancel_subscription, reactivate_subscription
from subscriptions.models import Subscription
from subscriptions.utils import can_see_billing
from core.email import send_account_deleted_email
from core.languages import user_language


def _send_deletion_confirmation(email, language, **kwargs):
    """Confirm a deletion. The data is gone already, so a mail failure is only logged."""
    if not email:
        return
    try:
        send_account_deleted_email(email, language, **kwargs)
    except Exception:
        logger.exception('Deletion confirmation email failed')


@login_required
def account_settings(request):
    """The account settings live on the dashboard settings page."""
    return redirect('settings')


@login_required
@require_POST
def cancel_subscription_view(request):
    """Cancel subscription at period end."""
    if not can_see_billing(request.organization, request.user):
        raise Http404
    org = request.organization
    if not org:
        messages.error(request, _('Organization not found.'))
        return redirect('billing')

    try:
        subscription = Subscription.objects.get(organization=org)
        cancel_subscription(subscription)
        messages.success(request, _('Subscription will be canceled at the end of the current billing period.'))
    except Subscription.DoesNotExist:
        messages.error(request, _('No active subscription found.'))
    except Exception as e:
        messages.error(request, _('Error canceling subscription: %(error)s') % {'error': str(e)})

    return redirect('billing')


@login_required
@require_POST
def reactivate_subscription_view(request):
    """Reactivate a subscription that was set to cancel."""
    if not can_see_billing(request.organization, request.user):
        raise Http404
    org = request.organization
    if not org:
        messages.error(request, _('Organization not found.'))
        return redirect('billing')

    try:
        subscription = Subscription.objects.get(organization=org)
        reactivate_subscription(subscription)
        messages.success(request, _('Subscription reactivated successfully.'))
    except Subscription.DoesNotExist:
        messages.error(request, _('No subscription found.'))
    except Exception as e:
        messages.error(request, _('Error reactivating subscription: %(error)s') % {'error': str(e)})

    return redirect('billing')


@login_required
@can_manage_organization_required
def export_data(request):
    """Export all organization data as JSON."""
    org = request.organization
    if not org:
        return JsonResponse({'error': _('Organization not found')}, status=404)

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
        logger.exception('Error exporting data')
        return JsonResponse({'error': _('Export failed. Please try again.')}, status=500)


@login_required(as_json=True)
@can_manage_organization_required(
    as_json=True, message=gettext_lazy('Only organization administrators can import data'))
@require_POST
def preview_import(request):
    """
    Preview import data without actually importing.
    Returns validation results and preview information.
    """
    org = request.organization
    if not org:
        return JsonResponse({'error': _('Organization not found')}, status=404)

    try:
        import_file = request.FILES.get('import_file')
        if not import_file:
            return JsonResponse({'error': _('No file uploaded')}, status=400)

        # Validate file size (max 50MB)
        max_size = 50 * 1024 * 1024
        if import_file.size > max_size:
            return JsonResponse({'error': _('File too large (max %(size)sMB)') % {'size': max_size // (1024*1024)}}, status=400)

        # Validate file type
        if not import_file.name.endswith('.json'):
            return JsonResponse({'error': _('Only JSON files are allowed')}, status=400)

        # Parse JSON
        try:
            data = json.load(import_file)
        except json.JSONDecodeError as e:
            return JsonResponse({'error': _('Invalid JSON format. Please check your file.')}, status=400)

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
        logger.exception('Preview import failed')
        return JsonResponse({'error': _('Preview failed. Please try again.')}, status=500)


@login_required
@require_POST
def import_data(request):
    """
    Import organization data from uploaded JSON file.
    """
    org = request.organization
    if not org:
        messages.error(request, _('Organization not found'))
        return redirect('settings')

    # Check if user is org admin
    if not request.user.has_perm('accounts.can_manage_organization'):
        messages.error(request, _('Only organization administrators can import data'))
        return redirect('settings')

    try:
        import_file = request.FILES.get('import_file')
        if not import_file:
            messages.error(request, _('No file uploaded'))
            return redirect('settings')

        # Validate file size (max 50MB)
        max_size = 50 * 1024 * 1024
        if import_file.size > max_size:
            messages.error(request, _('File too large (max %(size)sMB)') % {'size': max_size // (1024*1024)})
            return redirect('settings')

        # Validate file type
        if not import_file.name.endswith('.json'):
            messages.error(request, _('Only JSON files are allowed'))
            return redirect('settings')

        # Parse JSON
        try:
            data = json.load(import_file)
        except json.JSONDecodeError as e:
            messages.error(request, _('Invalid JSON format: %(error)s') % {'error': str(e)})
            return redirect('settings')

        # Get import options from form
        import_options = {
            'users': request.POST.get('import_users') == 'on',
            'reviewees': request.POST.get('import_reviewees') == 'on',
            'questionnaires': request.POST.get('import_questionnaires') == 'on',
            'cycles': request.POST.get('import_cycles') == 'on',
            'reports': request.POST.get('import_reports') == 'on',
        }

        if (import_options['questionnaires']
                and not request.user.has_perm('accounts.can_manage_questionnaires')):
            messages.error(request, _('You do not have permission to create or edit questionnaires.'))
            return redirect('settings')

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
            messages.success(request, _('Import completed successfully: %(summary)s') % {'summary': result['summary']})

            # Show warnings if any
            if result.get('warnings'):
                for warning in result['warnings'][:5]:  # Show first 5 warnings
                    messages.warning(request, warning)
                if len(result['warnings']) > 5:
                    messages.info(request, _('... and %(count)s more warnings') % {'count': len(result['warnings']) - 5})
        else:
            messages.error(request, _('Import failed'))
            for error in result.get('errors', [])[:3]:  # Show first 3 errors
                messages.error(request, error)

        return redirect('settings')

    except Exception as e:
        messages.error(request, _('Import failed: %(error)s') % {'error': str(e)})
        return redirect('settings')


@login_required
@require_POST
def delete_account(request):
    """Delete user account."""
    user = request.user

    # Confirm with password
    password = request.POST.get('password')
    if not user.check_password(password):
        messages.error(request, _('Invalid password. Account deletion canceled.'))
        return redirect('settings')

    try:
        email, language = user.email, user_language(user)
        delete_user_account(user)
        _send_deletion_confirmation(email, language)
        logout(request)
        return redirect('landing:index')
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('settings')
    except Exception as e:
        messages.error(request, _('Error deleting account: %(error)s') % {'error': str(e)})
        return redirect('settings')


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
        messages.error(request, _('Invalid password. Organization deletion canceled.'))
        return redirect('settings')

    # Confirm with organization name
    org_name = request.POST.get('organization_name')
    if org_name != org.name:
        messages.error(request, _('Organization name does not match. Deletion canceled.'))
        return redirect('settings')

    try:
        # Read what the confirmation needs while the organization still exists
        email, language = user.email, user_language(user)
        had_subscription = Subscription.objects.filter(organization=org).exists()
        delete_organization_service(org)
        _send_deletion_confirmation(email, language, organization_name=org_name,
                                    had_subscription=had_subscription)
        logout(request)
        return redirect('landing:index')
    except Exception as e:
        messages.error(request, _('Error deleting organization: %(error)s') % {'error': str(e)})
        return redirect('settings')


@login_required(as_json=True)
@require_POST
def mark_welcome_seen(request):
    """
    Remember that this user folded "How Blik works" on the dashboard: from now
    on it starts folded for them, on every device. The flag is older than the
    dashboard section; it was the "seen" mark of the welcome modal before.
    """
    try:
        profile = request.user.profile
        profile.has_seen_welcome = True
        profile.save()
        return JsonResponse({'success': True})
    except Exception as e:
        logger.exception('Error marking welcome as seen')
        return JsonResponse({'success': False, 'error': _('Something went wrong.')}, status=500)
