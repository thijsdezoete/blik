from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.factories import RevieweeFactory
from accounts.models import ReviewSetup, SetupReviewer
from core.factories import OrganizationFactory
from core.gdpr import GDPRDeletionService


class ReviewSetupModelTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.a = RevieweeFactory(organization=self.org, email='a@acme.example')
        self.b = RevieweeFactory(organization=self.org, email='b@acme.example')
        self.c = RevieweeFactory(organization=self.org, email='c@acme.example')
        self.setup = ReviewSetup.objects.create(reviewee=self.a)

    def test_row_needs_a_person_or_an_email_not_both(self):
        for kwargs in ({'person': self.b, 'email': 'b@acme.example'}, {}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                SetupReviewer.objects.create(setup=self.setup, category='peer', **kwargs)

    def test_same_person_once_per_category(self):
        SetupReviewer.objects.create(setup=self.setup, category='peer', person=self.b)
        SetupReviewer.objects.create(setup=self.setup, category='manager', person=self.b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SetupReviewer.objects.create(setup=self.setup, category='peer', person=self.b)

    def test_same_email_once_per_category_ignoring_case(self):
        SetupReviewer.objects.create(setup=self.setup, category='peer', email='Ext@Acme.example')
        self.assertEqual(self.setup.reviewers.get().email, 'ext@acme.example')
        with self.assertRaises(IntegrityError), transaction.atomic():
            SetupReviewer.objects.create(setup=self.setup, category='peer', email='EXT@acme.example')

    def test_soft_delete_removes_the_lists(self):
        setup_b = ReviewSetup.objects.create(reviewee=self.b)
        setup_c = ReviewSetup.objects.create(reviewee=self.c)
        SetupReviewer.objects.create(setup=self.setup, category='peer', person=self.b)
        SetupReviewer.objects.create(setup=setup_b, category='peer', person=self.a)
        SetupReviewer.objects.create(setup=setup_b, category='peer', person=self.c)
        SetupReviewer.objects.create(setup=setup_c, category='peer', email='a@acme.example')
        SetupReviewer.objects.create(setup=setup_c, category='peer', email='x@acme.example')

        GDPRDeletionService.delete_reviewee(self.a.id)

        self.assertFalse(ReviewSetup.objects.filter(reviewee=self.a).exists())
        self.assertEqual([r.person for r in setup_b.reviewers.all()], [self.c])
        self.assertEqual([r.email for r in setup_c.reviewers.all()], ['x@acme.example'])

    def test_soft_delete_keeps_rows_of_other_organizations_with_the_same_email(self):
        other = RevieweeFactory(organization=OrganizationFactory(), email='o@other.example')
        other_setup = ReviewSetup.objects.create(reviewee=other)
        SetupReviewer.objects.create(setup=other_setup, category='peer', email='a@acme.example')

        GDPRDeletionService.delete_reviewee(self.a.id)

        self.assertEqual(other_setup.reviewers.count(), 1)

    def test_soft_delete_of_a_reviewee_without_email_keeps_person_rows(self):
        nameless = RevieweeFactory(organization=self.org, email='')
        setup_b = ReviewSetup.objects.create(reviewee=self.b)
        SetupReviewer.objects.create(setup=setup_b, category='peer', person=self.c)

        GDPRDeletionService.delete_reviewee(nameless.id)

        self.assertEqual(setup_b.reviewers.count(), 1)
