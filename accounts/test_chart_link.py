from django.test import TestCase

from accounts.chart_link import apply_chart_choice, chart_relation, chart_shown, unplaced_with_manager
from accounts.factories import OrgUnitFactory, OrgUnitMembershipFactory, RevieweeFactory
from accounts.models import OrgUnit, OrgUnitMembership
from core.factories import OrganizationFactory
from questionnaires.factories import QuestionnaireFactory
from reviews.services import derive_reviewers
from reviews.setup import save_review_setup

ALL_FLAGS = {'include_self': True, 'include_manager': True, 'include_peer': True, 'include_direct_report': True}


class ChartLinkTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()
        self.tom = self.person('Tom Bakker', 'tom@acme.example', department='Engineering')
        self.maya = self.person('Maya Jansen', 'maya@acme.example', department='Product Engineering')
        self.lena = self.person('Lena Visser', 'lena@acme.example', department='Engineering')

    def person(self, name, email, department=''):
        return RevieweeFactory(organization=self.org, name=name, email=email, department=department)

    def unit(self, name, manager=None, members=(), display_order=0):
        unit = OrgUnitFactory(organization=self.org, name=name, display_order=display_order)
        if manager:
            OrgUnitMembershipFactory(unit=unit, reviewee=manager, row=0, col=0)
        for col, member in enumerate(members):
            OrgUnitMembershipFactory(unit=unit, reviewee=member, row=1, col=col)
        return unit

    def roles(self, unit):
        return {(m.reviewee, m.role) for m in unit.memberships.all()}

    def managers_of(self, person):
        return derive_reviewers(person)['manager']

    def test_place_puts_the_person_in_the_unit_the_manager_leads(self):
        unit = self.unit('Platform', manager=self.tom, members=[self.lena])
        self.assertEqual(chart_relation(self.tom, self.maya),
                         {'state': 'missing', 'managers': [], 'unit_name': 'Platform', 'new_unit': False,
                          'unit_id': unit.pk, 'also_managers': []})

        self.assertEqual(apply_chart_choice(self.tom, self.maya, 'place'), unit)

        self.assertEqual(self.roles(unit), {(self.tom, OrgUnitMembership.MANAGER),
                                            (self.lena, OrgUnitMembership.MEMBER),
                                            (self.maya, OrgUnitMembership.MEMBER)})
        self.assertEqual(unit.memberships.get(reviewee=self.maya).col, 1)
        self.assertEqual(self.managers_of(self.maya), [self.tom])
        self.assertEqual(chart_relation(self.tom, self.maya)['state'], 'has')

    def test_manager_with_two_units_uses_the_one_named_after_the_department(self):
        self.unit('Platform', manager=self.tom, display_order=1)
        named = self.unit('product engineering', manager=self.tom, display_order=2)
        self.assertEqual(apply_chart_choice(self.tom, self.maya, 'place'), named)

        self.lena.department = 'Sales'
        first = OrgUnit.objects.get(name='Platform')
        self.assertEqual(chart_relation(self.tom, self.lena)['unit_name'], 'Platform')
        self.assertEqual(apply_chart_choice(self.tom, self.lena, 'place'), first)

    def test_manager_without_unit_gets_a_new_unit_named_after_the_managers_department(self):
        self.assertEqual(chart_relation(self.tom, self.maya)['unit_name'], 'Engineering')
        self.assertTrue(chart_relation(self.tom, self.maya)['new_unit'])

        unit = apply_chart_choice(self.tom, self.maya, 'place')

        self.assertEqual(unit.name, 'Engineering')
        self.assertEqual(self.roles(unit), {(self.tom, OrgUnitMembership.MANAGER),
                                            (self.maya, OrgUnitMembership.MEMBER)})
        self.assertEqual(self.managers_of(self.maya), [self.tom])

        nameless = self.person('Sam Peters', 'sam@acme.example')
        lead = self.person('Noor Smit', 'noor@acme.example')
        self.assertEqual(apply_chart_choice(lead, nameless, 'place').name, 'Noor Smit')
        nameless.refresh_from_db()
        self.assertEqual(nameless.department, 'Noor Smit')

    def test_two_people_under_a_manager_without_unit_end_in_the_unit_that_was_named(self):
        questionnaire = QuestionnaireFactory(organization=self.org)
        blair = self.person('Blair Chen', 'blair@acme.example', department='Customer Success')
        ravi = self.person('Ravi Kumar', 'ravi@acme.example', department='Data')
        for person in (self.maya, ravi):
            save_review_setup(person, questionnaire, ALL_FLAGS,
                              {'manager': [blair], 'peer': [], 'direct_report': []},
                              {'manager': [], 'peer': [], 'direct_report': []})
        named = {person: chart_relation(blair, person)['unit_name'] for person in (self.maya, ravi)}
        listed = {person: relation['unit_name'] for person, _manager, relation in unplaced_with_manager(self.org)}

        for person in (ravi, self.maya):
            apply_chart_choice(blair, person, 'place')

        for person in (self.maya, ravi):
            placed_in = OrgUnit.objects.get(memberships__reviewee=person, memberships__role=OrgUnitMembership.MEMBER)
            self.assertEqual(named[person], placed_in.name)
            self.assertEqual(listed[person], placed_in.name)

    def test_taken_unit_name_gets_the_manager_name(self):
        self.unit('Engineering', manager=self.lena)
        self.unit('Engineering (Tom Bakker)')
        self.assertEqual(chart_relation(self.tom, self.maya)['unit_name'], 'Engineering (Tom Bakker) 2')

        unit = apply_chart_choice(self.tom, self.maya, 'both')

        self.assertEqual(unit.name, 'Engineering (Tom Bakker) 2')
        self.assertEqual(self.roles(unit), {(self.tom, OrgUnitMembership.MANAGER),
                                            (self.maya, OrgUnitMembership.MEMBER)})

    def test_existing_unit_never_gets_a_second_manager(self):
        existing = self.unit('Engineering', manager=self.lena)
        empty = self.unit('Engineering (Tom Bakker)')

        apply_chart_choice(self.tom, self.maya, 'place')

        self.assertEqual(self.roles(existing), {(self.lena, OrgUnitMembership.MANAGER)})
        self.assertEqual(self.roles(empty), set())
        self.assertEqual(self.managers_of(self.maya), [self.tom])

    def test_relation_is_conflict_and_names_the_current_manager(self):
        self.unit('Sales', manager=self.lena, members=[self.maya])
        self.assertEqual(chart_relation(self.tom, self.maya),
                         {'state': 'conflict', 'managers': [self.lena],
                          'unit_name': 'Engineering', 'new_unit': True, 'unit_id': None, 'also_managers': []})

    def test_relation_names_the_other_managers_of_the_target_unit(self):
        zoe = self.person('Zoe Lim', 'zoe@acme.example')
        gone = self.person('Ann Gone', 'ann@acme.example')
        gone.is_active = False
        gone.save()
        shared = self.unit('Platform', manager=self.tom)
        for col, co_manager in enumerate([zoe, gone, self.lena], start=1):
            OrgUnitMembershipFactory(unit=shared, reviewee=co_manager, row=0, col=col)
        # A deactivated co-manager is named too: a login of theirs still reads the reports.
        self.assertEqual(chart_relation(self.tom, self.maya)['also_managers'], [gone, self.lena, zoe])

        alone = self.person('Noor Smit', 'noor@acme.example')
        self.unit('Mobile', manager=alone)
        self.assertEqual(chart_relation(alone, self.maya)['also_managers'], [])
        self.assertEqual(chart_relation(self.maya, self.lena)['also_managers'], [])  # a new unit

    def test_relation_is_missing_when_only_units_without_a_manager_have_the_person(self):
        self.unit('Guild', members=[self.maya])
        self.assertEqual(chart_relation(self.tom, self.maya)['state'], 'missing')
        self.assertEqual(unplaced_with_manager(self.org), [])  # the list only has people in no unit

    def test_move_removes_only_the_membership_under_the_named_manager(self):
        m1 = self.person('Mila de Vries', 'mila@acme.example')
        m2 = self.person('Ravi Kumar', 'ravi@acme.example')
        under_m1 = self.unit('Design', manager=m1, members=[self.maya])
        under_m2 = self.unit('Research', manager=m2, members=[self.maya])
        guild = self.unit('Guild', members=[self.maya])
        own = self.unit('Mobile', manager=self.maya, members=[self.lena])
        self.assertEqual(chart_relation(self.tom, self.maya)['managers'], [m1, m2])

        unit = apply_chart_choice(self.tom, self.maya, 'move')

        self.assertFalse(under_m1.memberships.filter(reviewee=self.maya).exists())
        self.assertFalse(under_m2.memberships.filter(reviewee=self.maya).exists())
        self.assertTrue(guild.memberships.filter(reviewee=self.maya, role=OrgUnitMembership.MEMBER).exists())
        self.assertTrue(own.memberships.filter(reviewee=self.maya, role=OrgUnitMembership.MANAGER).exists())
        self.assertTrue(unit.memberships.filter(reviewee=self.maya, role=OrgUnitMembership.MEMBER).exists())
        self.assertEqual(self.managers_of(self.maya), [self.tom])

    def test_move_with_the_shown_managers_keeps_a_manager_added_after_them(self):
        old = self.unit('Sales', manager=self.lena, members=[self.maya])
        shown = chart_relation(self.tom, self.maya)['managers']
        zoe = self.person('Zoe Lim', 'zoe@acme.example')
        apply_chart_choice(zoe, self.maya, 'both')

        apply_chart_choice(self.tom, self.maya, 'move', shown)

        self.assertFalse(old.memberships.filter(reviewee=self.maya).exists())
        self.assertEqual(set(self.managers_of(self.maya)), {zoe, self.tom})

    def test_shown_text_changes_with_each_thing_a_choice_promises(self):
        texts = [chart_shown(chart_relation(self.tom, self.maya))]  # missing, a new unit Engineering
        self.unit('Engineering', manager=self.lena)  # the new unit gets another name
        texts.append(chart_shown(chart_relation(self.tom, self.maya)))
        platform = self.unit('Platform', manager=self.tom)  # an existing unit
        texts.append(chart_shown(chart_relation(self.tom, self.maya)))
        zoe = self.person('Zoe Lim', 'zoe@acme.example')
        OrgUnitMembershipFactory(unit=platform, reviewee=zoe, row=0, col=1)  # another manager there
        texts.append(chart_shown(chart_relation(self.tom, self.maya)))
        self.unit('Sales', manager=self.lena, members=[self.maya])  # a current manager: conflict
        texts.append(chart_shown(chart_relation(self.tom, self.maya)))

        self.assertEqual(len(set(texts)), len(texts))
        self.assertEqual(chart_shown(chart_relation(self.tom, self.maya)), texts[-1])

    def test_both_keeps_the_old_manager(self):
        old = self.unit('Sales', manager=self.lena, members=[self.maya])

        apply_chart_choice(self.tom, self.maya, 'both')

        self.assertTrue(old.memberships.filter(reviewee=self.maya).exists())
        self.assertEqual(self.managers_of(self.maya), [self.lena, self.tom])

    def test_department_is_kept_when_set(self):
        self.unit('Platform', manager=self.tom)
        apply_chart_choice(self.tom, self.maya, 'place')
        self.maya.refresh_from_db()
        self.assertEqual(self.maya.department, 'Product Engineering')

        nameless = self.person('Sam Peters', 'sam@acme.example')
        apply_chart_choice(self.tom, nameless, 'place')
        nameless.refresh_from_db()
        self.assertEqual(nameless.department, 'Platform')

    def test_choice_that_does_not_fit_the_state_changes_nothing(self):
        unit = self.unit('Platform', manager=self.tom, members=[self.maya])
        co_led = self.unit('Mobile', manager=self.lena)
        OrgUnitMembershipFactory(unit=co_led, reviewee=self.maya, row=0, col=1)
        before = set(OrgUnitMembership.objects.values_list('unit', 'reviewee', 'role'))

        for action in ('place', 'move', 'both'):
            self.assertEqual(apply_chart_choice(self.tom, self.maya, action), unit)
        # Maya leads Mobile with Lena: placing her under Lena there would be a second row.
        self.assertEqual(apply_chart_choice(self.lena, self.maya, 'place'), co_led)

        self.assertEqual(set(OrgUnitMembership.objects.values_list('unit', 'reviewee', 'role')), before)

    def test_refuses_unknown_action_the_person_as_own_manager_another_organization_and_inactive_people(self):
        outsider = RevieweeFactory(organization=OrganizationFactory(), email='kim@other.example')
        inactive = RevieweeFactory(organization=self.org, email='ann@acme.example', is_active=False)
        for manager, person, action in ((self.tom, self.maya, 'swap'), (self.maya, self.maya, 'place'),
                                        (outsider, self.maya, 'place'), (self.tom, outsider, 'place'),
                                        (inactive, self.maya, 'place'), (self.tom, inactive, 'place')):
            with self.assertRaises(ValueError):
                apply_chart_choice(manager, person, action)
        self.assertFalse(OrgUnit.objects.exists())

    def test_unplaced_with_manager_lists_people_with_one_manager_in_their_list(self):
        questionnaire = QuestionnaireFactory(organization=self.org)
        self.unit('Platform', manager=self.tom)
        sam = self.person('Sam Peters', 'sam@acme.example')
        noor = self.person('Noor Smit', 'noor@acme.example')
        gone = self.person('Ann Gone', 'ann@acme.example')
        placed = self.person('Bo Placed', 'bo@acme.example')
        self.unit('Sales', manager=self.lena, members=[placed])

        def save(person, managers):
            save_review_setup(person, questionnaire, ALL_FLAGS,
                              {'manager': managers, 'peer': [], 'direct_report': []},
                              {'manager': [], 'peer': [], 'direct_report': []})

        save(self.maya, [noor])
        save(sam, [self.tom])
        save(noor, [self.tom, self.lena])  # two managers: not one to place under
        save(gone, [self.tom])
        save(placed, [self.tom])
        gone.is_active = False
        gone.save()

        self.assertEqual(unplaced_with_manager(self.org), [
            (self.maya, noor, chart_relation(noor, self.maya)),
            (sam, self.tom, chart_relation(self.tom, sam)),
        ])
        self.assertEqual(chart_relation(noor, self.maya)['unit_name'], 'Noor Smit')
