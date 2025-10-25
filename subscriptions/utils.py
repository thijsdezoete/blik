from django.contrib import messages
from accounts.models import Reviewee
from .models import Subscription


def check_employee_limit(request):
    """Check if organization can add more employees based on subscription plan"""
    if not hasattr(request, 'organization') or not request.organization:
        return True  # No organization context, allow (single-tenant mode)

    try:
        subscription = Subscription.objects.get(organization=request.organization)

        if not subscription.is_active:
            return False, "Your subscription is not active. Please update your payment information."

        # Count active reviewees
        active_reviewees = Reviewee.objects.filter(
            organization=request.organization,
            is_active=True
        ).count()

        if active_reviewees >= subscription.plan.max_employees:
            return False, f"You've reached your plan limit of {subscription.plan.max_employees} employees. Please upgrade your plan."

        return True, None

    except Subscription.DoesNotExist:
        # No subscription found - allow in single-tenant/self-hosted mode
        return True, None


def get_subscription_status(organization):
    """Get subscription status and usage information"""
    try:
        subscription = Subscription.objects.select_related('plan').get(organization=organization)

        active_reviewees = Reviewee.objects.filter(
            organization=organization,
            is_active=True
        ).count()

        return {
            'has_subscription': True,
            'is_active': subscription.is_active,
            'is_past_due': subscription.is_past_due,
            'plan_name': subscription.plan.name,
            'max_employees': subscription.plan.max_employees,
            'current_employees': active_reviewees,
            'employees_remaining': subscription.plan.max_employees - active_reviewees,
            'current_period_end': subscription.current_period_end,
        }
    except Subscription.DoesNotExist:
        return {
            'has_subscription': False,
            'is_active': True,  # Assume active in self-hosted mode
            'is_past_due': False,
        }
