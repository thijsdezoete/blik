from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.url import get_absolute_url
from reviews.factories import ReviewerTokenFactory


@override_settings(SITE_PROTOCOL='https', SITE_DOMAIN='blik.example')
class GetAbsoluteUrlTests(SimpleTestCase):
    def test_a_view_name_with_arguments(self):
        url = get_absolute_url('review_cycle_detail', cycle_uuid='0c4a9e1e-5d33-4c39-9f0c-1b2a3c4d5e6f')

        self.assertEqual(url, 'https://blik.example/dashboard/cycles/0c4a9e1e-5d33-4c39-9f0c-1b2a3c4d5e6f/')

    def test_a_path(self):
        self.assertEqual(get_absolute_url('/landing/dreyfus-model/'), 'https://blik.example/landing/dreyfus-model/')


@override_settings(SITE_PROTOCOL='https', SITE_DOMAIN='blik.example')
class AbsoluteUrlTagTests(TestCase):
    def test_the_copied_review_link_uses_the_site_domain_not_the_request_host(self):
        ensure_permission_groups()
        token = ReviewerTokenFactory()
        admin = User.objects.create_user(username='admin', email='admin@example.com', password='pw')
        UserProfile.objects.create(user=admin, organization=token.cycle.reviewee.organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)

        response = self.client.get(reverse('send_reminder_form', args=[token.cycle.uuid]))

        self.assertContains(response, f'data-url="https://blik.example/feedback/{token.token}/"')
