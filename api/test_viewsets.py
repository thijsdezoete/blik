"""
Tests for API viewsets.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from accounts.models import Organization, User, Reviewee
from api.models import APIToken
from reviews.models import ReviewCycle, ReviewerToken
from questionnaires.models import Questionnaire, QuestionSection, Question
from reports.models import Report


class RevieweeViewSetTest(TestCase):
    """Test RevieweeViewSet CRUD operations."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        self.user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        # Grant manage permission
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_organization')
        self.user.user_permissions.add(perm)

        self.token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Token'
        )

        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')

    def test_list_reviewees(self):
        """GET /reviewees/ returns list of reviewees."""
        # Create reviewees
        Reviewee.objects.create(
            organization=self.org,
            name='John Doe',
            email='john@example.com',
            department='Engineering'
        )
        Reviewee.objects.create(
            organization=self.org,
            name='Jane Smith',
            email='jane@example.com',
            department='Sales'
        )

        response = self.client.get('/api/v1/reviewees/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)

    def test_create_reviewee(self):
        """POST /reviewees/ creates new reviewee."""
        response = self.client.post('/api/v1/reviewees/', {
            'name': 'New Reviewee',
            'email': 'new@example.com',
            'department': 'Marketing'
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'New Reviewee')
        self.assertEqual(response.data['email'], 'new@example.com')

        # Verify created in database
        reviewee = Reviewee.objects.get(email='new@example.com')
        self.assertEqual(reviewee.organization, self.org)

    def test_retrieve_reviewee(self):
        """GET /reviewees/{id}/ returns reviewee details."""
        reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='test@example.com'
        )

        response = self.client.get(f'/api/v1/reviewees/{reviewee.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Test Reviewee')
        self.assertEqual(response.data['email'], 'test@example.com')

    def test_update_reviewee(self):
        """PUT /reviewees/{id}/ updates reviewee."""
        reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Original Name',
            email='original@example.com',
            department='Engineering'
        )

        response = self.client.put(f'/api/v1/reviewees/{reviewee.id}/', {
            'name': 'Updated Name',
            'email': 'original@example.com',
            'department': 'Sales'
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Updated Name')
        self.assertEqual(response.data['department'], 'Sales')

    def test_partial_update_reviewee(self):
        """PATCH /reviewees/{id}/ partially updates reviewee."""
        reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='test@example.com',
            department='Engineering'
        )

        response = self.client.patch(f'/api/v1/reviewees/{reviewee.id}/', {
            'department': 'Product'
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['department'], 'Product')
        self.assertEqual(response.data['name'], 'Test Reviewee')  # Unchanged

    def test_delete_reviewee_soft_deletes(self):
        """DELETE /reviewees/{id}/ soft deletes (marks inactive)."""
        reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='test@example.com'
        )

        response = self.client.delete(f'/api/v1/reviewees/{reviewee.id}/')

        self.assertEqual(response.status_code, 204)

        # Refresh from database
        reviewee.refresh_from_db()
        self.assertFalse(reviewee.is_active)

    def test_filter_by_department(self):
        """Can filter reviewees by department."""
        Reviewee.objects.create(
            organization=self.org,
            name='Engineer',
            email='eng@example.com',
            department='Engineering'
        )
        Reviewee.objects.create(
            organization=self.org,
            name='Sales Person',
            email='sales@example.com',
            department='Sales'
        )

        response = self.client.get('/api/v1/reviewees/?department=Engineering')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['email'], 'eng@example.com')

    def test_search_reviewees(self):
        """Can search reviewees by name or email."""
        Reviewee.objects.create(
            organization=self.org,
            name='John Doe',
            email='john@example.com'
        )
        Reviewee.objects.create(
            organization=self.org,
            name='Jane Smith',
            email='jane@example.com'
        )

        response = self.client.get('/api/v1/reviewees/?search=john')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], 'John Doe')

    def test_bulk_create_reviewees(self):
        """POST /reviewees/bulk_create/ creates multiple reviewees."""
        response = self.client.post('/api/v1/reviewees/bulk_create/', {
            'reviewees': [
                {'name': 'Person 1', 'email': 'p1@example.com', 'department': 'Eng'},
                {'name': 'Person 2', 'email': 'p2@example.com', 'department': 'Sales'},
                {'name': 'Person 3', 'email': 'p3@example.com', 'department': 'Marketing'}
            ]
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['summary']['created'], 3)
        self.assertEqual(response.data['summary']['failed'], 0)

        # Verify created in database
        self.assertEqual(Reviewee.objects.filter(organization=self.org).count(), 3)

    def test_bulk_create_with_errors(self):
        """Bulk create reports errors for invalid entries."""
        response = self.client.post('/api/v1/reviewees/bulk_create/', {
            'reviewees': [
                {'name': 'Valid', 'email': 'valid@example.com'},
                {'name': 'Invalid', 'email': 'not-an-email'},  # Invalid email
                {'name': '', 'email': 'empty@example.com'}      # Empty name
            ]
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['summary']['created'], 1)
        self.assertEqual(response.data['summary']['failed'], 2)
        self.assertEqual(len(response.data['errors']), 2)

    def test_unique_email_per_organization(self):
        """Email must be unique within organization."""
        Reviewee.objects.create(
            organization=self.org,
            name='Existing',
            email='existing@example.com'
        )

        response = self.client.post('/api/v1/reviewees/', {
            'name': 'Duplicate',
            'email': 'existing@example.com'
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data)


class ReviewCycleViewSetTest(TestCase):
    """Test ReviewCycleViewSet operations."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        self.user = User.objects.create_user(
            username='creator',
            email='creator@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.can_create_cycles_for_others = True
        self.user.profile.save()

        self.token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Token'
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
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')

    def test_create_cycle_basic(self):
        """POST /cycles/ creates new review cycle."""
        response = self.client.post('/api/v1/cycles/', {
            'reviewee': self.reviewee.id,
            'questionnaire': self.questionnaire.id
        })

        self.assertEqual(response.status_code, 201)

        # Verify created in database
        cycle = ReviewCycle.objects.get(id=response.data['id'])
        self.assertEqual(cycle.reviewee, self.reviewee)
        self.assertEqual(cycle.questionnaire, self.questionnaire)
        self.assertEqual(cycle.created_by, self.user)

    def test_create_cycle_with_reviewers(self):
        """Can create cycle with reviewer emails."""
        response = self.client.post('/api/v1/cycles/', {
            'reviewee': self.reviewee.id,
            'questionnaire': self.questionnaire.id,
            'reviewer_emails': {
                'self': ['reviewee@example.com'],
                'peer': ['peer1@example.com', 'peer2@example.com'],
                'manager': ['manager@example.com']
            },
            'send_invitations': False  # Don't send emails in tests
        }, format='json')

        self.assertEqual(response.status_code, 201)

        # Verify tokens created
        cycle = ReviewCycle.objects.get(id=response.data['id'])
        self.assertEqual(cycle.tokens.count(), 4)
        self.assertEqual(cycle.tokens.filter(category='peer').count(), 2)

    def test_list_cycles(self):
        """GET /cycles/ returns list of cycles."""
        ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

        response = self.client.get('/api/v1/cycles/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)

    def test_retrieve_cycle(self):
        """GET /cycles/{id}/ returns cycle details."""
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

        response = self.client.get(f'/api/v1/cycles/{cycle.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reviewee_detail']['name'], 'Test Reviewee')

    def test_filter_by_status(self):
        """Can filter cycles by status."""
        active = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user,
            status='active'
        )
        completed = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user,
            status='completed'
        )

        response = self.client.get('/api/v1/cycles/?status=active')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], active.id)

    def test_progress_action(self):
        """GET /cycles/{id}/progress/ returns detailed progress."""
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

        # Create some tokens
        ReviewerToken.objects.create(
            cycle=cycle,
            category='self',
            reviewer_email='reviewee@example.com'
        )
        ReviewerToken.objects.create(
            cycle=cycle,
            category='peer',
            reviewer_email='peer@example.com'
        )

        response = self.client.get(f'/api/v1/cycles/{cycle.id}/progress/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('overall', response.data)
        self.assertIn('by_category', response.data)
        self.assertEqual(response.data['overall']['total'], 2)


class QuestionnaireViewSetTest(TestCase):
    """Test QuestionnaireViewSet (read-only)."""

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

        self.token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Token'
        )

        # Create questionnaires
        self.org_questionnaire = Questionnaire.objects.create(
            organization=self.org,
            name='Org Questionnaire',
            is_active=True
        )

        self.shared_questionnaire = Questionnaire.objects.create(
            organization=None,  # Shared template
            name='Shared Template',
            is_active=True
        )

        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')

    def test_list_questionnaires(self):
        """GET /questionnaires/ returns org + shared questionnaires."""
        response = self.client.get('/api/v1/questionnaires/')

        self.assertEqual(response.status_code, 200)
        # Should see both org questionnaire and shared template
        self.assertEqual(len(response.data['results']), 2)

    def test_retrieve_questionnaire(self):
        """GET /questionnaires/{id}/ returns questionnaire details."""
        # Add section and question
        section = QuestionSection.objects.create(
            questionnaire=self.org_questionnaire,
            title='Section 1',
            order=1
        )
        Question.objects.create(
            section=section,
            question_text='Test question?',
            question_type='text',
            order=1
        )

        response = self.client.get(f'/api/v1/questionnaires/{self.org_questionnaire.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Org Questionnaire')
        self.assertEqual(len(response.data['sections']), 1)
        self.assertEqual(len(response.data['sections'][0]['questions']), 1)

    def test_cannot_create_questionnaire(self):
        """POST /questionnaires/ is not allowed (read-only)."""
        response = self.client.post('/api/v1/questionnaires/', {
            'name': 'New Questionnaire'
        })

        self.assertEqual(response.status_code, 405)  # Method Not Allowed


class ReportViewSetTest(TestCase):
    """Test ReportViewSet operations."""

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

        self.token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Token'
        )

        # Create test data
        reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='reviewee@example.com'
        )

        questionnaire = Questionnaire.objects.create(
            organization=self.org,
            name='Test Questionnaire',
            is_active=True
        )

        self.cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=self.user
        )

        self.report = Report.objects.create(
            cycle=self.cycle,
            report_data={'test': 'data'},
            available=True
        )

        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')

    def test_list_reports(self):
        """GET /reports/ returns list of reports."""
        response = self.client.get('/api/v1/reports/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)

    def test_list_hides_access_token(self):
        """List view should not expose access_token."""
        response = self.client.get('/api/v1/reports/')

        self.assertEqual(response.status_code, 200)
        # access_token should not be in list response
        self.assertNotIn('access_token', response.data['results'][0])

    def test_retrieve_shows_access_token(self):
        """Detail view should show access_token."""
        response = self.client.get(f'/api/v1/reports/{self.report.id}/')

        self.assertEqual(response.status_code, 200)
        # access_token should be in detail response
        self.assertIn('access_token', response.data)
        self.assertEqual(response.data['access_token'], self.report.access_token)
