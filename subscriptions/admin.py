from django.contrib import admin
from .models import Plan, Subscription


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
