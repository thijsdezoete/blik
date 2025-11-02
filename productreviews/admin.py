"""Django admin configuration for Product Reviews"""
from django.contrib import admin
from django.utils.html import format_html
from .models import ProductReview


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    """Admin interface for managing product reviews"""

    list_display = [
        'reviewer_name',
        'reviewer_company',
        'rating_stars',
        'status',
        'verified_customer',
        'featured',
        'published_date',
        'created_at',
    ]

    list_filter = [
        'status',
        'rating',
        'verified_customer',
        'featured',
        'is_active',
        'created_at',
        'published_date',
    ]

    search_fields = [
        'reviewer_name',
        'reviewer_company',
        'reviewer_email',
        'review_title',
        'review_text',
    ]

    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Review Content', {
            'fields': ('rating', 'review_title', 'review_text')
        }),
        ('Reviewer Information', {
            'fields': ('reviewer_name', 'reviewer_title', 'reviewer_company', 'reviewer_email')
        }),
        ('Status & Publishing', {
            'fields': ('status', 'verified_customer', 'is_active', 'featured', 'published_date')
        }),
        ('Organization & Metadata', {
            'fields': ('organization', 'source', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['approve_reviews', 'reject_reviews', 'mark_as_featured']

    def rating_stars(self, obj):
        """Display rating as stars"""
        stars = '★' * obj.rating + '☆' * (5 - obj.rating)
        color = '#FFD700' if obj.rating >= 4 else '#FFA500' if obj.rating >= 3 else '#999'
        return format_html(
            '<span style="color: {}; font-size: 16px;">{}</span>',
            color,
            stars
        )
    rating_stars.short_description = 'Rating'

    def approve_reviews(self, request, queryset):
        """Bulk approve reviews"""
        updated = queryset.update(status='approved')
        self.message_user(request, f'{updated} review(s) approved.')
    approve_reviews.short_description = 'Approve selected reviews'

    def reject_reviews(self, request, queryset):
        """Bulk reject reviews"""
        updated = queryset.update(status='rejected')
        self.message_user(request, f'{updated} review(s) rejected.')
    reject_reviews.short_description = 'Reject selected reviews'

    def mark_as_featured(self, request, queryset):
        """Bulk mark as featured"""
        updated = queryset.update(featured=True)
        self.message_user(request, f'{updated} review(s) marked as featured.')
    mark_as_featured.short_description = 'Mark as featured'
