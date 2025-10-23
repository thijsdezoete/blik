from django.contrib import admin
from django.contrib import messages
from .models import ReviewCycle, ReviewerToken, Response


class ReviewerTokenInline(admin.TabularInline):
    model = ReviewerToken
    extra = 1
    readonly_fields = ['token', 'completed_at']
    fields = ['category', 'token', 'completed_at']


def send_feedback_invitations(modeladmin, request, queryset):
    """Admin action to send feedback invitation emails"""
    from notifications.utils import send_feedback_invitation

    sent_count = 0
    error_count = 0

    for token in queryset:
        # For MVP, we'll need admin to manually specify email or we skip
        # In production, you'd have a reviewer email field
        try:
            # This is a placeholder - admin would need to manually send
            # or we'd need to add email field to ReviewerToken
            messages.warning(
                request,
                f"Token {token.token} generated. Copy feedback URL and send to reviewer manually: "
                f"http://localhost:8000/feedback/{token.token}/"
            )
            sent_count += 1
        except Exception as e:
            error_count += 1
            messages.error(request, f"Error with token {token.token}: {str(e)}")

    if sent_count > 0:
        messages.success(request, f"Generated {sent_count} feedback URLs. Copy and send manually.")

send_feedback_invitations.short_description = "Generate feedback URLs for selected tokens"


@admin.register(ReviewCycle)
class ReviewCycleAdmin(admin.ModelAdmin):
    list_display = ['reviewee', 'questionnaire', 'status', 'created_by', 'created_at', 'view_report_link']
    list_filter = ['status', 'created_at']
    search_fields = ['reviewee__name', 'reviewee__email']
    list_select_related = ['reviewee', 'questionnaire', 'created_by']
    inlines = [ReviewerTokenInline]
    readonly_fields = ['created_at', 'updated_at']

    def view_report_link(self, obj):
        from django.utils.html import format_html
        from django.urls import reverse
        url = reverse('reports:view_report', args=[obj.id])
        return format_html('<a href="{}" target="_blank">View Report</a>', url)
    view_report_link.short_description = 'Report'


@admin.register(ReviewerToken)
class ReviewerTokenAdmin(admin.ModelAdmin):
    list_display = ['cycle', 'category', 'token', 'completed_at', 'created_at']
    list_filter = ['category', 'completed_at', 'created_at']
    search_fields = ['token', 'cycle__reviewee__name']
    list_select_related = ['cycle', 'cycle__reviewee']
    readonly_fields = ['token', 'created_at', 'updated_at']
    actions = [send_feedback_invitations]


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ['cycle', 'question_short', 'category', 'created_at']
    list_filter = ['category', 'created_at']
    search_fields = ['cycle__reviewee__name', 'question__question_text']
    list_select_related = ['cycle', 'cycle__reviewee', 'question', 'token']
    readonly_fields = ['created_at', 'updated_at']

    def question_short(self, obj):
        return obj.question.question_text[:50] + '...' if len(obj.question.question_text) > 50 else obj.question.question_text
    question_short.short_description = 'Question'
