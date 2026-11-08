"""
Tests for `derive_reviewers` — the org-chart → four-reviewer-bucket mapper
used by Phase 2 of the org chart feature.

Rules under test (from the plan):

    self           = {P}
    managers(P)    = ⋃ over T where P is MEMBER  → managers(T)
    peers(P)       = (⋃ over T where P is MEMBER  → members(T) \\ {P})
                   ∪ (⋃ over T where P is MANAGER → managers(T) \\ {P})
    direct_reports = ⋃ over T where P is MANAGER → members(T)

    Dedup priority: self > manager > direct_report > peer.
"""
from django.test import TestCase

from accounts.factories import (
    RevieweeFactory,
    OrgUnitFactory,
    OrgUnitMembershipFactory,
)
from core.factories import OrganizationFactory
from reviews.services import derive_reviewers


class DeriveReviewersTests(TestCase):
    def setUp(self):
        self.org = OrganizationFactory()

    def _make_reviewee(self, name):
        return RevieweeFactory(organization=self.org, name=name)

    def _add(self, unit, reviewee, row, col):
        return OrgUnitMembershipFactory(
            unit=unit, reviewee=reviewee, row=row, col=col)

    def _uuids(self, people):
        return sorted(str(p.uuid) for p in people)

    def test_solo_reviewee_not_in_any_unit(self):
        alice = self._make_reviewee('Alice')
        result = derive_reviewers(alice)
        self.assertEqual([p.uuid for p in result['self']], [alice.uuid])
        self.assertEqual(result['manager'], [])
        self.assertEqual(result['peer'], [])
        self.assertEqual(result['direct_report'], [])

    def test_simple_pyramid(self):
        """Two managers on top, two members below."""
        ceo = self._make_reviewee('CEO')
        cfo = self._make_reviewee('CFO')
        alice = self._make_reviewee('Alice')
        bob = self._make_reviewee('Bob')

        unit = OrgUnitFactory(organization=self.org, name='Leadership')
        self._add(unit, ceo, row=0, col=0)
        self._add(unit, cfo, row=0, col=1)
        self._add(unit, alice, row=1, col=0)
        self._add(unit, bob, row=1, col=1)

        # From a member's perspective
        result = derive_reviewers(alice)
        self.assertEqual(self._uuids(result['manager']),
                         self._uuids([ceo, cfo]))
        self.assertEqual(self._uuids(result['peer']),
                         self._uuids([bob]))
        self.assertEqual(result['direct_report'], [])

        # From a manager's perspective
        result = derive_reviewers(ceo)
        self.assertEqual(self._uuids(result['direct_report']),
                         self._uuids([alice, bob]))
        self.assertEqual(self._uuids(result['peer']),
                         self._uuids([cfo]))
        self.assertEqual(result['manager'], [])

    def test_multi_unit_membership(self):
        """A person in two units sees both sets of relationships."""
        ceo = self._make_reviewee('CEO')
        cfo = self._make_reviewee('CFO')
        vp_eng = self._make_reviewee('VP Eng')
        vp_sales = self._make_reviewee('VP Sales')
        alice = self._make_reviewee('Alice')
        bob = self._make_reviewee('Bob')

        leadership = OrgUnitFactory(organization=self.org, name='Leadership')
        self._add(leadership, ceo, row=0, col=0)
        self._add(leadership, cfo, row=0, col=1)
        self._add(leadership, vp_eng, row=1, col=0)
        self._add(leadership, vp_sales, row=1, col=1)

        engineering = OrgUnitFactory(organization=self.org, name='Engineering')
        self._add(engineering, vp_eng, row=0, col=0)
        self._add(engineering, alice, row=1, col=0)
        self._add(engineering, bob, row=1, col=1)

        # VP Eng is a member of Leadership AND manager of Engineering.
        result = derive_reviewers(vp_eng)
        # Managers: those above in Leadership
        self.assertEqual(self._uuids(result['manager']),
                         self._uuids([ceo, cfo]))
        # Peers: fellow member of Leadership
        self.assertEqual(self._uuids(result['peer']),
                         self._uuids([vp_sales]))
        # Direct reports: members of Engineering
        self.assertEqual(self._uuids(result['direct_report']),
                         self._uuids([alice, bob]))

    def test_co_managers_are_peers(self):
        """Two co-managers of the same unit see each other as peers."""
        a = self._make_reviewee('A')
        b = self._make_reviewee('B')
        c = self._make_reviewee('C')
        t = OrgUnitFactory(organization=self.org, name='T')
        self._add(t, a, row=0, col=0)
        self._add(t, b, row=0, col=1)
        self._add(t, c, row=1, col=0)

        result = derive_reviewers(a)
        self.assertEqual(self._uuids(result['peer']), self._uuids([b]))
        self.assertEqual(self._uuids(result['direct_report']),
                         self._uuids([c]))
        self.assertEqual(result['manager'], [])

    def test_dedup_priority_manager_over_peer(self):
        """
        If X is a manager of P via one unit AND a peer of P via another,
        X should end up only under `manager` (higher priority).
        """
        x = self._make_reviewee('X')
        p = self._make_reviewee('P')

        # Unit1: X is manager of P (P is member, X is manager).
        t1 = OrgUnitFactory(organization=self.org, name='T1')
        self._add(t1, x, row=0, col=0)
        self._add(t1, p, row=1, col=0)

        # Unit2: X and P are both members → would normally be peers.
        t2 = OrgUnitFactory(organization=self.org, name='T2')
        # Give t2 a manager so it's a complete pyramid (not required but realistic)
        owner = self._make_reviewee('Owner')
        self._add(t2, owner, row=0, col=0)
        self._add(t2, x, row=1, col=0)
        self._add(t2, p, row=1, col=1)

        result = derive_reviewers(p)
        manager_uuids = {r.uuid for r in result['manager']}
        peer_uuids = {r.uuid for r in result['peer']}
        self.assertIn(x.uuid, manager_uuids)
        self.assertNotIn(x.uuid, peer_uuids)

    def test_dedup_priority_direct_report_over_peer(self):
        """
        If Y reports to P via OrgUnit A AND Y is a co-member-peer of P in OrgUnit B,
        Y should only appear under `direct_report`.
        """
        p = self._make_reviewee('P')
        y = self._make_reviewee('Y')

        t_a = OrgUnitFactory(organization=self.org, name='A')
        self._add(t_a, p, row=0, col=0)
        self._add(t_a, y, row=1, col=0)

        t_b = OrgUnitFactory(organization=self.org, name='B')
        boss = self._make_reviewee('Boss')
        self._add(t_b, boss, row=0, col=0)
        self._add(t_b, p, row=1, col=0)
        self._add(t_b, y, row=1, col=1)

        result = derive_reviewers(p)
        dr_uuids = {r.uuid for r in result['direct_report']}
        peer_uuids = {r.uuid for r in result['peer']}
        self.assertIn(y.uuid, dr_uuids)
        self.assertNotIn(y.uuid, peer_uuids)

    def test_self_always_contains_only_the_reviewee(self):
        a = self._make_reviewee('A')
        b = self._make_reviewee('B')
        t = OrgUnitFactory(organization=self.org)
        self._add(t, a, row=0, col=0)
        self._add(t, b, row=1, col=0)

        result = derive_reviewers(a)
        self.assertEqual([p.uuid for p in result['self']], [a.uuid])

    def test_ordering_is_alphabetical_by_name(self):
        p = self._make_reviewee('P')
        zara = self._make_reviewee('Zara')
        alice = self._make_reviewee('Alice')
        marie = self._make_reviewee('Marie')

        t = OrgUnitFactory(organization=self.org)
        self._add(t, p, row=0, col=0)
        self._add(t, zara, row=1, col=0)
        self._add(t, alice, row=1, col=1)
        self._add(t, marie, row=1, col=2)

        result = derive_reviewers(p)
        names = [r.name for r in result['direct_report']]
        self.assertEqual(names, ['Alice', 'Marie', 'Zara'])
