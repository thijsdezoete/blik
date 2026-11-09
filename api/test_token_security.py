"""API tokens are stored hashed, and a token's scopes limit what it can do."""
import hashlib
import importlib

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization

from .models import MAX_RATE_LIMIT, APIToken


class TokenTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

    def token(self, **fields):
        return APIToken.objects.create(organization=self.org, created_by=self.admin, name='T', **fields)

    def client_for(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.raw_token}')
        return client


class TokenStorageTests(TokenTestCase):
    def test_only_the_hash_is_stored(self):
        token = self.token()

        stored = APIToken.objects.get(pk=token.pk)
        self.assertEqual(stored.token, hashlib.sha256(token.raw_token.encode()).hexdigest())
        self.assertEqual(stored.prefix, token.raw_token[:8])

    def test_rate_limit_is_capped(self):
        self.assertEqual(self.token(rate_limit=10**9).rate_limit, MAX_RATE_LIMIT)

    def test_migration_hashes_existing_tokens_so_clients_keep_working(self):
        token = self.token()
        APIToken.objects.filter(pk=token.pk).update(token='legacy-raw-token-value', prefix='')
        migration = importlib.import_module('api.migrations.0005_hash_api_tokens')

        migration.hash_existing_tokens(apps, None)

        token.raw_token = 'legacy-raw-token-value'
        self.assertEqual(self.client_for(token).get('/api/v1/reviewees/').status_code, 200)


class TokenScopeTests(TokenTestCase):
    def test_read_scope_allows_reading(self):
        token = self.token(permissions={'read:reviewees': True})

        self.assertEqual(self.client_for(token).get('/api/v1/reviewees/').status_code, 200)

    def test_read_scope_refuses_writing(self):
        token = self.token(permissions={'read:reviewees': True})

        response = self.client_for(token).post('/api/v1/reviewees/', {'name': 'N', 'email': 'n@acme.example'})

        self.assertEqual(response.status_code, 403)

    def test_scope_for_one_resource_refuses_another(self):
        token = self.token(permissions={'read:reviewees': True})

        self.assertEqual(self.client_for(token).get('/api/v1/reports/').status_code, 403)

    def test_token_without_scopes_keeps_its_creators_rights(self):
        token = self.token()

        self.assertEqual(self.client_for(token).get('/api/v1/reports/').status_code, 200)
