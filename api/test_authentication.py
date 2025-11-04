"""
Tests for API token authentication.
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from accounts.models import Organization, User, Reviewee
from api.models import APIToken


class APITokenAuthenticationTest(TestCase):
    """Test API token authentication."""

    def setUp(self):
        """Set up test data."""
        # Create organization
        self.org = Organization.objects.create(
            name='Test Org',
            slug='test-org'
        )

        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        # Create API token
        self.token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Token'
        )

        self.client = APIClient()

    def test_valid_token_authentication(self):
        """Valid token should authenticate successfully."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 200)

    def test_invalid_token(self):
        """Invalid token should return 401."""
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token-12345')
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Invalid or inactive token', str(response.data))

    def test_missing_authorization_header(self):
        """Missing Authorization header should return 401."""
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 401)

    def test_malformed_authorization_header(self):
        """Malformed Authorization header should return 401."""
        # Missing 'Bearer' prefix
        self.client.credentials(HTTP_AUTHORIZATION=self.token.token)
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 401)

        # Wrong prefix
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.token}')
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 401)

    def test_inactive_token(self):
        """Inactive token should return 401."""
        self.token.is_active = False
        self.token.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Invalid or inactive token', str(response.data))

    def test_expired_token(self):
        """Expired token should return 401."""
        self.token.expires_at = timezone.now() - timedelta(days=1)
        self.token.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('Token has expired', str(response.data))

    def test_token_not_yet_expired(self):
        """Token with future expiration should work."""
        self.token.expires_at = timezone.now() + timedelta(days=30)
        self.token.save()

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 200)

    def test_last_used_at_updated(self):
        """Token usage should update last_used_at."""
        self.assertIsNone(self.token.last_used_at)

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')
        self.client.get('/api/v1/reviewees/')

        # Refresh token from database
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_organization_isolation(self):
        """Token should only access its own organization data."""
        # Create another organization
        other_org = Organization.objects.create(
            name='Other Org',
            slug='other-org'
        )

        # Create reviewee in other org
        other_reviewee = Reviewee.objects.create(
            organization=other_org,
            name='Other Reviewee',
            email='other@example.com'
        )

        # Try to access other org's reviewee
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')
        response = self.client.get(f'/api/v1/reviewees/{other_reviewee.id}/')

        # Should return 404 (not 403) to avoid leaking existence
        self.assertEqual(response.status_code, 404)

    def test_organization_set_on_request(self):
        """Token authentication should set request.organization."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')

        # Create a reviewee in our org
        reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='reviewee@example.com'
        )

        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 200)

        # Should only see reviewees from our org
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['email'], 'reviewee@example.com')


class SessionAuthenticationTest(TestCase):
    """Test session authentication (for browsable API)."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(
            name='Test Org',
            slug='test-org'
        )

        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        self.client = APIClient()

    def test_session_authentication(self):
        """Session authentication should work for logged-in users."""
        # Login
        self.client.login(username='testuser', password='testpass123')

        # Should be able to access API
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 200)

    def test_session_without_organization(self):
        """User without organization should be denied."""
        # Create user without org
        user_no_org = User.objects.create_user(
            username='noorg',
            email='noorg@example.com',
            password='testpass123'
        )

        self.client.login(username='noorg', password='testpass123')
        response = self.client.get('/api/v1/reviewees/')

        # Should be denied (no organization context)
        self.assertEqual(response.status_code, 403)
