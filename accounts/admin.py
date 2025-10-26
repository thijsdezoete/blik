from django.contrib import admin
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
    list_display = ['email', 'organization', 'invited_by', 'accepted_at', 'expires_at', 'created_at']
    list_filter = ['accepted_at', 'expires_at', 'organization', 'created_at']
    search_fields = ['email', 'token', 'invited_by__username', 'invited_by__email']
    list_select_related = ['organization', 'invited_by']
    raw_id_fields = ['organization', 'invited_by']
    readonly_fields = ['token', 'accepted_at']

    def has_add_permission(self, request):
        # Invitations should be created through the application, not admin
        return False
