"""Environment-owned settings must be read-only in the admin UI.

setup_organization rewrites env-backed fields on every container start. If the
UI let you edit them, the edit would silently vanish on the next restart — the
confusing half of issue #4. The form disables those inputs, but a disabled
input is cosmetic: the view has to refuse the write too.
"""
import os
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin
from core.env_config import ENV_MANAGED_FIELDS, env_managed_fields
from core.models import Organization
from django.contrib.auth.models import User


def only_env(**overrides):
    """An os.environ with every config var cleared except the given ones.

    The developer's own .env is loaded into os.environ, so a test that does not
    clear these would silently inherit whatever the machine has set.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in set(ENV_MANAGED_FIELDS.values())}
    env.update(overrides)
    return patch.dict(os.environ, env, clear=True)


class EnvManagedFieldsTests(TestCase):
    def test_only_reports_vars_that_are_set_and_non_empty(self):
        with only_env(EMAIL_HOST='smtp.acme.com', EMAIL_PORT=''):
            locked = env_managed_fields()

        self.assertEqual(locked.get('smtp_host'), 'EMAIL_HOST')
        # An empty var hands the field back to the UI without editing compose files.
        self.assertNotIn('smtp_port', locked)

    def test_the_name_is_locked_only_for_the_organization_the_environment_owns(self):
        # setup_organization writes one organization. On a service with more, the others name themselves.
        owned = Organization(pk=1, name='Blik')
        other = Organization(pk=2, name='anna@acme.example')

        with only_env(ORGANIZATION_NAME='Blik', EMAIL_HOST='smtp.acme.example'):
            self.assertIn('name', env_managed_fields(owned))
            self.assertNotIn('name', env_managed_fields(other))
            # Every organization sends through the mail server of the service.
            self.assertIn('smtp_host', env_managed_fields(other))


class SettingsViewEnvLockTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name='Acme', email='org@acme.example',
            smtp_host='smtp.from-env.example', smtp_port=25,
        )
        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)
        self.client.force_login(self.admin)

    def test_env_owned_field_is_not_writable_even_if_posted(self):
        """A disabled input is cosmetic — the view must reject the value."""
        with only_env(EMAIL_HOST='smtp.from-env.example'):
            self.client.post(reverse('settings'), {
                'section': 'email',
                'smtp_host': 'smtp.hand-edited.example',
                'smtp_port': '2525',
                'smtp_username': 'someone',
            })

        self.org.refresh_from_db()
        self.assertEqual(self.org.smtp_host, 'smtp.from-env.example')
        # Fields with no env var stay editable.
        self.assertEqual(self.org.smtp_username, 'someone')
        self.assertEqual(self.org.smtp_port, 2525)

    def test_field_is_editable_when_no_env_var_owns_it(self):
        with only_env():
            self.client.post(reverse('settings'), {
                'section': 'email',
                'smtp_host': 'smtp.hand-edited.example',
                'smtp_port': '587',
            })

        self.org.refresh_from_db()
        self.assertEqual(self.org.smtp_host, 'smtp.hand-edited.example')

    def test_settings_page_marks_locked_fields(self):
        with only_env(EMAIL_HOST='smtp.from-env.example'):
            response = self.client.get(reverse('settings'))

        self.assertEqual(response.context['locked_fields'].get('smtp_host'), 'EMAIL_HOST')
        self.assertContains(response, 'Managed by')

    def test_bad_smtp_port_in_form_does_not_500(self):
        with only_env():
            self.client.post(reverse('settings'), {
                'section': 'email',
                'smtp_port': 'abc',
            })

        self.org.refresh_from_db()
        self.assertEqual(self.org.smtp_port, 587)
