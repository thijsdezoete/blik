"""
Tests for the reviewee picker Phase 1 work:

- `reviewee_quick_create` JSON endpoint
- `collect_reviewer_emails` server-side helper
- End-to-end equivalence: picker-UUID submission and email-textarea
  submission produce the same ReviewerToken rows.
"""
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.models import Reviewee, UserProfile
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle, ReviewerToken

from blik.admin_views import collect_reviewer_emails
from reviews.models import CATEGORY_ORDER as ALL


def _grant_manage_permission(user):
    """Give the user the `can_manage_organization` permission."""
    ct = ContentType.objects.get_for_model(UserProfile)
    perm, _ = Permission.objects.get_or_create(
        codename='can_manage_organization',
        content_type=ct,
        defaults={'name': 'Can manage organization settings'},
    )
    user.user_permissions.add(perm)


class RevieweeQuickCreateTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='admin_qc')
        UserProfileFactory(user=self.admin, organization=self.org,
                           can_create_cycles_for_others=True)
        _grant_manage_permission(self.admin)
        self.client.force_login(self.admin)

    def test_creates_new_reviewee(self):
        resp = self.client.post(
            reverse('reviewee_quick_create'),
            {'name': 'New Person', 'email': 'new@example.com'},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['created'])
        self.assertEqual(data['email'], 'new@example.com')
        self.assertTrue(Reviewee.objects.filter(
            organization=self.org, email='new@example.com').exists())

    def test_returns_existing_reviewee_without_duplicating(self):
        existing = RevieweeFactory(
            organization=self.org, name='Existing', email='same@example.com')

        resp = self.client.post(
            reverse('reviewee_quick_create'),
            {'name': 'Different Name', 'email': 'same@example.com'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['created'])
        self.assertEqual(data['uuid'], str(existing.uuid))
        # Name should not be overwritten
        existing.refresh_from_db()
        self.assertEqual(existing.name, 'Existing')
        self.assertEqual(Reviewee.objects.filter(
            organization=self.org, email='same@example.com').count(), 1)

    def test_reactivates_soft_deleted_reviewee(self):
        existing = RevieweeFactory(
            organization=self.org, email='back@example.com', is_active=False)

        resp = self.client.post(
            reverse('reviewee_quick_create'),
            {'name': existing.name, 'email': 'back@example.com'},
        )
        self.assertEqual(resp.status_code, 200)
        existing.refresh_from_db()
        self.assertTrue(existing.is_active)

    def test_requires_permission(self):
        user = UserFactory(username='no_perm_user')
        UserProfileFactory(user=user, organization=self.org)
        self.client.force_login(user)
        resp = self.client.post(
            reverse('reviewee_quick_create'),
            {'name': 'X', 'email': 'x@example.com'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_validates_email(self):
        resp = self.client.post(
            reverse('reviewee_quick_create'),
            {'name': 'X', 'email': 'not-an-email'},
        )
        self.assertEqual(resp.status_code, 400)

    def test_requires_post(self):
        resp = self.client.get(reverse('reviewee_quick_create'))
        self.assertEqual(resp.status_code, 405)


class CollectReviewerEmailsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.org = OrganizationFactory()
        self.other_org = OrganizationFactory()

        self.alice = RevieweeFactory(
            organization=self.org, name='Alice', email='Alice@Example.com')
        self.bob = RevieweeFactory(
            organization=self.org, name='Bob', email='bob@example.com')
        self.cross_org = RevieweeFactory(
            organization=self.other_org, name='Outsider',
            email='out@other.example.com')

    def _post(self, data):
        req = self.factory.post('/', data=data)
        req.organization = self.org
        return req

    def test_picker_uuids_resolve_to_emails(self):
        req = self._post({
            'manager_reviewees': [str(self.alice.uuid)],
            'peer_reviewees': [str(self.bob.uuid)],
        })
        assignments, warnings = collect_reviewer_emails(req, self.org, ALL)
        self.assertEqual(assignments['manager'], ['alice@example.com'])
        self.assertEqual(assignments['peer'], ['bob@example.com'])
        self.assertEqual(assignments['self'], [])
        self.assertEqual(assignments['direct_report'], [])
        self.assertEqual(warnings, [])

    def test_textareas_still_work(self):
        req = self._post({
            'peer_emails': 'one@example.com, two@example.com\nthree@example.com',
        })
        assignments, warnings = collect_reviewer_emails(req, self.org, ALL)
        self.assertEqual(sorted(assignments['peer']),
                         ['one@example.com', 'three@example.com', 'two@example.com'])
        self.assertEqual(warnings, [])

    def test_picker_and_textarea_dedup_by_normalized_email(self):
        # Picker adds alice@example.com (via UUID → lowercased email).
        # Textarea also lists ALICE@example.com with different case.
        req = self._post({
            'manager_reviewees': [str(self.alice.uuid)],
            'manager_emails': 'ALICE@example.com, other@example.com',
        })
        assignments, _ = collect_reviewer_emails(req, self.org, ALL)
        self.assertEqual(
            assignments['manager'], ['alice@example.com', 'other@example.com'])

    def test_invalid_textarea_email_becomes_warning(self):
        req = self._post({'peer_emails': 'valid@example.com, not-valid'})
        assignments, warnings = collect_reviewer_emails(req, self.org, ALL)
        self.assertEqual(assignments['peer'], ['valid@example.com'])
        self.assertEqual(len(warnings), 1)
        self.assertIn('not-valid', warnings[0])

    def test_cross_org_uuid_is_silently_skipped(self):
        req = self._post({
            'peer_reviewees': [str(self.cross_org.uuid), str(self.alice.uuid)],
        })
        assignments, _ = collect_reviewer_emails(req, self.org, ALL)
        self.assertEqual(assignments['peer'], ['alice@example.com'])

    def test_empty_post_returns_empty_buckets(self):
        req = self._post({})
        assignments, warnings = collect_reviewer_emails(req, self.org, ALL)
        self.assertEqual(warnings, [])
        for cat in ['self', 'manager', 'peer', 'direct_report']:
            self.assertEqual(assignments[cat], [])


class CyclePickerSubmissionTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.admin = UserFactory(username='admin_cyc')
        UserProfileFactory(user=self.admin, organization=self.org,
                           can_create_cycles_for_others=True)
        _grant_manage_permission(self.admin)
        self.client.force_login(self.admin)

        self.reviewee = RevieweeFactory(
            organization=self.org, name='Target', email='target@example.com')
        self.alice = RevieweeFactory(
            organization=self.org, name='Alice', email='alice@example.com')
        self.bob = RevieweeFactory(
            organization=self.org, name='Bob', email='bob@example.com')

        self.questionnaire = QuestionnaireFactory(organization=self.org)

    def test_picker_uuid_submission_creates_tokens_with_emails(self):
        resp = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'single',
            'questionnaire': str(self.questionnaire.id),
            'reviewee': str(self.reviewee.id),
            'self_reviewees': [str(self.reviewee.uuid)],
            'manager_reviewees': [str(self.alice.uuid)],
            'peer_reviewees': [str(self.bob.uuid)],
        })
        # The view redirects after success (either cycle_detail or manage_invitations).
        self.assertEqual(resp.status_code, 302)

        cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        emails_by_cat = {
            cat: sorted(
                cycle.tokens.filter(
                    category=cat, reviewer_email__isnull=False
                ).values_list('reviewer_email', flat=True)
            )
            for cat in ['self', 'manager', 'peer', 'direct_report']
        }
        self.assertEqual(emails_by_cat['self'], ['target@example.com'])
        self.assertEqual(emails_by_cat['manager'], ['alice@example.com'])
        self.assertEqual(emails_by_cat['peer'], ['bob@example.com'])
        self.assertEqual(emails_by_cat['direct_report'], [])

    def test_picker_and_textarea_equivalence(self):
        """Same emails via picker vs textarea produce same token set."""
        # Round 1: picker submission
        resp = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'single',
            'questionnaire': str(self.questionnaire.id),
            'reviewee': str(self.reviewee.id),
            'manager_reviewees': [str(self.alice.uuid)],
            'peer_reviewees': [str(self.bob.uuid)],
        })
        self.assertEqual(resp.status_code, 302)
        picker_cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        picker_emails = sorted(
            picker_cycle.tokens.filter(
                reviewer_email__isnull=False
            ).values_list('category', 'reviewer_email')
        )
        picker_cycle.delete()

        # Round 2: textarea submission with the same emails
        resp = self.client.post(reverse('review_cycle_create'), {
            'creation_mode': 'single',
            'questionnaire': str(self.questionnaire.id),
            'reviewee': str(self.reviewee.id),
            'manager_emails': 'alice@example.com',
            'peer_emails': 'bob@example.com',
        })
        self.assertEqual(resp.status_code, 302)
        textarea_cycle = ReviewCycle.objects.get(reviewee=self.reviewee)
        textarea_emails = sorted(
            textarea_cycle.tokens.filter(
                reviewer_email__isnull=False
            ).values_list('category', 'reviewer_email')
        )

        self.assertEqual(picker_emails, textarea_emails)


class CollectReviewerEmailsCategoriesTests(TestCase):
    def test_categories_outside_the_list_stay_empty(self):
        org = OrganizationFactory()
        req = RequestFactory().post('/', {'peer_emails': 'a@example.com', 'manager_emails': 'b@example.com'})
        assignments, _ = collect_reviewer_emails(req, org, ['manager'])
        self.assertEqual(assignments['peer'], [])
        self.assertEqual(assignments['manager'], ['b@example.com'])
