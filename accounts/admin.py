from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Reviewee, UserProfile, OrganizationInvitation
from core.gdpr import GDPRDeletionService


@admin.register(Reviewee)
class RevieweeAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'department', 'organization', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization', 'created_at']
    search_fields = ['name', 'email', 'department']
    list_select_related = ['organization']
    actions = [
        'gdpr_soft_delete',
        'gdpr_hard_delete',
        'gdpr_full_anonymization',
        'show_data_summary'
    ]

    @admin.action(description='GDPR: Soft delete (anonymize identifiable data)')
    def gdpr_soft_delete(self, request, queryset):
        """Anonymize reviewee data while preserving structure"""
        count = 0
        for reviewee in queryset:
            try:
                result = GDPRDeletionService.delete_reviewee(
                    reviewee.id,
                    hard_delete=False,
                    performed_by=request.user
                )
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error anonymizing {reviewee.name}: {str(e)}",
                    level=messages.ERROR
                )

        self.message_user(
            request,
            f"Successfully anonymized {count} reviewee(s). Personal data removed, review cycles preserved.",
            level=messages.SUCCESS
        )

    @admin.action(description='GDPR: Hard delete (complete removal with all data)')
    def gdpr_hard_delete(self, request, queryset):
        """Completely delete reviewee and all related data"""
        count = 0
        total_cycles = 0
        for reviewee in queryset:
            try:
                # Get cycle count before deletion
                from reviews.models import ReviewCycle
                cycles = ReviewCycle.objects.filter(reviewee=reviewee).count()
                total_cycles += cycles

                result = GDPRDeletionService.delete_reviewee(
                    reviewee.id,
                    hard_delete=True,
                    performed_by=request.user
                )
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error deleting {reviewee.name}: {str(e)}",
                    level=messages.ERROR
                )

        self.message_user(
            request,
            f"Successfully deleted {count} reviewee(s) and {total_cycles} review cycle(s) with all related data.",
            level=messages.WARNING
        )

    @admin.action(description='GDPR: Full anonymization (reviewee + reviewer emails)')
    def gdpr_full_anonymization(self, request, queryset):
        """Anonymize reviewee and all reviewer emails in their cycles"""
        count = 0
        for reviewee in queryset:
            try:
                result = GDPRDeletionService.delete_reviewee_and_anonymize_reviewer_emails(
                    reviewee.id,
                    performed_by=request.user
                )
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error in full anonymization for {reviewee.name}: {str(e)}",
                    level=messages.ERROR
                )

        self.message_user(
            request,
            f"Successfully fully anonymized {count} reviewee(s) including reviewer emails.",
            level=messages.SUCCESS
        )

    @admin.action(description='Show GDPR data summary')
    def show_data_summary(self, request, queryset):
        """Show summary of data that would be affected"""
        for reviewee in queryset:
            try:
                summary = GDPRDeletionService.get_reviewee_data_summary(reviewee.id)
                self.message_user(
                    request,
                    f"Reviewee {reviewee.name}: {summary['review_cycles']['total']} cycles, "
                    f"{summary['tokens']} tokens, {summary['responses']} responses, "
                    f"{summary['reports']} reports",
                    level=messages.INFO
                )
            except Exception as e:
                self.message_user(
                    request,
                    f"Error getting summary for {reviewee.name}: {str(e)}",
                    level=messages.ERROR
                )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'organization', 'can_create_cycles_for_others', 'created_at', 'updated_at']
    list_filter = ['can_create_cycles_for_others', 'organization', 'created_at']
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name']
    list_select_related = ['user', 'organization']
    raw_id_fields = ['user', 'organization']
    actions = ['gdpr_soft_delete_users', 'gdpr_hard_delete_users', 'show_user_data_summary']

    @admin.action(description='GDPR: Soft delete users (anonymize identifiable data)')
    def gdpr_soft_delete_users(self, request, queryset):
        """Anonymize user data while preserving profile"""
        count = 0
        for profile in queryset:
            try:
                result = GDPRDeletionService.delete_user(
                    profile.user.id,
                    hard_delete=False,
                    performed_by=request.user
                )
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error anonymizing user {profile.user.username}: {str(e)}",
                    level=messages.ERROR
                )

        self.message_user(
            request,
            f"Successfully anonymized {count} user(s). Personal data removed, profiles preserved.",
            level=messages.SUCCESS
        )

    @admin.action(description='GDPR: Hard delete users (complete removal)')
    def gdpr_hard_delete_users(self, request, queryset):
        """Completely delete user and profile"""
        count = 0
        for profile in queryset:
            try:
                result = GDPRDeletionService.delete_user(
                    profile.user.id,
                    hard_delete=True,
                    performed_by=request.user
                )
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error deleting user {profile.user.username}: {str(e)}",
                    level=messages.ERROR
                )

        self.message_user(
            request,
            f"Successfully deleted {count} user(s) and their profiles.",
            level=messages.WARNING
        )

    @admin.action(description='Show GDPR data summary')
    def show_user_data_summary(self, request, queryset):
        """Show summary of user data"""
        for profile in queryset:
            try:
                summary = GDPRDeletionService.get_user_data_summary(profile.user.id)
                self.message_user(
                    request,
                    f"User {profile.user.username}: Created {summary['created_cycles']} review cycles",
                    level=messages.INFO
                )
            except Exception as e:
                self.message_user(
                    request,
                    f"Error getting summary for {profile.user.username}: {str(e)}",
                    level=messages.ERROR
                )


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
