from django.test import TestCase

from accounts.factories import RevieweeFactory
from accounts.models import OrgUnit, OrgUnitMembership, Reviewee
from django.urls import reverse

from accounts.org_import import guess_mapping, import_org_chart, map_rows, read_table, rows_from_csv
from core.factories import OrganizationFactory
from reviews.services import derive_reviewers

CSV = """name;email;department;manager_email
Owner Ada;ada@acme.example;Engineering;
Hank Head;hank@acme.example;Platform;ada@acme.example
Hilde Head;hilde@acme.example;Mobile;ada@acme.example
Sam Staff;sam@acme.example;Platform;hank@acme.example
Sue Staff;sue@acme.example;Platform;hank@acme.example
"""


class ImportOrgChartTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()

    def _import(self, text=CSV, **options):
        rows, errors = rows_from_csv(text.encode())
        self.assertEqual(errors, [])
        return import_org_chart(self.org, rows, **options)

    def _members(self, unit_name, role):
        return sorted(
            OrgUnitMembership.objects.filter(unit__name=unit_name, role=role)
            .values_list('reviewee__email', flat=True)
        )

    def test_one_unit_per_manager_stacked_by_reporting_line(self):
        stats, errors = self._import()

        self.assertEqual(errors, [])
        self.assertEqual(len(stats['created']), 5)
        self.assertEqual(stats['units_created'], ['Engineering', 'Platform'])
        self.assertEqual(self._members('Engineering', 'manager'), ['ada@acme.example'])
        self.assertEqual(self._members('Engineering', 'member'), ['hank@acme.example', 'hilde@acme.example'])
        self.assertEqual(self._members('Platform', 'manager'), ['hank@acme.example'])
        self.assertEqual(self._members('Platform', 'member'), ['sam@acme.example', 'sue@acme.example'])

        hank = derive_reviewers(Reviewee.objects.get(email='hank@acme.example'))
        self.assertEqual([r.email for r in hank['manager']], ['ada@acme.example'])
        self.assertEqual([r.email for r in hank['peer']], ['hilde@acme.example'])
        self.assertEqual([r.email for r in hank['direct_report']], ['sam@acme.example', 'sue@acme.example'])

    def test_import_again_keeps_the_units_and_moves_only_who_changed(self):
        RevieweeFactory(organization=self.org, email='sam@acme.example', name='Old name')
        self._import()
        platform = OrgUnit.objects.get(name='Platform')
        OrgUnit.objects.filter(pk=platform.pk).update(name='Platform lab', display_order=7)
        before = list(OrgUnitMembership.objects.filter(unit=platform).values_list('pk', flat=True))

        # Hilde now reports to Hank; nothing else changes.
        stats, errors = self._import(CSV.replace('Mobile;ada@acme.example', 'Mobile;hank@acme.example'))

        self.assertEqual(errors, [])
        self.assertEqual((stats['updated'], stats['unchanged'], stats['units_created'], stats['units_removed']), (5, 4, [], []))
        self.assertEqual(stats['people'], [{
            'name': 'Hilde Head', 'email': 'hilde@acme.example', 'kind': 'moved',
            'before': ['In Engineering, reports to Owner Ada'], 'after': ['In Platform lab, reports to Hank Head']}])
        platform.refresh_from_db()
        self.assertEqual((platform.name, platform.display_order), ('Platform lab', 7))
        self.assertEqual(self._members('Platform lab', 'member'), ['hilde@acme.example', 'sam@acme.example', 'sue@acme.example'])
        self.assertEqual(self._members('Engineering', 'member'), ['hank@acme.example'])
        self.assertTrue(set(before) <= set(OrgUnitMembership.objects.filter(unit=platform).values_list('pk', flat=True)))
        self.assertEqual(Reviewee.objects.get(email='sam@acme.example').name, 'Sam Staff')

    def test_people_not_in_the_file_stay_unless_deactivated(self):
        self._import()
        without_sue = CSV.replace('Sue Staff;sue@acme.example;Platform;hank@acme.example\n', '')

        stats, _errors = self._import(without_sue)

        self.assertEqual([(m['email'], m['before']) for m in stats['missing']],
                         [('sue@acme.example', ['In Platform, reports to Hank Head'])])
        self.assertEqual(self._members('Platform', 'member'), ['sam@acme.example', 'sue@acme.example'])
        self.assertTrue(Reviewee.objects.get(email='sue@acme.example').is_active)

        stats, _errors = self._import(without_sue, deactivate_missing=True)

        self.assertEqual((stats['deactivated'], stats['active']), (1, 4))
        self.assertEqual(self._members('Platform', 'member'), ['sam@acme.example'])
        self.assertFalse(Reviewee.objects.get(email='sue@acme.example').is_active)

    def test_an_admin_who_is_not_in_the_file_is_never_deactivated(self):
        from accounts.factories import UserProfileFactory
        from accounts.permissions import assign_organization_admin, assign_organization_member
        from core.factories import UserFactory

        self._import()
        # Hilde and Sue have an account; Hilde is an admin. The file has neither of them.
        for email, assign in (('hilde@acme.example', assign_organization_admin),
                              ('sue@acme.example', assign_organization_member)):
            user = UserFactory(email=email)
            UserProfileFactory(user=user, organization=self.org)
            assign(user)
        without_both = (CSV.replace('Hilde Head;hilde@acme.example;Mobile;ada@acme.example\n', '')
                        .replace('Sue Staff;sue@acme.example;Platform;hank@acme.example\n', ''))

        stats, errors = self._import(without_both, deactivate_missing=True)

        self.assertEqual(errors, [])
        self.assertEqual([m['email'] for m in stats['missing']], ['sue@acme.example'])
        self.assertEqual(stats['deactivated'], 1)
        self.assertTrue(Reviewee.objects.get(email='hilde@acme.example').is_active)
        self.assertEqual(self._members('Engineering', 'member'), ['hank@acme.example', 'hilde@acme.example'])
        self.assertFalse(Reviewee.objects.get(email='sue@acme.example').is_active)

    def test_dry_run_reports_the_changes_and_writes_nothing(self):
        self._import()
        text = CSV.replace('Sam Staff;sam@acme.example;Platform;hank@acme.example\nSue Staff;sue@acme.example;Platform;hank@acme.example\n',
                           'New Nia;nia@acme.example;Mobile;hilde@acme.example\n')

        stats, errors = self._import(text, deactivate_missing=True, dry_run=True)

        self.assertEqual(errors, [])
        self.assertEqual(stats['created'], ['New Nia'])
        self.assertEqual([(p['kind'], p['before'], p['after']) for p in stats['people'] if p['name'] == 'New Nia'],
                         [('new', [], ['In Mobile, reports to Hilde Head'])])
        self.assertEqual((stats['units_created'], stats['units_removed'], stats['deactivated']), (['Mobile'], ['Platform'], 2))
        self.assertFalse(Reviewee.objects.filter(email='nia@acme.example').exists())
        self.assertEqual(OrgUnit.objects.filter(organization=self.org).count(), 2)
        self.assertTrue(Reviewee.objects.get(email='sue@acme.example').is_active)

    def test_a_new_manager_takes_over_the_unit_of_the_old_one(self):
        self._import()
        platform = OrgUnit.objects.get(name='Platform')

        # Sam becomes head of Platform; Hank reports to Sam.
        stats, errors = self._import(
            'name;email;department;manager_email\n'
            'Owner Ada;ada@acme.example;Engineering;\n'
            'Hilde Head;hilde@acme.example;Mobile;ada@acme.example\n'
            'Sam Staff;sam@acme.example;Platform;ada@acme.example\n'
            'Hank Head;hank@acme.example;Platform;sam@acme.example\n'
            'Sue Staff;sue@acme.example;Platform;sam@acme.example\n')

        self.assertEqual(errors, [])
        self.assertEqual((stats['units_created'], stats['units_removed']), ([], []))
        self.assertEqual(OrgUnit.objects.get(name='Platform').pk, platform.pk)
        self.assertEqual(self._members('Platform', 'manager'), ['sam@acme.example'])
        self.assertEqual(self._members('Platform', 'member'), ['hank@acme.example', 'sue@acme.example'])
        self.assertEqual(self._members('Engineering', 'member'), ['hilde@acme.example', 'sam@acme.example'])

    def test_a_reporting_line_in_a_circle_is_an_error(self):
        stats, errors = self._import('name;email;manager\nA;a@x.example;b@x.example\nB;b@x.example;a@x.example\n')

        self.assertIsNone(stats)
        self.assertEqual(len(errors), 2)

    def test_errors_write_nothing(self):
        text = CSV + 'Max Mystery;max@acme.example;Platform;nobody@acme.example\nBad;not-an-email;;\n'

        stats, errors = self._import(text)

        self.assertIsNone(stats)
        self.assertEqual(len(errors), 2)
        self.assertIn('nobody@acme.example', errors[1])
        self.assertFalse(Reviewee.objects.filter(organization=self.org).exists())

    def test_two_managers_with_the_same_department_get_distinct_units(self):
        text = CSV + 'Olga Other;olga@acme.example;Platform;ada@acme.example\nOtto;otto@acme.example;Platform;olga@acme.example\n'

        stats, errors = self._import(text)

        self.assertEqual(errors, [])
        self.assertTrue(OrgUnit.objects.filter(name='Platform (Olga Other)').exists())

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
        mapping = {'name': '0', 'email': '1', 'department': '2', 'manager': '3'}
        preview = self.client.post(reverse('org_chart_import_map'), mapping)
        saved_by_preview = OrgUnit.objects.filter(organization=org).count()
        # A confirmation for another mapping than the one posted shows the changes again.
        stale = self.client.post(reverse('org_chart_import_map'), {**mapping, 'confirm': '0,,,1,2,'})
        done = self.client.post(reverse('org_chart_import_map'), {**mapping, 'confirm': preview.context['mapping_key']})

        self.assertRedirects(upload, reverse('org_chart_import_map'), fetch_redirect_response=False)
        self.assertEqual([f[2] for f in page.context['fields']], [0, None, None, 1, 2, 3])
        self.assertEqual(preview.context['changes']['created'], ['Ada', 'Bob'])
        self.assertEqual((saved_by_preview, stale.status_code), (0, 200))
        self.assertRedirects(done, reverse('org_chart'))
        self.assertEqual(
            list(OrgUnitMembership.objects.filter(unit__organization=org).values_list('unit__name', 'reviewee__email', 'role')),
            [('Board', 'ada@x.example', 'manager'), ('Board', 'bob@x.example', 'member')],
        )
        self.assertNotIn('org_import', self.client.session)

    def test_a_file_past_the_plan_limit_is_refused_up_front(self):
        from accounts.factories import UserProfileFactory
        from accounts.permissions import assign_organization_admin, ensure_permission_groups
        from core.factories import UserFactory
        from django.core.files.uploadedfile import SimpleUploadedFile
        from subscriptions.testing import subscribe

        ensure_permission_groups()
        org = OrganizationFactory()
        subscribe(org, max_employees=3)  # the admin's own reviewee row and Ada fill two seats
        RevieweeFactory(organization=org, email='ada@x.example')
        user = UserFactory()
        UserProfileFactory(user=user, organization=org)
        assign_organization_admin(user)
        self.client.force_login(user)
        csv = 'Name;Email;Manager\nAda;ada@x.example;\nBob;bob@x.example;Ada\nCy;cy@x.example;Ada\n'
        self.client.post(reverse('org_chart_import'), {'file': SimpleUploadedFile('people.csv', csv.encode())})

        page = self.client.post(reverse('org_chart_import_map'), {'name': '0', 'email': '1', 'manager': '2'})

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['over_limit'], {'new': 2, 'allowed': 1})
        self.assertContains(page, reverse('billing'))
        self.assertFalse(OrgUnit.objects.filter(organization=org).exists())
        self.assertFalse(Reviewee.objects.filter(email__in=['bob@x.example', 'cy@x.example']).exists())
