from django.contrib.messages import get_messages
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.factories import (
    OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory, UserProfileFactory,
)
from accounts.chart_link import chart_relation, chart_shown
from accounts.models import OrgUnitMembership
from blik.test_org_chart import _grant_manage
from core.factories import OrganizationFactory, UserFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.setup import save_review_setup

SKIPPED = 'Some people were not placed: the org chart or a reviewer list changed since the page was loaded.'
ALL_FLAGS = {'include_self': True, 'include_manager': True, 'include_peer': True, 'include_direct_report': True}


class OrgChartPlaceSetup(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.user = UserFactory(username='place_admin')
        UserProfileFactory(user=self.user, organization=self.org)
        _grant_manage(self.user)
        self.client.force_login(self.user)
        self.questionnaire = QuestionnaireFactory(organization=self.org)
        self.tom = self.person('Tom Bakker', 'tom@acme.example', 'Product Engineering')
        self.sara = self.person('Sara Koster', 'sara@acme.example', 'Design')
        self.maya = self.person('Maya Jansen', 'maya@acme.example', 'Product Engineering')
        self.ivo = self.person('Ivo Peters', 'ivo@acme.example', 'Design')
        self.unit = OrgUnitFactory(organization=self.org, name='Product Engineering')
        OrgUnitMembershipFactory(unit=self.unit, reviewee=self.tom, row=0, col=0)
        self.name_manager(self.maya, self.tom)
        self.name_manager(self.ivo, self.sara)

    def person(self, name, email, department):
        return RevieweeFactory(organization=self.org, name=name, email=email, department=department)

    def name_manager(self, person, manager):
        save_review_setup(person, self.questionnaire, ALL_FLAGS,
                          {'manager': [manager], 'peer': [], 'direct_report': []},
                          {'manager': [], 'peer': [], 'direct_report': []})

    def is_member(self, person):
        return OrgUnitMembership.objects.filter(reviewee=person, role=OrgUnitMembership.MEMBER).exists()

    def lines(self, *pairs):
        """The fields the notice posts for these (person, manager) lines, with the text of what it showed."""
        return {'person': [str(person.uuid) for person, _manager in pairs],
                'manager': [str(manager.uuid) for _person, manager in pairs],
                'seen': [chart_shown(chart_relation(manager, person)) for person, manager in pairs]}

    def place(self, *pairs):
        return self.client.post(reverse('org_chart_place'), self.lines(*pairs))

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]


class OrgChartPlaceTests(OrgChartPlaceSetup):
    def test_place_one_person(self):
        response = self.place((self.maya, self.tom))

        self.assertRedirects(response, reverse('org_chart'))
        self.assertTrue(self.unit.memberships.filter(reviewee=self.maya, role=OrgUnitMembership.MEMBER).exists())
        self.assertFalse(self.is_member(self.ivo))
        self.assertEqual(self.messages(response), ['1 person placed in the org chart.'])

    def test_place_all(self):
        response = self.place((self.maya, self.tom), (self.ivo, self.sara))

        self.assertRedirects(response, reverse('org_chart'))
        self.assertTrue(self.is_member(self.maya))
        self.assertTrue(self.is_member(self.ivo))
        self.assertEqual(self.messages(response), ['2 people placed in the org chart.'])

    def test_member_cannot_place(self):
        member = UserFactory(username='place_member')
        UserProfileFactory(user=member, organization=self.org)
        self.client.force_login(member)

        response = self.place((self.maya, self.tom), (self.ivo, self.sara))

        self.assertRedirects(response, reverse('org_chart'))
        self.assertFalse(self.is_member(self.maya))
        self.assertFalse(self.is_member(self.ivo))

    def test_person_who_is_no_longer_unplaced_is_skipped(self):
        shown = self.lines((self.maya, self.tom))
        OrgUnitMembershipFactory(unit=self.unit, reviewee=self.maya, row=1, col=0)

        response = self.client.post(reverse('org_chart_place'), shown)

        self.assertRedirects(response, reverse('org_chart'))
        self.assertEqual(OrgUnitMembership.objects.filter(reviewee=self.maya).count(), 1)
        self.assertEqual(self.messages(response), ['0 people placed in the org chart.', SKIPPED])

    def test_line_is_skipped_when_the_list_names_another_manager_than_the_page_showed(self):
        shown = self.lines((self.maya, self.tom))
        self.name_manager(self.maya, self.sara)

        response = self.client.post(reverse('org_chart_place'), shown)

        self.assertFalse(self.is_member(self.maya))
        self.assertEqual(self.messages(response), ['0 people placed in the org chart.', SKIPPED])

    def test_line_is_skipped_when_the_unit_got_another_manager_after_the_page_was_loaded(self):
        shown = self.lines((self.maya, self.tom))
        lena = self.person('Lena Visser', 'lena@acme.example', 'Product Engineering')
        OrgUnitMembershipFactory(unit=self.unit, reviewee=lena, row=0, col=1)

        response = self.client.post(reverse('org_chart_place'), shown)

        self.assertFalse(self.is_member(self.maya))
        self.assertEqual(self.messages(response), ['0 people placed in the org chart.', SKIPPED])

    def test_place_all_places_only_the_people_the_page_listed(self):
        page = self.client.get(reverse('org_chart'))
        listed = [(line['person'], line['manager']) for line in page.context['placeable']]
        noor = self.person('Noor Smit', 'noor@acme.example', 'Product Engineering')
        self.name_manager(noor, self.tom)

        response = self.place(*listed)

        self.assertTrue(self.is_member(self.maya))
        self.assertTrue(self.is_member(self.ivo))
        self.assertFalse(self.is_member(noor))
        self.assertEqual(self.messages(response), ['2 people placed in the org chart.'])

    def test_place_all_with_two_people_under_a_manager_without_unit_places_both(self):
        noor = self.person('Noor Smit', 'noor@acme.example', 'Design')
        self.name_manager(noor, self.sara)

        response = self.place((self.ivo, self.sara), (noor, self.sara))

        self.assertTrue(self.is_member(self.ivo))
        self.assertTrue(self.is_member(noor))
        self.assertEqual(self.messages(response), ['2 people placed in the org chart.'])


class OrgChartNoticeTests(OrgChartPlaceSetup):
    def test_line_names_the_other_managers_of_the_unit(self):
        lena = self.person('Lena Visser', 'lena@acme.example', 'Product Engineering')
        OrgUnitMembershipFactory(unit=self.unit, reviewee=lena, row=0, col=1)

        response = self.client.get(reverse('org_chart'))

        line = next(i for i in response.context['placeable'] if i['person'] == self.maya)
        self.assertEqual(line['also_names'], 'Lena Visser')
        self.assertEqual(line['seen'], chart_shown(chart_relation(self.tom, self.maya)))
        self.assertContains(response, 'Lena Visser also manages this unit.')

    def test_page_does_not_query_per_person_without_a_list_or_a_review(self):
        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse('org_chart'))
            return len(captured)

        before = queries()
        for n in range(10):
            self.person(f'Person {n:02}', f'p{n}@acme.example', 'Design')

        self.assertEqual(queries(), before)

    def test_member_gets_no_notice(self):
        member = UserFactory(username='notice_member')
        UserProfileFactory(user=member, organization=self.org)
        self.client.force_login(member)

        response = self.client.get(reverse('org_chart'))

        self.assertNotIn('placeable', response.context)
