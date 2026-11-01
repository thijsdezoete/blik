from django.test import TestCase

from accounts.factories import RevieweeFactory
from accounts.models import OrgUnit, OrgUnitMembership, Reviewee
from django.urls import reverse

from accounts.org_import import guess_mapping, import_org_chart, map_rows, read_table, rows_from_csv
from core.factories import OrganizationFactory
from reviews.services import derive_reviewers

CSV = """name;email;department;manager_email
Prof Ada;ada@uni.example;Chair of Physics;
Hank Head;hank@uni.example;Optics;ada@uni.example
Hilde Head;hilde@uni.example;Lasers;ada@uni.example
Sam Staff;sam@uni.example;Optics;hank@uni.example
Sue Staff;sue@uni.example;Optics;hank@uni.example
"""


class ImportOrgChartTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()

    def _import(self, text=CSV):
        rows, errors = rows_from_csv(text.encode())
        self.assertEqual(errors, [])
        return import_org_chart(self.org, rows)

    def _members(self, unit_name, role):
        return sorted(
            OrgUnitMembership.objects.filter(unit__name=unit_name, role=role)
            .values_list('reviewee__email', flat=True)
        )

    def test_one_unit_per_manager_stacked_by_reporting_line(self):
        stats, errors = self._import()

        self.assertEqual(errors, [])
        self.assertEqual(stats, {'created': 5, 'updated': 0, 'units': 2})
        self.assertEqual(self._members('Chair of Physics', 'manager'), ['ada@uni.example'])
        self.assertEqual(self._members('Chair of Physics', 'member'), ['hank@uni.example', 'hilde@uni.example'])
        self.assertEqual(self._members('Optics', 'manager'), ['hank@uni.example'])
        self.assertEqual(self._members('Optics', 'member'), ['sam@uni.example', 'sue@uni.example'])

        hank = derive_reviewers(Reviewee.objects.get(email='hank@uni.example'))
        self.assertEqual([r.email for r in hank['manager']], ['ada@uni.example'])
        self.assertEqual([r.email for r in hank['peer']], ['hilde@uni.example'])
        self.assertEqual([r.email for r in hank['direct_report']], ['sam@uni.example', 'sue@uni.example'])

    def test_import_again_replaces_the_chart_and_updates_people(self):
        RevieweeFactory(organization=self.org, email='sam@uni.example', name='Old name')
        self._import()

        stats, errors = self._import(CSV.replace('Sue Staff;sue@uni.example;Optics;hank@uni.example\n', ''))

        self.assertEqual(errors, [])
        self.assertEqual(stats['updated'], 4)
        self.assertEqual(OrgUnit.objects.filter(organization=self.org).count(), 2)
        self.assertEqual(self._members('Optics', 'member'), ['sam@uni.example'])
        self.assertEqual(Reviewee.objects.get(email='sam@uni.example').name, 'Sam Staff')
        self.assertFalse(OrgUnitMembership.objects.filter(reviewee__email='sue@uni.example').exists())

    def test_errors_write_nothing(self):
        text = CSV + 'Max Mystery;max@uni.example;Optics;nobody@uni.example\nBad;not-an-email;;\n'

        stats, errors = self._import(text)

        self.assertIsNone(stats)
        self.assertEqual(len(errors), 2)
        self.assertIn('nobody@uni.example', errors[1])
        self.assertFalse(Reviewee.objects.filter(organization=self.org).exists())

    def test_two_managers_with_the_same_department_get_distinct_units(self):
        text = CSV + 'Olga Other;olga@uni.example;Optics;ada@uni.example\nOtto;otto@uni.example;Optics;olga@uni.example\n'

        stats, errors = self._import(text)

        self.assertEqual(errors, [])
        self.assertTrue(OrgUnit.objects.filter(name='Optics (Olga Other)').exists())

    def test_comma_separated_with_bom_and_capitalised_headers(self):
        headers, rows = read_table('\ufeffName,Email,Department,Manager_Email\nA,a@x.example,,\n'.encode())

        self.assertEqual(headers, ['Name', 'Email', 'Department', 'Manager_Email'])
        self.assertEqual(rows, [['A', 'a@x.example', '', '']])


class MappingTests(TestCase):
    def test_guesses_hr_export_headers(self):
        headers = ['Vorname', 'Nachname', 'Manager E-Mail', 'E-Mail', 'Abteilung', 'Start date']

        self.assertEqual(guess_mapping(headers), {
            'manager': 2, 'email': 3, 'first_name': 0, 'last_name': 1, 'name': None, 'department': 4,
        })

    def test_first_and_last_name_and_manager_by_name(self):
        headers = ['First', 'Last', 'Mail', 'Boss']
        rows = [['Ada', 'Lovelace', 'ada@x.example', ''], ['Bob', 'Byte', 'bob@x.example', 'Ada Lovelace']]
        mapping = {'first_name': 0, 'last_name': 1, 'email': 2, 'manager': 3}

        mapped, errors = map_rows(headers, rows, mapping)

        self.assertEqual(errors, [])
        self.assertEqual(mapped[1], {'name': 'Bob Byte', 'email': 'bob@x.example', 'department': '',
                                     'manager_email': 'ada@x.example'})

    def test_unknown_and_ambiguous_manager_names_are_errors(self):
        headers = ['Name', 'Email', 'Manager']
        rows = [['Ann', 'a1@x.example', ''], ['Ann', 'a2@x.example', ''],
                ['Bo', 'bo@x.example', 'Ann'], ['Cy', 'cy@x.example', 'Nobody']]

        _mapped, errors = map_rows(headers, rows, {'name': 0, 'email': 1, 'manager': 2})

        self.assertEqual(len(errors), 2)
        self.assertIn('Line 4', errors[0])
        self.assertIn('Nobody', errors[1])

    def test_email_column_is_required(self):
        _mapped, errors = map_rows(['Name'], [['Ann']], {'name': 0})

        self.assertEqual(len(errors), 1)


class ImportViewTests(TestCase):
    def test_upload_then_map_columns_then_import(self):
        from accounts.factories import UserProfileFactory
        from accounts.permissions import assign_organization_admin, ensure_permission_groups
        from core.factories import UserFactory
        from django.core.files.uploadedfile import SimpleUploadedFile

        ensure_permission_groups()
        org = OrganizationFactory()
        user = UserFactory()
        UserProfileFactory(user=user, organization=org)
        assign_organization_admin(user)
        self.client.force_login(user)
        csv = 'Full name;Work email;Team;Reports to\nAda;ada@x.example;Board;\nBob;bob@x.example;Tech;Ada\n'

        upload = self.client.post(reverse('org_chart_import'),
                                  {'file': SimpleUploadedFile('people.csv', csv.encode())})
        page = self.client.get(reverse('org_chart_import_map'))
        done = self.client.post(reverse('org_chart_import_map'),
                                {'name': '0', 'email': '1', 'department': '2', 'manager': '3'})

        self.assertRedirects(upload, reverse('org_chart_import_map'), fetch_redirect_response=False)
        self.assertEqual([f[2] for f in page.context['fields']], [0, None, None, 1, 2, 3])
        self.assertRedirects(done, reverse('org_chart'))
        self.assertEqual(
            list(OrgUnitMembership.objects.filter(unit__organization=org).values_list('unit__name', 'reviewee__email', 'role')),
            [('Board', 'ada@x.example', 'manager'), ('Board', 'bob@x.example', 'member')],
        )
        self.assertNotIn('org_import', self.client.session)
