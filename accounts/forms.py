from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _, gettext
from accounts.models import UserProfile


class ProfileEditForm(forms.ModelForm):
    """Form for editing user profile information"""

    first_name = forms.CharField(
        label=_('First Name'),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('First name')
        })
    )

    last_name = forms.CharField(
        label=_('Last Name'),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Last name')
        })
    )

    email = forms.EmailField(
        label=_('Email'),
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('Email address')
        })
    )

    # Stored on the profile, not on the user
    language = forms.ChoiceField(
        label=_('Language'),
        required=False,
        help_text=_('Used for the dashboard and for emails to you.'),
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate with current user data
        if self.instance:
            self.fields['first_name'].initial = self.instance.first_name
            self.fields['last_name'].initial = self.instance.last_name
            self.fields['email'].initial = self.instance.email

        self.fields['language'].choices = [('', _('Browser language'))] + list(settings.LANGUAGES)
        profile = getattr(self.instance, 'profile', None)
        if profile:
            self.fields['language'].initial = profile.language

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # Check if email is already taken by another user
        if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(gettext('This email address is already in use.'))
        return email

    def save(self, commit=True):
        user = super().save(commit)
        profile = getattr(user, 'profile', None)

        if commit and profile:
            profile.language = self.cleaned_data['language']
            profile.save(update_fields=['language'])

        return user


class ProfilePasswordForm(PasswordChangeForm):
    """Django's password change form, styled for the profile page"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].label = _('Current password')
        self.fields['new_password2'].label = _('Confirm new password')
        self.fields['new_password2'].help_text = ''
        # A short hint instead of the list of all validator rules; the validators still explain what fails
        self.fields['new_password1'].help_text = _('Use at least 8 characters.')
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
            field.widget.attrs.pop('autofocus', None)
        self.fields['old_password'].widget.attrs['autofocus'] = True


class FreeSignupForm(forms.Form):
    email = forms.EmailField(label=_('Email'), max_length=150)  # the username too: User.username has 150


class ForgotPasswordForm(forms.Form):
    """Form for requesting a password reset"""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _('Enter your email address'),
            'autofocus': True
        })
    )


class ResetPasswordForm(forms.Form):
    """Form for setting a new password"""
    password1 = forms.CharField(
        label=_('New Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('New password'),
            'autofocus': True
        })
    )
    password2 = forms.CharField(
        label=_('Confirm Password'),
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': _('Confirm new password')
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2:
            if password1 != password2:
                raise ValidationError(gettext('Passwords do not match.'))
            try:
                validate_password(password1)
            except ValidationError as e:
                raise ValidationError(e.messages)

        return cleaned_data
