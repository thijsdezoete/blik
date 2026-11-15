"""Who may open the setup pages.

The pages change the organization: its name and contact address, the mail
server, and they can fill it with demo data. Before the first run anybody may
use them, because no admin exists yet. After that they are for the people who
may change the same things in the settings.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.factories import UserProfileFactory
from accounts.models import Reviewee
from accounts.permissions import assign_organization_admin, assign_organization_member, ensure_permission_groups
from core.factories import OrganizationFactory, UserFactory
from core.views import may_run_setup


class MayRunSetupTests(TestCase):
    def test_before_the_first_run_an_account_without_organization_may(self):
        self.assertTrue(may_run_setup(User.objects.create_user('first', 'first@acme.example', 'pw')))

    def test_after_the_first_run_only_who_manages_the_organization_may(self):
        ensure_permission_groups()
        org = OrganizationFactory()
        admin, member = UserFactory(), UserFactory()
        for user, assign in ((admin, assign_organization_admin), (member, assign_organization_member)):
            UserProfileFactory(user=user, organization=org)
            assign(user)
        stray = User.objects.create_user('stray', 'stray@acme.example', 'pw')

        # has_perm caches per instance; the views get a fresh one per request.
        self.assertTrue(may_run_setup(User.objects.get(pk=admin.pk)))
        self.assertFalse(may_run_setup(User.objects.get(pk=member.pk)))
        self.assertFalse(may_run_setup(stray))


class SetupPagesRefuseAMemberTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = OrganizationFactory(name='Acme', smtp_host='mail.acme.example')
        member = UserFactory()
        UserProfileFactory(user=member, organization=self.org)
        assign_organization_member(member)
        self.client.force_login(member)

    def test_the_organization_keeps_its_name(self):
        self.client.post(reverse('setup_organization'), {'name': 'Taken over', 'email': 'other@acme.example'})

        self.org.refresh_from_db()
        self.assertEqual(self.org.name, 'Acme')

    def test_the_mail_server_stays(self):
        self.client.post(reverse('setup_email'), {
            'smtp_host': 'mail.other.example', 'smtp_port': 587, 'from_email': 'other@other.example'})

        self.org.refresh_from_db()
        self.assertEqual(self.org.smtp_host, 'mail.acme.example')

    def test_no_demo_data_is_made(self):
        before = Reviewee.objects.filter(organization=self.org).count()

        self.client.post(reverse('setup_complete'), {'generate_test_data': '1'})

        self.assertEqual(Reviewee.objects.filter(organization=self.org).count(), before)
