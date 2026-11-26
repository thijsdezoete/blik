from django.test import TestCase
from django.urls import reverse

from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory
from accounts.models import OrgUnitMembership
from accounts.permissions import assign_organization_admin, assign_organization_member
from questionnaires.factories import QuestionnaireFactory
from reviews.models import ReviewCycle
from reviews.services import derive_reviewers


class RevieweeDetailChartTests(TestCase):
    def setUp(self):
        profile = UserProfileFactory()
        self.org = profile.organization
        assign_organization_admin(profile.user)
        self.client.force_login(profile.user)
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True)
        self.alex = self.person('Alex Morgan', 'alex@acme.example', department='Product Engineering')
        self.blair = self.person('Blair Chen', 'blair@acme.example')
        self.sara = self.person('Sara Koster', 'sara@acme.example')
        self.url = reverse('reviewee_detail', args=[self.alex.uuid])
        self.relation_url = reverse('reviewee_chart_relation', args=[self.alex.uuid])

    def person(self, name, email, department=''):
        return RevieweeFactory(organization=self.org, name=name, email=email, department=department)

    def unit(self, name, managers=(), members=()):
        unit = OrgUnitFactory(organization=self.org, name=name)
        for col, manager in enumerate(managers):
            OrgUnitMembershipFactory(unit=unit, reviewee=manager, row=0, col=col)
        for col, member in enumerate(members):
            OrgUnitMembershipFactory(unit=unit, reviewee=member, row=1, col=col)
        return unit

    def post(self, action='save', **fields):
        return self.client.post(self.url, {
            'action': action, 'questionnaire': self.questionnaire.id, 'categories_submitted': '1',
            'include_self': 'on', 'include_manager': 'on', 'include_direct_report': 'on', **fields,
        })

    def test_place_puts_the_reviewee_under_the_posted_manager(self):
        self.post(manager_reviewees=[str(self.blair.uuid)], **{f'chart_manager_{self.blair.uuid}': 'place'})

        self.assertEqual(derive_reviewers(self.alex)['manager'], [self.blair])

    def test_two_new_managers_are_both_placed(self):
        self.post(manager_reviewees=[str(self.blair.uuid), str(self.sara.uuid)],
                  **{f'chart_manager_{self.blair.uuid}': 'place', f'chart_manager_{self.sara.uuid}': 'place'})

        self.assertEqual(set(derive_reviewers(self.alex)['manager']), {self.blair, self.sara})

    def test_move_takes_the_direct_report_out_of_the_old_unit(self):
        old = self.unit('Platform', managers=[self.sara], members=[self.blair])

        self.post('start', direct_report_reviewees=[str(self.blair.uuid)],
                  **{f'chart_direct_report_{self.blair.uuid}': 'move'})

        self.assertEqual(derive_reviewers(self.blair)['manager'], [self.alex])
        self.assertFalse(old.memberships.filter(reviewee=self.blair).exists())
        self.assertTrue(ReviewCycle.objects.filter(reviewee=self.alex).exists())

    def test_no_choice_leaves_the_chart_alone(self):
        self.post(manager_reviewees=[str(self.blair.uuid)])

        self.assertFalse(OrgUnitMembership.objects.exists())

    def test_choice_of_a_user_without_the_permission_is_ignored(self):
        own = UserProfileFactory(organization=self.org, user__email='alex@acme.example')
        assign_organization_member(own.user)
        self.client.force_login(own.user)

        response = self.post(manager_emails='blair@acme.example', **{f'chart_manager_{self.blair.uuid}': 'place'})

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(OrgUnitMembership.objects.exists())

    def test_choice_for_a_person_not_in_the_list_is_ignored(self):
        self.post(peer_reviewees=[str(self.blair.uuid)], **{f'chart_manager_{self.blair.uuid}': 'place'})

        self.assertFalse(OrgUnitMembership.objects.exists())

    def test_place_is_ignored_when_the_chart_names_another_manager(self):
        self.unit('Product Engineering', managers=[self.sara], members=[self.alex])

        self.post(manager_reviewees=[str(self.blair.uuid)], **{f'chart_manager_{self.blair.uuid}': 'place'})

        self.assertEqual(derive_reviewers(self.alex)['manager'], [self.sara])
        self.assertFalse(OrgUnitMembership.objects.filter(reviewee=self.blair).exists())

    def test_move_or_both_is_ignored_when_the_person_is_not_in_the_chart(self):
        for value in ('move', 'both'):
            with self.subTest(value=value):
                self.post(manager_reviewees=[str(self.blair.uuid)], **{f'chart_manager_{self.blair.uuid}': value})

                self.assertFalse(OrgUnitMembership.objects.exists())

    def test_relation_endpoint_needs_the_permission(self):
        own = UserProfileFactory(organization=self.org, user__email='alex@acme.example')
        assign_organization_member(own.user)
        self.client.force_login(own.user)

        response = self.client.get(self.relation_url, {'person': self.blair.uuid, 'category': 'manager'})

        self.assertEqual(response.status_code, 403)
        self.assertNotIn('state', response.json())

    def test_relation_endpoint_for_a_direct_report_puts_the_reviewee_on_top(self):
        self.unit('Growth', managers=[self.alex])
        self.unit('Design', managers=[self.blair])

        data = self.client.get(self.relation_url, {'person': self.blair.uuid, 'category': 'direct_report'}).json()

        self.assertEqual((data['state'], data['unit_name'], data['new_unit']), ('missing', 'Growth', False))

    def test_relation_endpoint_names_the_other_managers_of_the_unit(self):
        dana = self.person('Dana Visser', 'dana@acme.example')
        self.unit('Design', managers=[self.blair, dana])

        data = self.client.get(self.relation_url, {'person': self.blair.uuid, 'category': 'manager'}).json()

        self.assertEqual((data['state'], data['unit_name'], data['also_managers']), ('missing', 'Design', ['Dana Visser']))
        self.assertIn('Dana Visser', data['html'])
