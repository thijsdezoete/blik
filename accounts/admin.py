from django.contrib import admin
from .models import Reviewee


@admin.register(Reviewee)
class RevieweeAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'department', 'organization', 'is_active', 'created_at']
    list_filter = ['is_active', 'organization', 'created_at']
    search_fields = ['name', 'email', 'department']
    list_select_related = ['organization']
