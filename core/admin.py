from django.contrib import admin
from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'email']
    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'email', 'is_active']
        }),
        ('Email Settings', {
            'fields': ['smtp_host', 'smtp_port', 'smtp_username', 'smtp_password', 'smtp_use_tls', 'from_email'],
            'classes': ['collapse']
        }),
    ]


# Note: django-axes models (AccessAttempt, AccessLog, AccessFailureLog) are
# automatically registered by the axes package and available in Django admin
# under the "Axes" section for security monitoring
