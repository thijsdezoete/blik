"""GitHub #22: regular members could download the full organization export
and browse the (read-only) settings page, which lists API tokens, webhooks
and SMTP configuration. Both are admin-only."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, assign_organization_member
from core.models import Organization


class MemberAuthorizationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.member = User.objects.create_user(username='member', email='m@acme.example', password='pw')
        UserProfile.objects.create(user=self.member, organization=self.org)
        assign_organization_member(self.member)
        self.admin = User.objects.create_user(username='admin', email='a@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

    def test_member_cannot_export_organization_data(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('account:export_data'))
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp.get('Content-Type'), 'application/json')

    def test_member_cannot_open_settings_page(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('settings'))
        self.assertRedirects(resp, reverse('admin_dashboard'), fetch_redirect_response=False)

    def test_admin_can_export(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('account:export_data'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json')

    def test_member_cannot_create_api_token(self):
        from api.models import APIToken
        self.client.force_login(self.member)
        resp = self.client.post(reverse('create_api_token'), {'name': 'sneaky'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(APIToken.objects.exists())

    def test_member_does_not_see_settings_in_nav(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('admin_dashboard'))
        self.assertNotContains(resp, reverse('settings'))
