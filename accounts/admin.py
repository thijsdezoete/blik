from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Reviewee, UserProfile, OrganizationInvitation


@admin.register(Reviewee)
class RevieweeAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'department', 'organization', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization', 'created_at']
    search_fields = ['name', 'email', 'department']
    list_select_related = ['organization']


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'can_create_cycles_for_others', 'created_at', 'updated_at']
    list_filter = ['can_create_cycles_for_others', 'organization', 'created_at']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
    list_select_related = ['user', 'organization']
    raw_id_fields = ['user', 'organization']


@admin.register(OrganizationInvitation)
class OrganizationInvitationAdmin(admin.ModelAdmin):
    list_display = ['email', 'organization', 'invited_by', 'accepted_at', 'invitation_status', 'created_at']
    list_filter = ['accepted_at', 'expires_at', 'organization', 'created_at']
    search_fields = ['email', 'token', 'invited_by__username', 'invited_by__email']
    list_select_related = ['organization', 'invited_by']
    raw_id_fields = ['organization', 'invited_by']
    readonly_fields = ['token', 'accepted_at', 'invitation_expiry_status']

    def invitation_status(self, obj):
        """Display invitation status with color coding"""
        if obj.accepted_at:
            return format_html('<span style="color: green; font-weight: bold;">Accepted</span>')

        now = timezone.now()
        if obj.expires_at < now:
            return format_html('<span style="color: red; font-weight: bold;">Expired</span>')

        time_left = obj.expires_at - now
        if time_left.days < 1:
            return format_html('<span style="color: orange;">Expires in {} hours</span>', time_left.seconds // 3600)

        return format_html('<span style="color: blue;">Pending ({} days)</span>', time_left.days)

    invitation_status.short_description = 'Status'

    def invitation_expiry_status(self, obj):
        """Detailed invitation expiration info"""
        if obj.accepted_at:
            return format_html('<span style="color: green;">Accepted on {}</span>',
                             obj.accepted_at.strftime('%Y-%m-%d %H:%M'))

        now = timezone.now()
        if obj.expires_at < now:
            return format_html('<span style="color: red; font-weight: bold;">EXPIRED on {}</span>',
                             obj.expires_at.strftime('%Y-%m-%d %H:%M'))

        time_left = obj.expires_at - now
        return format_html('<span style="color: blue;">Expires on {} ({} days, {} hours remaining)</span>',
                         obj.expires_at.strftime('%Y-%m-%d %H:%M'),
                         time_left.days,
                         time_left.seconds // 3600)

    invitation_expiry_status.short_description = 'Invitation Expiration'

    def has_add_permission(self, request):
        # Invitations should be created through the application, not admin
        return False
