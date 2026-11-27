"""Login through Django's LoginView, with the username or the email address."""
import uuid

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin
from core.models import Organization
from reports.models import Report
from reviews.factories import ReviewCycleFactory


class LoginTests(TestCase):
    def setUp(self):
        # The login is rate limited per IP; the limit counts in the cache
        cache.clear()
        organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.user = User.objects.create_user(username='dana', email='Dana@acme.example', password='secret-pw')
        UserProfile.objects.create(user=self.user, organization=organization)

    def login(self, username, password='secret-pw', next_url=''):
        return self.client.post(reverse('login'), {'username': username, 'password': password, 'next': next_url})

    def test_the_username_logs_in_and_lands_on_the_dashboard(self):
        response = self.login('dana')

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)

    def test_the_email_address_logs_in_regardless_of_case(self):
        response = self.login('dana@ACME.example')

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)

    def test_the_login_returns_to_the_page_that_asked_for_it(self):
        response = self.login('dana', next_url='/dashboard/team/')

        self.assertRedirects(response, '/dashboard/team/', fetch_redirect_response=False)

    def test_a_next_url_on_another_host_is_ignored(self):
        response = self.login('dana', next_url='https://evil.example/')

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)

    def test_a_wrong_password_shows_an_error(self):
        response = self.login('dana', password='wrong')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alert-error')

    def test_two_users_with_the_same_email_address_can_both_log_in(self):
        User.objects.create_user(username='dana2', email='dana@acme.example', password='other-pw')

        response = self.login('dana@acme.example', password='other-pw')

        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)

    def test_the_sixth_attempt_within_a_minute_is_blocked(self):
        # Different usernames, so axes (per username and IP) does not lock first
        for attempt in range(5):
            self.assertEqual(self.login(f'nobody{attempt}', password='wrong').status_code, 200)

        self.assertEqual(self.login('dana').status_code, 403)
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)

    def test_a_signed_in_user_is_sent_on(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('login') + '?next=/dashboard/team/')

        self.assertRedirects(response, '/dashboard/team/', fetch_redirect_response=False)


class DeactivatedPersonTests(TestCase):
    """A person who was deactivated has left: their account shows their own profile page and nothing else."""

    def setUp(self):
        self.organization = Organization.objects.create(name='Acme', email='org@acme.example')
        self.user = User.objects.create_user(username='dana', email='Dana@acme.example', password='secret-pw')
        UserProfile.objects.create(user=self.user, organization=self.organization)
        # A new profile gets its person record by signal
        self.person = Reviewee.objects.get(organization=self.organization)
        self.person.is_active = False
        self.person.save()
        self.client.force_login(self.user)

    def test_a_deactivated_person_is_sent_to_their_profile_from_every_other_page(self):
        for url in (reverse('reviewee_list'), reverse('admin_dashboard'), reverse('send_invitation'),
                    '/api/v1/reviewees/'):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse('profile'), fetch_redirect_response=False)

    def test_a_deactivated_person_can_view_their_profile(self):
        response = self.client.get(reverse('profile'))

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.wsgi_request.person_deactivated, True)

    def test_a_deactivated_person_can_open_their_own_report_but_not_the_report_page_of_the_dashboard(self):
        cycle = ReviewCycleFactory(reviewee=self.person, status='completed')
        report = Report.objects.create(cycle=cycle, access_token=uuid.uuid4(), report_data={})

        own = self.client.get(reverse('reports:reviewee_report', args=[report.access_token]))
        dashboard = self.client.get(reverse('reports:view_report', args=[cycle.uuid]))

        self.assertEqual(own.status_code, 200)
        self.assertRedirects(dashboard, reverse('profile'), fetch_redirect_response=False)

    def test_a_deactivated_person_cannot_change_their_email_or_password(self):
        for fields in ({'email': 'dana.new@acme.example', 'first_name': 'Dana', 'last_name': 'New'},
                       {'change_password': '1', 'old_password': 'secret-pw',
                        'new_password1': 'another-pw-91', 'new_password2': 'another-pw-91'}):
            with self.subTest(fields=fields):
                response = self.client.post(reverse('profile'), fields)

                self.assertRedirects(response, reverse('profile'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'Dana@acme.example')
        self.assertTrue(self.user.check_password('secret-pw'))

    def test_a_deactivated_person_can_log_out(self):
        self.client.post(reverse('logout'))

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_an_active_person_is_not_limited(self):
        self.person.is_active = True
        self.person.save()

        self.assertEqual(self.client.get(reverse('reviewee_list')).status_code, 200)

    def test_a_deactivated_person_of_another_organization_does_not_count(self):
        other = Organization.objects.create(name='Other', email='org@other.example')
        Reviewee.objects.filter(pk=self.person.pk).update(organization=other)

        self.assertEqual(self.client.get(reverse('reviewee_list')).status_code, 200)

    def test_an_administrator_is_not_limited_by_their_own_person_record(self):
        assign_organization_admin(self.user)

        self.assertEqual(self.client.get(reverse('reviewee_list')).status_code, 200)
