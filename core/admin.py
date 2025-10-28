from django.contrib import admin
from django import forms
from .models import Organization, WelcomeEmailFact


class OrganizationAdminForm(forms.ModelForm):
    """Custom form for Organization admin with password handling"""
    smtp_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Enter a new SMTP password or leave blank to keep the existing one'
    )

    class Meta:
        model = Organization
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing organization with a password, show a placeholder
        if self.instance.pk and self.instance.smtp_password_encrypted:
            self.fields['smtp_password'].widget.attrs['placeholder'] = '••••••••'

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Only update the password if a new one was provided
        smtp_password = self.cleaned_data.get('smtp_password')
        if smtp_password:
            instance.set_smtp_password(smtp_password)
        if commit:
            instance.save()
        return instance


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    form = OrganizationAdminForm
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


@admin.register(WelcomeEmailFact)
class WelcomeEmailFactAdmin(admin.ModelAdmin):
    list_display = ['title', 'is_active', 'display_order', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['title', 'content']
    list_editable = ['is_active', 'display_order']
    ordering = ['display_order', 'created_at']


# Note: django-axes models (AccessAttempt, AccessLog, AccessFailureLog) are
# automatically registered by the axes package and available in Django admin
# under the "Axes" section for security monitoring
