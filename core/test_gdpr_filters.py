from django.test import TestCase

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.models import Reviewee, UserProfile
from core.factories import OrganizationFactory, UserFactory
from core.gdpr import GDPRDeletionService, filter_reviewees, filter_users


class GdprListFilterTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.active = RevieweeFactory(organization=self.org, name='Ada Active', email='ada@acme.example')
        self.left = RevieweeFactory(
            organization=self.org, name='Lee Left', email='lee@acme.example', is_active=False)
        gone = RevieweeFactory(organization=self.org, name='Gus Gone', email='gus@acme.example')
        GDPRDeletionService.delete_reviewee(gone.id)
        self.gone = Reviewee.objects.get(pk=gone.pk)
        self.people = Reviewee.objects.filter(organization=self.org)

    def account(self, email):
        return UserProfileFactory(
            user=UserFactory(username=email, email=email, first_name='', last_name=''), organization=self.org)

    def test_reviewee_statuses_do_not_overlap(self):
        for status, expected in (
            ('active', [self.active]), ('deactivated', [self.left]), ('anonymized', [self.gone]),
            ('', [self.active, self.left, self.gone]),
        ):
            self.assertCountEqual(filter_reviewees(self.people, status=status), expected, status)

    def test_reviewee_search_in_name_and_email(self):
        self.assertCountEqual(filter_reviewees(self.people, q='lee l'), [self.left])
        self.assertCountEqual(filter_reviewees(self.people, q='ADA@acme'), [self.active])
        self.assertCountEqual(filter_reviewees(self.people, q='ada', status='deactivated'), [])

    def test_account_of_a_deactivated_person(self):
        stays = self.account('ada@acme.example')
        left = self.account('lee@acme.example')
        # The email is the only link between account and person, in any case.
        Reviewee.objects.filter(pk=self.left.pk).update(email='Lee@Acme.example')
        no_person = self.account('admin@acme.example')
        # A second, active record with the same email in another organization does not count.
        RevieweeFactory(organization=OrganizationFactory(), email='lee@acme.example')
        gone = self.account('gus@acme.example')
        GDPRDeletionService.delete_user(gone.user_id)
        profiles = UserProfile.objects.filter(organization=self.org)

        for status, expected in (
            ('active', [stays, no_person]), ('deactivated', [left]), ('anonymized', [gone]),
            ('', [stays, left, no_person, gone]),
        ):
            self.assertCountEqual(filter_users(profiles, self.org, status=status), expected, status)
        self.assertCountEqual(filter_users(profiles, self.org, q='lee'), [left])
        self.assertTrue(filter_users(profiles, self.org).get(pk=left.pk).person_left)
