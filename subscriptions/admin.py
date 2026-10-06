from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Plan, Subscription, OneTimeLoginToken, CheckoutFulfilment, RoundPurchase


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'plan_type', 'price_monthly', 'max_employees', 'is_active']
    list_filter = ['plan_type', 'is_active']
    search_fields = ['name']


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['organization', 'plan', 'status', 'current_period_end', 'created_at']
    list_filter = ['status', 'plan']
    search_fields = ['organization__name', 'stripe_customer_id', 'stripe_subscription_id']
    readonly_fields = ['stripe_customer_id', 'stripe_subscription_id', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'


@admin.register(OneTimeLoginToken)
class OneTimeLoginTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'token_status', 'expires_at', 'created_at']
    list_filter = ['used', 'expires_at', 'created_at']
    search_fields = ['user__username', 'user__email', 'token']
    list_select_related = ['user']
    readonly_fields = ['token', 'used', 'created_at', 'updated_at', 'token_expiry_status']
    date_hierarchy = 'created_at'

    def token_status(self, obj):
        """Display token status with color coding"""
        if obj.used:
            return format_html('<span style="color: gray;">Used</span>')

        now = timezone.now()
        if obj.expires_at < now:
            return format_html('<span style="color: red; font-weight: bold;">Expired</span>')

        time_left = obj.expires_at - now
        if time_left.seconds < 3600:  # Less than 1 hour
            return format_html('<span style="color: orange;">Expires in {} min</span>', time_left.seconds // 60)

        if time_left.days < 1:
            return format_html('<span style="color: orange;">Expires in {} hours</span>', time_left.seconds // 3600)

        return format_html('<span style="color: green;">Valid</span>')

    token_status.short_description = 'Status'

    def token_expiry_status(self, obj):
        """Detailed token expiration info"""
        if obj.used:
            return format_html('<span style="color: gray;">Token was used and is no longer valid</span>')

        now = timezone.now()
        if obj.expires_at < now:
            return format_html('<span style="color: red; font-weight: bold;">EXPIRED on {}</span>',
                             obj.expires_at.strftime('%Y-%m-%d %H:%M'))

        time_left = obj.expires_at - now
        if time_left.days < 1:
            return format_html('<span style="color: orange;">Expires on {} ({} hours, {} minutes remaining)</span>',
                             obj.expires_at.strftime('%Y-%m-%d %H:%M'),
                             time_left.seconds // 3600,
                             (time_left.seconds % 3600) // 60)

        return format_html('<span style="color: green;">Expires on {} ({} days remaining)</span>',
                         obj.expires_at.strftime('%Y-%m-%d %H:%M'),
                         time_left.days)

    token_expiry_status.short_description = 'Token Expiration'

    def has_add_permission(self, request):
        # Tokens should be created through the application, not admin
        return False


@admin.register(RoundPurchase)
class RoundPurchaseAdmin(admin.ModelAdmin):
    list_display = ['organization', 'cycles_remaining', 'fulfilment', 'created_at']
    search_fields = ['organization__name', 'fulfilment__stripe_session_id']
    readonly_fields = ['fulfilment', 'created_at', 'updated_at']

    def has_delete_permission(self, request, obj=None):
        # Deleting an organization's last purchase would turn it into an
        # unlimited self-hosted organization. Refund by setting the balance to 0.
        return False


@admin.register(CheckoutFulfilment)
class CheckoutFulfilmentAdmin(admin.ModelAdmin):
    list_display = ['stripe_session_id', 'outcome', 'organization', 'user', 'user_created', 'created_at']
    list_filter = ['outcome', 'user_created']
    search_fields = ['stripe_session_id', 'organization__name', 'user__email']
    readonly_fields = ['stripe_session_id', 'outcome', 'organization', 'user', 'user_created', 'created_at', 'updated_at']

    # The row is the idempotency key: deleting one makes its paid session fulfillable again.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
