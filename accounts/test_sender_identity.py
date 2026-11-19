"""The names an invitation email shows: which are missing, how they are saved, and what the subject does without them."""
import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts import sender_identity
from accounts.invitation_views import invitation_email
from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, assign_organization_member
from core.env_config import ENV_ORGANIZATION_ID
from core.models import Organization


def account(email, organization, admin=True, **names):
    user = User.objects.create_user(username=email, email=email, password='x', **names)
    UserProfile.objects.create(user=user, organization=organization)
    (assign_organization_admin if admin else assign_organization_member)(user)
    return User.objects.get(pk=user.pk)


class MissingTests(TestCase):
    def setUp(self):
        # The organization of a free signup: named after the email address, and not the one the environment owns.
        Organization.objects.create(pk=ENV_ORGANIZATION_ID, name='Blik', email='blik@acme.example')
        self.organization = Organization.objects.create(name='anna@acme.example', email='anna@acme.example')

    def test_free_signup_admin_misses_both_names(self):
        admin = account('anna@acme.example', self.organization)

        self.assertEqual(sender_identity.missing(admin, self.organization), {'name', 'organization'})

    def test_nothing_is_missing_with_a_name_and_a_named_organization(self):
        self.organization.name = 'Acme'
        admin = account('anna@acme.example', self.organization, first_name='Anna')

        self.assertEqual(sender_identity.missing(admin, self.organization), set())

    def test_member_is_not_asked_for_the_organization_name(self):
        member = account('ben@acme.example', self.organization, admin=False)

        self.assertEqual(sender_identity.missing(member, self.organization), {'name'})

    def test_organization_name_of_the_environment_is_not_asked_for(self):
        owned = Organization.objects.get(pk=ENV_ORGANIZATION_ID)
        owned.name = 'ops@acme.example'
        admin = account('ops@acme.example', owned, first_name='Otto')

        with patch.dict(os.environ, {'ORGANIZATION_NAME': 'ops@acme.example'}):
            self.assertEqual(sender_identity.missing(admin, owned), set())
            # Another organization on the same service keeps the right to its own name.
            other = account('anna@acme.example', self.organization, first_name='Anna')
            self.assertEqual(sender_identity.missing(other, self.organization), {'organization'})


class SaveTests(TestCase):
    def setUp(self):
        Organization.objects.create(pk=ENV_ORGANIZATION_ID, name='Blik', email='blik@acme.example')
        self.organization = Organization.objects.create(name='anna@acme.example', email='anna@acme.example')
        self.admin = account('anna@acme.example', self.organization)
        self.posted = {
            sender_identity.FIRST_NAME: ' Anna ', sender_identity.LAST_NAME: 'Jansen',
            sender_identity.ORGANIZATION_NAME: 'Acme',
        }

    def test_saves_the_missing_names(self):
        sender_identity.save(self.admin, self.organization, self.posted)

        self.assertEqual(User.objects.get(pk=self.admin.pk).get_full_name(), 'Anna Jansen')
        self.assertEqual(Organization.objects.get(pk=self.organization.pk).name, 'Acme')

    def test_empty_values_change_nothing(self):
        sender_identity.save(self.admin, self.organization, {})

        self.assertEqual(User.objects.get(pk=self.admin.pk).get_full_name(), '')
        self.assertEqual(Organization.objects.get(pk=self.organization.pk).name, 'anna@acme.example')

    def test_member_cannot_rename_the_organization(self):
        member = account('ben@acme.example', self.organization, admin=False)

        sender_identity.save(member, self.organization, self.posted)

        self.assertEqual(User.objects.get(pk=member.pk).first_name, 'Anna')
        self.assertEqual(Organization.objects.get(pk=self.organization.pk).name, 'anna@acme.example')

    def test_names_that_are_set_are_not_overwritten(self):
        self.organization.name = 'Acme'
        self.organization.save()
        named = account('carla@acme.example', self.organization, first_name='Carla')

        sender_identity.save(named, self.organization, {
            sender_identity.FIRST_NAME: 'Mallory', sender_identity.ORGANIZATION_NAME: 'Other'})

        self.assertEqual(User.objects.get(pk=named.pk).first_name, 'Carla')
        self.assertEqual(Organization.objects.get(pk=self.organization.pk).name, 'Acme')

    def test_endpoint_saves_for_the_logged_in_user(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('save_sender_identity'), self.posted)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(Organization.objects.get(pk=self.organization.pk).name, 'Acme')


class SubjectTests(TestCase):
    """An email address in the subject looks like spam."""

    def setUp(self):
        self.organization = Organization.objects.create(name='Acme', email='anna@acme.example')

    def test_named_inviter_is_in_the_subject(self):
        anna = User(first_name='Anna', last_name='Jansen', email='anna@acme.example')

        self.assertEqual(invitation_email(self.organization, anna, '#')[0],
                         'Anna Jansen invited you to join Acme on Blik360')

    def test_inviter_without_a_name_is_not_in_the_subject(self):
        subject, text, _html = invitation_email(self.organization, User(email='anna@acme.example'), '#')

        self.assertEqual(subject, 'Invitation to join Acme on Blik360')
        # The text still says who sent the invitation.
        self.assertIn('anna@acme.example invited you', text)

    def test_organization_named_after_an_email_address_is_not_in_the_subject(self):
        self.organization.name = 'anna@acme.example'
        anna = User(first_name='Anna', email='anna@acme.example')

        self.assertEqual(invitation_email(self.organization, anna, '#')[0], 'Your invitation to Blik360')


class PreviewTests(TestCase):
    def setUp(self):
        Organization.objects.create(pk=ENV_ORGANIZATION_ID, name='Blik', email='blik@acme.example')
        self.organization = Organization.objects.create(name='anna@acme.example', email='anna@acme.example')
        self.admin = account('anna@acme.example', self.organization)
        self.client.force_login(self.admin)
        self.typed = {sender_identity.FIRST_NAME: 'Anna', sender_identity.ORGANIZATION_NAME: 'Acme'}

    def test_shows_the_email_as_it_is_now(self):
        preview = self.client.get(reverse('invitation_preview'), {'kind': 'team'}).json()

        self.assertEqual(preview['subject'], 'Your invitation to Blik360')
        self.assertIn('anna@acme.example invited you to join', preview['html'])

    def test_shows_the_typed_names_and_saves_nothing(self):
        preview = self.client.get(reverse('invitation_preview'), {'kind': 'team', **self.typed}).json()

        self.assertEqual(preview['subject'], 'Anna invited you to join Acme on Blik360')
        self.assertEqual(User.objects.get(pk=self.admin.pk).first_name, '')
        self.assertEqual(Organization.objects.get(pk=self.organization.pk).name, 'anna@acme.example')

    def test_reviewer_invitation_names_the_organization(self):
        preview = self.client.get(reverse('invitation_preview'), {'kind': 'reviewer', **self.typed}).json()

        self.assertEqual(preview['subject'], 'Your feedback for Anna')
        self.assertIn('Acme asks for your honest feedback', preview['html'])
