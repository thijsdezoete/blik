"""Tests for the `setup_organization` management command.

The command runs on every container start. It must bootstrap the
Organization row on first run, and on subsequent runs it must not
silently overwrite fields that the user has edited through the admin UI.
"""
import os
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import Organization


CONFIG_ENV_VARS = (
    'ORGANIZATION_NAME',
    'DEFAULT_FROM_EMAIL',
    'EMAIL_HOST',
    'EMAIL_PORT',
    'EMAIL_HOST_USER',
    'EMAIL_HOST_PASSWORD',
    'EMAIL_USE_TLS',
)


class SetupOrganizationCommandTests(TestCase):
    def setUp(self):
        # Each test starts with a known-empty environment for the keys the
        # command reads. Anything we pop is restored on tearDown.
        self._saved_env = {
            key: os.environ.pop(key, None) for key in CONFIG_ENV_VARS
        }

    def tearDown(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _run(self, **env):
        with patch.dict(os.environ, env, clear=False):
            call_command('setup_organization', verbosity=0)

    def test_first_run_creates_organization_from_env(self):
        self._run(ORGANIZATION_NAME='Acme Corp')

        org = Organization.objects.get(id=1)
        self.assertEqual(org.name, 'Acme Corp')

    def test_subsequent_run_preserves_admin_edits_when_env_unset(self):
        self._run(ORGANIZATION_NAME='Acme Corp')
        org = Organization.objects.get(id=1)
        org.name = 'Edited in admin'
        org.smtp_host = 'smtp.acme.example.com'
        org.save(update_fields=['name', 'smtp_host'])

        self._run()

        org.refresh_from_db()
        self.assertEqual(org.name, 'Edited in admin')
        self.assertEqual(org.smtp_host, 'smtp.acme.example.com')

    def test_explicit_env_var_updates_only_its_field(self):
        self._run(ORGANIZATION_NAME='Acme Corp')
        org = Organization.objects.get(id=1)
        org.smtp_host = 'smtp.acme.example.com'
        org.save(update_fields=['smtp_host'])

        self._run(ORGANIZATION_NAME='Rebrand Corp')

        org.refresh_from_db()
        self.assertEqual(org.name, 'Rebrand Corp')
        self.assertEqual(
            org.smtp_host, 'smtp.acme.example.com',
            'Unset env vars must not touch their fields',
        )

    def test_invalid_email_port_falls_back_instead_of_crashing(self):
        """A typo in EMAIL_PORT must not take the container down on boot."""
        self._run(EMAIL_PORT='abc')

        org = Organization.objects.get(id=1)
        self.assertEqual(org.smtp_port, 587)

    def test_invalid_email_port_on_subsequent_run_keeps_container_up(self):
        self._run(EMAIL_PORT='2525')

        self._run(EMAIL_PORT='not-a-port')

        org = Organization.objects.get(id=1)
        self.assertEqual(org.smtp_port, 587)

    def test_subsequent_run_with_smtp_password_env_saves(self):
        """smtp_password is a property over smtp_password_encrypted; naming
        the property in update_fields raised ValueError and crash-looped
        the container on every start (prod outage 2026-10-06)."""
        self._run(ORGANIZATION_NAME='Acme Corp')

        self._run(EMAIL_HOST_PASSWORD='s3cret')

        org = Organization.objects.get(id=1)
        self.assertEqual(org.smtp_password, 's3cret')
