import uuid
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.factories import RevieweeFactory, UserProfileFactory
from accounts.models import Reviewee
from accounts.permissions import assign_organization_admin, assign_organization_member
from core.factories import OrganizationFactory
from questionnaires.factories import QuestionnaireFactory
from reports.models import Report
from reviews.factories import ReviewCycleFactory


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.hrefs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.append(dict(attrs).get('href', ''))


class RevieweeOverviewTests(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.user = self.profile.user
        self.org = self.profile.organization
        assign_organization_admin(self.user)
        Reviewee.objects.filter(organization=self.org, email=self.user.email).update(is_active=False)
        self.client.force_login(self.user)
        self.url = reverse('reviewee_list')
        self.questionnaire = QuestionnaireFactory(organization=self.org, is_default=True, name='Current review')
        self.archived = QuestionnaireFactory(organization=self.org, is_active=False, name='Archived review')
        self.alex = RevieweeFactory(organization=self.org, name='Alex Morgan', email='alex@example.test', department='People & Culture')
        self.blair = RevieweeFactory(organization=self.org, name='Blair Chen', email='blair@example.test', department='Engineering')
        self.casey = RevieweeFactory(organization=self.org, name='Casey Jones', email='casey@example.test', department='People & Culture')
        self.dana = RevieweeFactory(organization=self.org, name='Dana Park', email='dana@example.test', department='')
        old = ReviewCycleFactory(reviewee=self.alex, questionnaire=self.questionnaire, status='completed')
        self.report(old, 2, 4)
        self.active = ReviewCycleFactory(reviewee=self.alex, questionnaire=self.archived)
        complete = ReviewCycleFactory(reviewee=self.blair, questionnaire=self.questionnaire, status='completed')
        self.report(complete, 4, 3)
        ReviewCycleFactory(reviewee=self.dana, questionnaire=self.questionnaire, status='completed')

    def report(self, cycle, own, others, count=3):
        return Report.objects.create(cycle=cycle, access_token=uuid.uuid4(), report_data={
            'by_section': {'1': {'questions': {'1': {'question_type': 'rating', 'by_category': {
                'self': {'count': 1, 'avg': own}, 'peer': {'count': count, 'avg': others},
            }}}}},
        })

    def people(self, response):
        return [item['reviewee'] for item in response.context['reviewees_with_latest']]

    def test_search_matches_name_email_and_department(self):
        for query, expected in [('aLeX', [self.alex]), ('blair@example.test', [self.blair]),
                                ('People & Culture', [self.alex, self.casey])]:
            with self.subTest(query=query):
                response = self.client.get(self.url, {'q': query})
                self.assertEqual(self.people(response), expected)

    def test_stages_are_exclusive_and_counts_follow_filters(self):
        expected = {'not_started': [self.casey], 'active': [self.alex], 'completed': [self.blair, self.dana]}
        for stage, people in expected.items():
            with self.subTest(stage=stage):
                response = self.client.get(self.url, {'stage': stage})
                self.assertEqual(self.people(response), people)
                self.assertEqual(response.context['total_count'], 4)
        response = self.client.get(self.url, {'department': 'People & Culture'})
        self.assertEqual(response.context['stage_counts'], {'not_started': 1, 'active': 1, 'completed': 0})
        self.assertEqual(response.context['total_count'], 2)

    def test_questionnaire_filter_uses_latest_cycle_including_archived(self):
        response = self.client.get(self.url, {'questionnaire': str(self.archived.uuid)})
        self.assertEqual(self.people(response), [self.alex])
        response = self.client.get(self.url, {'questionnaire': str(self.questionnaire.uuid)})
        self.assertEqual(self.people(response), [self.blair, self.dana])

    def test_scope_excludes_other_org_inactive_and_anonymized_people(self):
        foreign_org = OrganizationFactory()
        foreign_q = QuestionnaireFactory(organization=foreign_org, name='Foreign questionnaire')
        foreign = RevieweeFactory(organization=foreign_org, name='Foreign person', department='Secret department')
        ReviewCycleFactory(reviewee=foreign, questionnaire=foreign_q)
        RevieweeFactory(organization=self.org, is_active=False, name='Inactive person')
        RevieweeFactory(organization=self.org, email='gone@deleted.invalid', name='Anonymized person')
        response = self.client.get(self.url)
        self.assertEqual(response.context['total_count'], 4)
        for hidden in ['Foreign person', 'Foreign questionnaire', 'Secret department', 'Inactive person', 'Anonymized person']:
            self.assertNotContains(response, hidden)
        self.assertEqual(self.people(self.client.get(self.url, {'questionnaire': str(foreign_q.uuid)})), [])

    def test_invalid_filters_and_page_size_fall_back(self):
        response = self.client.get(self.url, {'stage': 'bad', 'sort': 'bad', 'questionnaire': 'not-a-uuid', 'per_page': '-1', 'page': 'bad'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stage'], '')
        self.assertEqual(response.context['sort'], 'name')
        self.assertEqual(response.context['questionnaire_filter'], '')
        self.assertEqual(response.context['per_page'], 25)

    def test_gap_sort_still_uses_largest_distance_and_anonymity(self):
        response = self.client.get(self.url, {'sort': 'gap'})
        self.assertEqual(self.people(response)[:2], [self.alex, self.blair])
        rows = response.context['reviewees_with_latest']
        self.assertEqual([row['gap'] for row in rows[:2]], [-2, 1])
        report = Report.objects.get(cycle__reviewee=self.blair)
        report.report_data['by_section']['1']['questions']['1']['by_category']['peer']['count'] = 1
        report.save()
        response = self.client.get(self.url, {'q': 'Blair', 'sort': 'gap'})
        self.assertIsNone(response.context['reviewees_with_latest'][0]['gap'])

    def test_archived_previous_questionnaire_defaults_to_active_choice(self):
        response = self.client.get(self.url, {'q': 'Alex'})
        item = response.context['reviewees_with_latest'][0]
        self.assertEqual(item['latest_questionnaire'], self.archived)
        self.assertEqual(item['selected_questionnaire'], self.questionnaire)
        self.assertEqual(item['active_cycle'], self.active)
        self.assertIsNotNone(item['latest_completed_report'])

    def test_pagination_links_preserve_encoded_filters(self):
        Reviewee.objects.bulk_create([
            Reviewee(organization=self.org, name=f'Person {i:02}', email=f'p{i}@example.test', department='Research & Development')
            for i in range(26)
        ])
        params = {'q': 'Person', 'department': 'Research & Development', 'stage': 'not_started', 'sort': 'name_desc', 'per_page': 25}
        response = self.client.get(self.url, params)
        links = Links(response.content.decode()).hrefs
        page_two = [parse_qs(urlsplit(unescape(href)).query) for href in links if parse_qs(urlsplit(unescape(href)).query).get('page') == ['2']]
        self.assertTrue(page_two)
        for query in page_two:
            for key, value in params.items():
                self.assertEqual(query[key], [str(value)])
        response = self.client.get(self.url, {**params, 'page': 2})
        self.assertEqual(len(self.people(response)), 1)

    def test_filtered_empty_state_preserves_controls(self):
        response = self.client.get(self.url, {'q': 'No matches'})
        self.assertContains(response, 'No people match these filters.')
        self.assertContains(response, 'Clear filters')
        self.assertContains(response, 'value="No matches"')
        self.assertNotContains(response, 'Add your first reviewee')

    def test_members_do_not_get_management_actions(self):
        assign_organization_member(self.user)
        response = self.client.get(self.url)
        for route in ['quick_cycle_create', 'reviewee_edit', 'reviewee_delete']:
            self.assertNotContains(response, reverse(route, args=[self.alex.uuid]))

    def test_query_count_does_not_grow_per_row(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)
        for i in range(15):
            person = RevieweeFactory(organization=self.org, name=f'Person {i}')
            ReviewCycleFactory(reviewee=person, questionnaire=self.questionnaire)
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url)
        self.assertLessEqual(len(large), len(small) + 2)
