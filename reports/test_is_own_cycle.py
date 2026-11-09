from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import Reviewee, UserProfile
from core.models import Organization
from questionnaires.models import Questionnaire
from reviews.models import ReviewCycle

from .views import is_own_cycle


class IsOwnCycleTests(TestCase):
    def setUp(self):
        self.acme = Organization.objects.create(name='Acme', email='org@acme.example')
        self.other = Organization.objects.create(name='Other', email='org@other.example')
        self.user = User.objects.create_user(username='dana', email='Dana@shared.example', password='pw')
        UserProfile.objects.create(user=self.user, organization=self.acme)

    def cycle_in(self, organization):
        reviewee = Reviewee.objects.create(name='Dana', email='dana@shared.example', organization=organization)
        questionnaire = Questionnaire.objects.create(name='Q', organization=organization)
        return ReviewCycle.objects.create(reviewee=reviewee, questionnaire=questionnaire)

    def test_own_email_in_own_organization(self):
        self.assertTrue(is_own_cycle(self.user, self.cycle_in(self.acme)))

    def test_same_email_in_another_organization_is_not_own(self):
        self.assertFalse(is_own_cycle(self.user, self.cycle_in(self.other)))
