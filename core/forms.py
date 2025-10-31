from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from .models import Organization

User = get_user_model()


class SetupAdminForm(forms.Form):
    """Form for creating the first admin user during setup."""

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'admin@example.com',
            'autofocus': True
        }),
        help_text='Email address for the administrator'
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••'
        }),
        min_length=8,
        help_text='Password must be at least 8 characters'
    )

    password_confirm = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••'
        }),
        help_text='Enter the same password again for verification'
    )

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('This email is already registered.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('Passwords do not match.')

        return cleaned_data


class SetupOrganizationForm(forms.ModelForm):
    """Form for setting up organization details during setup."""

    class Meta:
        model = Organization
        fields = ['name', 'email']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Acme Corporation',
                'autofocus': True
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'hr@example.com'
            }),
        }
        help_texts = {
            'name': 'Your organization or company name',
            'email': 'Main contact email for your organization',
        }


class SetupEmailForm(forms.Form):
    """Form for configuring SMTP email settings during setup."""

    smtp_host = forms.CharField(
        label='SMTP Host',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'smtp.gmail.com',
            'autofocus': True
        }),
        help_text='Your SMTP server hostname'
    )

    smtp_port = forms.IntegerField(
        label='SMTP Port',
        initial=587,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '587'
        }),
        help_text='Common ports: 587 (TLS), 465 (SSL), 25 (Plain)'
    )

    smtp_username = forms.CharField(
        label='SMTP Username',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'your-email@gmail.com'
        }),
        help_text='Username for SMTP authentication (usually your email)'
    )

    smtp_password = forms.CharField(
        label='SMTP Password',
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••'
        }),
        help_text='Password or app-specific password for SMTP'
    )

    smtp_use_tls = forms.BooleanField(
        label='Use TLS',
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        help_text='Enable TLS encryption (recommended for port 587)'
    )

    from_email = forms.EmailField(
        label='From Email Address',
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'noreply@example.com'
        }),
        help_text='Email address that appears as sender'
    )

    skip_email_setup = forms.BooleanField(
        label='Skip email setup (configure later)',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        help_text='You can configure email settings later in the admin panel'
    )

    def clean(self):
        cleaned_data = super().clean()
        skip_email_setup = cleaned_data.get('skip_email_setup', False)

        # If skipping email setup, don't validate email fields
        if skip_email_setup:
            # Remove errors for required fields
            if 'smtp_host' in self.errors:
                del self.errors['smtp_host']
            if 'smtp_port' in self.errors:
                del self.errors['smtp_port']
            if 'from_email' in self.errors:
                del self.errors['from_email']
            return cleaned_data

        # If not skipping, ensure required fields are present
        if not cleaned_data.get('smtp_host'):
            self.add_error('smtp_host', 'SMTP Host is required when not skipping email setup.')
        if not cleaned_data.get('smtp_port'):
            self.add_error('smtp_port', 'SMTP Port is required when not skipping email setup.')
        if not cleaned_data.get('from_email'):
            self.add_error('from_email', 'From Email is required when not skipping email setup.')

        return cleaned_data


# Login and registration now handled by django-allauth
# Custom forms removed to simplify authentication flow
