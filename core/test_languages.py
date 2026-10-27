"""Which language a request, a reviewer's form and an email get (core/languages.py)."""
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.factories import OrganizationFactory
from core.languages import get_base_language, request_language, translation_languages
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.services import send_reminder_emails, send_reviewer_invitations


class VariantTests(SimpleTestCase):
    def test_a_variant_falls_back_to_its_base_language(self):
        self.assertEqual(translation_languages('de-informal'), ['de-informal', 'de'])
        self.assertEqual(translation_languages('en'), ['en'])

    def test_a_language_without_variant_is_its_own_base(self):
        self.assertEqual(get_base_language('de-informal'), 'de')
        self.assertEqual(get_base_language('de'), 'de')


class RequestLanguageTests(TestCase):
    def request(self, accept_language=None):
        headers = {'HTTP_ACCEPT_LANGUAGE': accept_language} if accept_language else {}
        return RequestFactory().get('/', **headers)

    def test_a_preferred_language_wins(self):
        organization = OrganizationFactory(default_language='en')
        self.assertEqual(request_language(self.request('en'), '', 'de-informal', organization=organization), 'de-informal')

    def test_an_unknown_preferred_language_is_skipped(self):
        organization = OrganizationFactory(default_language='en')
        self.assertEqual(request_language(self.request('de'), 'xx', organization=organization), 'de')

    def test_the_browser_gets_the_organizations_variant_of_its_language(self):
        organization = OrganizationFactory(default_language='de-informal')
        self.assertEqual(request_language(self.request('de-DE,de;q=0.9'), organization=organization), 'de-informal')

    def test_the_browser_wins_over_another_organization_language(self):
        organization = OrganizationFactory(default_language='en')
        self.assertEqual(request_language(self.request('de'), organization=organization), 'de')

    def test_an_unsupported_or_missing_browser_language_falls_back_to_the_organization(self):
        organization = OrganizationFactory(default_language='de')
        self.assertEqual(request_language(self.request('es'), organization=organization), 'de')
        self.assertEqual(request_language(self.request(), organization=organization), 'de')


class DashboardLanguageTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.organization = OrganizationFactory(default_language='en')
        self.user = User.objects.create_user(username='admin', email='admin@example.com', password='pw')
        self.profile = UserProfile.objects.create(user=self.user, organization=self.organization)
        assign_organization_admin(self.user)
        self.client.force_login(self.user)

    def test_the_profile_language_beats_the_browser(self):
        self.profile.language = 'de-informal'
        self.profile.save()

        response = self.client.get(reverse('admin_dashboard'), HTTP_ACCEPT_LANGUAGE='en')

        self.assertEqual(response['Content-Language'], 'de-informal')

    def test_the_switcher_stores_the_choice_on_the_profile(self):
        self.client.post(reverse('set_language'), {'language': 'de', 'next': '/dashboard/'})

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, 'de')

    def test_the_switcher_ignores_unknown_languages(self):
        self.client.post(reverse('set_language'), {'language': 'xx', 'next': '/dashboard/'})

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, '')


class FeedbackFormLanguageTests(TestCase):
    def setUp(self):
        self.cycle = ReviewCycleFactory(reviewee__organization__default_language='de-informal')
        self.token = ReviewerTokenFactory(cycle=self.cycle)
        # SetupMiddleware sends every request to /setup/ until a profile exists
        user = User.objects.create_user(username='admin', email='admin@example.com', password='pw')
        UserProfile.objects.create(user=user, organization=self.cycle.reviewee.organization)

    def test_the_form_stores_the_language_it_was_shown_in(self):
        response = self.client.get(reverse('reviews:feedback_form', args=[self.token.token]), HTTP_ACCEPT_LANGUAGE='de')

        self.token.refresh_from_db()
        self.assertEqual(self.token.language, 'de-informal')
        self.assertEqual(response['Content-Language'], 'de-informal')

    def test_the_token_language_beats_the_browser(self):
        self.token.language = 'en'
        self.token.save()

        response = self.client.get(reverse('reviews:feedback_form', args=[self.token.token]), HTTP_ACCEPT_LANGUAGE='de')

        self.assertEqual(response['Content-Language'], 'en')

    def test_the_switcher_stores_the_choice_on_the_token(self):
        self.client.post(reverse('reviews:feedback_language', args=[self.token.token]), {'language': 'de'})

        self.token.refresh_from_db()
        self.assertEqual(self.token.language, 'de')


class EmailLanguageTests(TestCase):
    """The language that is active while each email is rendered and sent."""

    def setUp(self):
        self.cycle = ReviewCycleFactory(reviewee__organization__default_language='de')
        self.languages = []

    def capture(self, **kwargs):
        self.languages.append(translation.get_language())
        return 1

    def test_invitations_use_the_reviewers_language_else_the_organizations(self):
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='a@example.com', language='en')
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='b@example.com')

        with patch('reviews.services.send_email', side_effect=self.capture):
            send_reviewer_invitations(self.cycle)

        self.assertEqual(sorted(self.languages), ['de', 'en'])

    def test_reminders_use_the_reviewers_language(self):
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='a@example.com', language='de-informal',
                             invitation_sent_at=timezone.now())

        with patch('reviews.services.send_email', side_effect=self.capture):
            send_reminder_emails(self.cycle)

        self.assertEqual(self.languages, ['de-informal'])

    def test_the_language_is_restored_after_sending(self):
        ReviewerTokenFactory(cycle=self.cycle, reviewer_email='a@example.com', language='de')

        with translation.override(settings.LANGUAGE_CODE), patch('reviews.services.send_email', side_effect=self.capture):
            send_reviewer_invitations(self.cycle)
            self.assertEqual(translation.get_language(), settings.LANGUAGE_CODE)


class TeamInvitationLanguageTests(TestCase):
    """The invitation email goes out in the language chosen in the form, else the organization's."""

    def setUp(self):
        ensure_permission_groups()
        organization = OrganizationFactory(default_language='de')
        admin = User.objects.create_user(username='admin', email='admin@example.com', password='pw')
        UserProfile.objects.create(user=admin, organization=organization)
        assign_organization_admin(admin)
        self.client.force_login(admin)
        self.languages = []

    def invite(self, language):
        def capture(**kwargs):
            self.languages.append(translation.get_language())

        with patch('accounts.invitation_views.send_email', side_effect=capture):
            self.client.post(reverse('send_invitation'), {'email': 'new@example.com', 'language': language})

    def test_the_chosen_language_wins(self):
        self.invite('de-informal')

        self.assertEqual(self.languages, ['de-informal'])

    def test_without_a_choice_the_organizations_language(self):
        self.invite('')

        self.assertEqual(self.languages, ['de'])
