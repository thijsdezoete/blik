"""API access (`can_use_api`) is a per-user permission that no group carries.

It shows the API parts of the interface. The token views in
blik/admin_views.py need it on top of `can_manage_organization`, and
migration accounts.0013 grants it to the admins of the organizations that
already have a token.
"""
import importlib

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import (
    assign_organization_admin,
    assign_organization_member,
    ensure_permission_groups,
    set_user_permission,
)
from api.models import APIToken
from core.models import Organization


class ApiAccessTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.admin = self._user('admin', self.org, admin=True)
        self.member = self._user('member', self.org)

    def _user(self, username, org, admin=False):
        user = User.objects.create_user(
            username=username, email=f'{username}@acme.example', password='pw')
        UserProfile.objects.create(user=user, organization=org)
        if admin:
            assign_organization_admin(user)
        else:
            assign_organization_member(user)
        return user

    def _has_direct_grant(self, user):
        return user.user_permissions.filter(codename='can_use_api').exists()


class TokenViewAccessTests(ApiAccessTestCase):
    def setUp(self):
        super().setUp()
        self.token = APIToken.objects.create(organization=self.org, name='Reporting')

    def test_admin_without_api_access_cannot_create_a_token(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('create_api_token'), {'name': 'New'})

        self.assertFalse(APIToken.objects.filter(name='New').exists())

    def test_admin_without_api_access_cannot_change_a_token(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('update_api_token', args=[self.token.id]),
                         {'name': 'Changed', 'rate_limit': 500})

        self.token.refresh_from_db()
        self.assertEqual(self.token.name, 'Reporting')
        self.assertTrue(self.token.is_active)

    def test_admin_without_api_access_cannot_revoke_a_token(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('delete_api_token', args=[self.token.id]))

        self.assertTrue(APIToken.objects.filter(pk=self.token.pk).exists())

    def test_admin_with_api_access_manages_tokens(self):
        set_user_permission(self.admin, 'can_use_api', True)
        self.client.force_login(self.admin)

        self.client.post(reverse('create_api_token'), {'name': 'New'})
        self.client.post(reverse('delete_api_token', args=[self.token.id]))

        self.assertTrue(APIToken.objects.filter(name='New').exists())
        self.assertFalse(APIToken.objects.filter(pk=self.token.pk).exists())

    def test_api_access_alone_does_not_manage_tokens(self):
        """A member with API access is still not an admin."""
        set_user_permission(self.member, 'can_use_api', True)
        self.client.force_login(self.member)

        self.client.post(reverse('create_api_token'), {'name': 'New'})
        self.client.post(reverse('delete_api_token', args=[self.token.id]))

        self.assertFalse(APIToken.objects.filter(name='New').exists())
        self.assertTrue(APIToken.objects.filter(pk=self.token.pk).exists())


class GrantToAdminsWithTokensTests(ApiAccessTestCase):
    """Migration accounts.0013: nobody who uses the API loses the API parts."""

    def _migrate(self):
        migration = importlib.import_module('accounts.migrations.0013_add_use_api_permission')
        migration.grant_to_admins_with_tokens(apps, None)

    def test_admins_of_an_organization_with_a_token_get_api_access(self):
        APIToken.objects.create(organization=self.org, name='Reporting')

        self._migrate()

        self.assertTrue(self._has_direct_grant(self.admin))
        self.assertFalse(self._has_direct_grant(self.member))

    def test_an_inactive_token_counts(self):
        APIToken.objects.create(organization=self.org, name='Reporting', is_active=False)

        self._migrate()

        self.assertTrue(self._has_direct_grant(self.admin))

    def test_admin_with_the_old_direct_grant_gets_api_access(self):
        """The old setup page and import made admins without the admin group."""
        APIToken.objects.create(organization=self.org, name='Reporting')
        first_user = User.objects.create_user(
            username='first', email='first@acme.example', password='pw')
        UserProfile.objects.create(user=first_user, organization=self.org)
        set_user_permission(first_user, 'can_manage_organization', True)

        self._migrate()

        self.assertTrue(self._has_direct_grant(first_user))

    def test_organization_without_a_token_gets_nothing(self):
        other_org = Organization.objects.create(name='Other company', email='org@other.example')
        other_admin = self._user('other-admin', other_org, admin=True)
        APIToken.objects.create(organization=other_org, name='Reporting')

        self._migrate()

        self.assertTrue(self._has_direct_grant(other_admin))
        self.assertFalse(self._has_direct_grant(self.admin))
