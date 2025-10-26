from django.contrib import admin
from .models import Plan, Subscription, OneTimeLoginToken


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
    list_display = ['user', 'used', 'expires_at', 'created_at']
    list_filter = ['used', 'expires_at', 'created_at']
    search_fields = ['user__username', 'user__email', 'token']
    list_select_related = ['user']
    readonly_fields = ['token', 'used', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        # Tokens should be created through the application, not admin
        return False
