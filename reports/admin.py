from django.contrib import admin
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['cycle', 'available', 'generated_at']
    list_filter = ['available', 'generated_at']
    search_fields = ['cycle__reviewee__name']
    list_select_related = ['cycle', 'cycle__reviewee']
    readonly_fields = ['cycle', 'generated_at', 'created_at', 'updated_at']
