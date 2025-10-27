from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['cycle', 'available', 'generated_at', 'access_count', 'last_accessed', 'token_status']
    list_filter = ['available', 'generated_at', 'last_accessed']
    search_fields = ['cycle__reviewee__name', 'access_token']
    list_select_related = ['cycle', 'cycle__reviewee']
    readonly_fields = ['cycle', 'generated_at', 'created_at', 'updated_at', 'access_token', 'last_accessed', 'access_count', 'token_expiry_status']

    def token_status(self, obj):
        """Display token expiration status with color coding"""
        if not obj.access_token_expires:
            return format_html('<span style="color: gray;">No expiry</span>')

        now = timezone.now()
        if obj.access_token_expires < now:
            return format_html('<span style="color: red; font-weight: bold;">Expired</span>')

        time_left = obj.access_token_expires - now
        if time_left.days < 7:
            return format_html('<span style="color: orange;">Expires in {} days</span>', time_left.days)

        return format_html('<span style="color: green;">Valid ({} days)</span>', time_left.days)

    token_status.short_description = 'Token Status'

    def token_expiry_status(self, obj):
        """Detailed token expiration info for detail view"""
        if not obj.access_token_expires:
            return 'No expiration set'

        now = timezone.now()
        if obj.access_token_expires < now:
            return format_html('<span style="color: red; font-weight: bold;">EXPIRED on {}</span>',
                             obj.access_token_expires.strftime('%Y-%m-%d %H:%M'))

        time_left = obj.access_token_expires - now
        return format_html('<span style="color: green;">Expires on {} ({} days, {} hours remaining)</span>',
                         obj.access_token_expires.strftime('%Y-%m-%d %H:%M'),
                         time_left.days,
                         time_left.seconds // 3600)

    token_expiry_status.short_description = 'Token Expiration'
