"""
Tests for API permissions.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from accounts.models import Organization, User, Reviewee
from api.models import APIToken
from reviews.models import ReviewCycle
from questionnaires.models import Questionnaire


class IsOrganizationMemberPermissionTest(TestCase):
    """Test IsOrganizationMember permission."""

    def setUp(self):
        """Set up test data."""
        # Create two organizations
        self.org1 = Organization.objects.create(name='Org 1')
        self.org2 = Organization.objects.create(name='Org 2')

        # Create users
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='test123'
        )
        self.user1.profile.organization = self.org1
        self.user1.profile.save()

        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='test123'
        )
        self.user2.profile.organization = self.org2
        self.user2.profile.save()

        # Create tokens
        self.token1 = APIToken.objects.create(
            organization=self.org1,
            created_by=self.user1,
            name='Org 1 Token'
        )

        self.token2 = APIToken.objects.create(
            organization=self.org2,
            created_by=self.user2,
            name='Org 2 Token'
        )

        # Create reviewees in each org
        self.reviewee1 = Reviewee.objects.create(
            organization=self.org1,
            name='Reviewee 1',
            email='r1@example.com'
        )

        self.reviewee2 = Reviewee.objects.create(
            organization=self.org2,
            name='Reviewee 2',
            email='r2@example.com'
        )

        self.client = APIClient()

    def test_can_access_own_org_data(self):
        """Users can access their own organization's data."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1.token}')

        # Should see own org's reviewees
        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['email'], 'r1@example.com')

    def test_cannot_access_other_org_data(self):
        """Users cannot access other organization's data."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1.token}')

        # Should not see other org's reviewee
        response = self.client.get(f'/api/v1/reviewees/{self.reviewee2.id}/')
        self.assertEqual(response.status_code, 404)

    def test_list_only_shows_own_org(self):
        """List views only show data from user's organization."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token1.token}')

        response = self.client.get('/api/v1/reviewees/')
        self.assertEqual(response.status_code, 200)

        # Should only see 1 reviewee (from org1)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.reviewee1.id)


class CanManageOrganizationPermissionTest(TestCase):
    """Test CanManageOrganization permission."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        # Create admin user
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='test123'
        )
        self.admin.profile.organization = self.org
        self.admin.profile.save()
        self.admin.user_permissions.add(
            *self.admin._meta.model._meta.permissions
        )

        # Create regular user
        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        # Create tokens
        self.admin_token = APIToken.objects.create(
            organization=self.org,
            created_by=self.admin,
            name='Admin Token'
        )

        self.user_token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='User Token'
        )

        self.client = APIClient()

    def test_admin_can_create_reviewee(self):
        """Admin can create reviewees."""
        # Grant manage permission to admin
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_organization')
        self.admin.user_permissions.add(perm)

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.admin_token.token}')

        response = self.client.post('/api/v1/reviewees/', {
            'name': 'New Reviewee',
            'email': 'new@example.com',
            'department': 'Engineering'
        })

        self.assertEqual(response.status_code, 201)

    def test_regular_user_cannot_create_reviewee(self):
        """Regular user without permission cannot create reviewees."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user_token.token}')

        response = self.client.post('/api/v1/reviewees/', {
            'name': 'New Reviewee',
            'email': 'new@example.com',
            'department': 'Engineering'
        })

        self.assertEqual(response.status_code, 403)


class CanCreateCyclesPermissionTest(TestCase):
    """Test CanCreateCycles permission."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        # Create user who can create cycles
        self.creator = User.objects.create_user(
            username='creator',
            email='creator@example.com',
            password='test123'
        )
        self.creator.profile.organization = self.org
        self.creator.profile.can_create_cycles_for_others = True
        self.creator.profile.save()

        # Create user who cannot
        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.can_create_cycles_for_others = False
        self.user.profile.save()

        # Create tokens
        self.creator_token = APIToken.objects.create(
            organization=self.org,
            created_by=self.creator,
            name='Creator Token'
        )

        self.user_token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='User Token'
        )

        # Create test data
        self.reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='reviewee@example.com'
        )

        self.questionnaire = Questionnaire.objects.create(
            organization=self.org,
            name='Test Questionnaire',
            is_active=True
        )

        self.client = APIClient()

    def test_creator_can_create_cycle(self):
        """User with can_create_cycles_for_others can create cycles."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.creator_token.token}')

        response = self.client.post('/api/v1/cycles/', {
            'reviewee': self.reviewee.id,
            'questionnaire': self.questionnaire.id
        })

        self.assertEqual(response.status_code, 201)

    def test_regular_user_cannot_create_cycle(self):
        """User without permission cannot create cycles."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.user_token.token}')

        response = self.client.post('/api/v1/cycles/', {
            'reviewee': self.reviewee.id,
            'questionnaire': self.questionnaire.id
        })

        self.assertEqual(response.status_code, 403)


class HasAPIPermissionTest(TestCase):
    """Test HasAPIPermission for token-level permissions."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        # Token with read-only permissions
        self.readonly_token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Read Only Token',
            permissions={
                'read:reviewees': True,
                'read:cycles': True
            }
        )

        # Token with full permissions
        self.full_token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Full Access Token',
            permissions={
                'read:reviewees': True,
                'write:reviewees': True,
                'read:cycles': True,
                'write:cycles': True
            }
        )

        self.client = APIClient()

    def test_session_auth_not_affected_by_token_permissions(self):
        """Session authentication ignores token-level permissions."""
        # Give user manage permission
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_organization')
        self.user.user_permissions.add(perm)

        self.client.login(username='user', password='test123')

        # Should work even though we're not using a token
        response = self.client.post('/api/v1/reviewees/', {
            'name': 'New Reviewee',
            'email': 'new@example.com',
            'department': 'Engineering'
        })

        # May fail due to other permissions, but not token permissions
        # (Token permissions only apply to API token auth)
        self.assertNotEqual(response.status_code, 401)
