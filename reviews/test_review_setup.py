from django.test import TestCase

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory
from accounts.models import ReviewSetup, SetupReviewer
from core.factories import OrganizationFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.factories import ReviewCycleFactory, ReviewerTokenFactory
from reviews.setup import review_setup, save_review_setup

ALL_FLAGS = {'include_self': True, 'include_manager': True, 'include_peer': True, 'include_direct_report': True}


class SetupTestCase(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.default = QuestionnaireFactory(organization=self.org, is_default=True, name='Current review')
        self.alex = self.person('Alex Morgan', 'alex@acme.example')
        self.blair = self.person('Blair Chen', 'blair@acme.example')
        self.casey = self.person('Casey Jones', 'casey@acme.example')

    def person(self, name, email, **kwargs):
        return RevieweeFactory(organization=self.org, name=name, email=email, **kwargs)

    def save(self, people=None, emails=None, questionnaire=None, flags=None):
        return save_review_setup(
            self.alex, questionnaire or self.default, flags or ALL_FLAGS,
            {'manager': [], 'peer': [], 'direct_report': [], **(people or {})},
            {'manager': [], 'peer': [], 'direct_report': [], **(emails or {})},
        )

    def put_alex_under_blair_in_the_chart(self):
        unit = OrgUnitFactory(organization=self.org)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.blair, row=0, col=0)
        OrgUnitMembershipFactory(unit=unit, reviewee=self.alex, row=1, col=0)

    def previous_cycle(self, questionnaire=None, peer_email='dana@acme.example'):
        cycle = ReviewCycleFactory(reviewee=self.alex, questionnaire=questionnaire or self.default)
        ReviewerTokenFactory(cycle=cycle, category='peer', reviewer_email=peer_email)
        return cycle


class ReviewSetupOrderTests(SetupTestCase):
    def test_saved_list_wins_over_the_org_chart(self):
        self.put_alex_under_blair_in_the_chart()
        self.previous_cycle()
        self.save(people={'peer': [self.casey]})
        setup = review_setup(self.alex)
        self.assertEqual(setup.source, 'saved')
        self.assertEqual(setup.people['peer'], [self.casey])
        self.assertEqual(setup.people['manager'], [])

    def test_org_chart_wins_over_the_previous_review(self):
        self.put_alex_under_blair_in_the_chart()
        self.previous_cycle()
        setup = review_setup(self.alex)
        self.assertEqual(setup.source, 'chart')
        self.assertEqual(setup.people['manager'], [self.blair])

    def test_previous_review_when_the_chart_knows_nobody(self):
        other = QuestionnaireFactory(organization=self.org, name='Annual review')
        self.previous_cycle(questionnaire=other)
        setup = review_setup(self.alex)
        self.assertEqual(setup.source, 'previous')
        self.assertEqual(setup.emails['peer'], ['dana@acme.example'])
        self.assertEqual(setup.questionnaire, other)

    def test_empty_without_any_data(self):
        setup = review_setup(self.alex)
        self.assertEqual(setup.source, 'empty')
        self.assertEqual(setup.flags, ALL_FLAGS)
        self.assertEqual(setup.questionnaire, self.default)

    def test_archived_questionnaire_falls_back_to_the_default(self):
        archived = QuestionnaireFactory(organization=self.org, name='Old review', is_active=False)
        self.save(questionnaire=archived, people={'peer': [self.casey]})
        self.assertEqual(review_setup(self.alex).questionnaire, self.default)

    def test_deactivated_person_is_left_out_of_a_saved_list(self):
        self.save(people={'peer': [self.casey, self.blair]})
        self.casey.is_active = False
        self.casey.save()
        self.assertEqual(review_setup(self.alex).people['peer'], [self.blair])

    def test_email_of_a_known_person_shows_as_that_person(self):
        self.previous_cycle(peer_email='Casey@acme.example')
        setup = review_setup(self.alex)
        self.assertEqual(setup.people['peer'], [self.casey])
        self.assertEqual(setup.emails['peer'], [])

    def test_forced_chart_source_ignores_the_saved_list(self):
        self.put_alex_under_blair_in_the_chart()
        self.save(people={'peer': [self.casey]})
        setup = review_setup(self.alex, source='chart')
        self.assertEqual(setup.source, 'chart')
        self.assertEqual(setup.people['manager'], [self.blair])
        self.assertEqual(setup.people['peer'], [])


class SaveReviewSetupTests(SetupTestCase):
    def test_save_replaces_the_rows(self):
        self.save(people={'peer': [self.casey]}, emails={'manager': ['Dana@acme.example']})
        self.save(people={'manager': [self.blair]})
        setup = ReviewSetup.objects.get(reviewee=self.alex)
        rows = [(r.category, r.person, r.email) for r in setup.reviewers.all()]
        self.assertEqual(rows, [('manager', self.blair, '')])

    def test_person_in_two_categories_is_kept_once_as_manager(self):
        self.save(people={'manager': [self.blair], 'peer': [self.blair, self.casey], 'direct_report': [self.blair]})
        rows = {(r.category, r.person) for r in SetupReviewer.objects.all()}
        self.assertEqual(rows, {('manager', self.blair), ('peer', self.casey)})

    def test_the_reviewee_is_never_their_own_reviewer(self):
        self.save(people={'peer': [self.alex]}, emails={'peer': ['ALEX@acme.example']})
        self.assertFalse(SetupReviewer.objects.exists())

    def test_email_of_a_person_in_blik_is_saved_as_that_person(self):
        self.save(emails={'peer': ['Casey@acme.example', 'dana@acme.example']})
        rows = {(r.category, r.person, r.email) for r in SetupReviewer.objects.all()}
        self.assertEqual(rows, {('peer', self.casey, ''), ('peer', None, 'dana@acme.example')})

    def test_email_assignments_have_only_the_asked_categories(self):
        self.save(people={'peer': [self.casey]}, emails={'manager': ['dana@acme.example']})
        setup = review_setup(self.alex)
        self.assertEqual(
            setup.email_assignments(['self', 'peer']),
            {'self': ['alex@acme.example'], 'peer': ['casey@acme.example']},
        )
