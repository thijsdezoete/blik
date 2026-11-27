"""
Turn "this person is the manager of that person" into a change of the org chart.

A place in the chart lets a manager read the reports of the members of the unit,
so every rule here is an access rule. Callers write only on an explicit choice of
a user who may edit the chart.
"""
from django.db import transaction
from django.db.models import Max

from accounts.models import OrgUnit, OrgUnitMembership, Reviewee

ACTIONS = ('place', 'move', 'both')


def append_membership(unit, reviewee, role):
    """Put `reviewee` in `unit` as manager (row 0) or member (row 1), after the people already there."""
    row = 0 if role == OrgUnitMembership.MANAGER else 1
    last = unit.memberships.filter(row=row).aggregate(m=Max('col'))['m']
    return OrgUnitMembership.objects.create(unit=unit, reviewee=reviewee, row=row, col=0 if last is None else last + 1)


def _target(manager, person):
    """(the unit `manager` leads that `person` would join, or None, and its name; a new one when None)."""
    led = list(OrgUnit.objects.filter(
        memberships__reviewee=manager, memberships__role=OrgUnitMembership.MANAGER).order_by('display_order', 'name'))
    if led:
        department = person.department.lower()
        unit = next((u for u in led if u.name.lower() == department), led[0])
        return unit, unit.name
    # A unit that exists never gets a second manager: that would show the manager all its members.
    # Named after the manager, not the person: the next person under this manager joins the same
    # unit, so the name shown before any write must not depend on who is placed first.
    name = manager.department or manager.name
    taken = {n.lower() for n in OrgUnit.objects.filter(organization=manager.organization_id)
             .values_list('name', flat=True)}
    if name.lower() in taken:
        name = f'{name} ({manager.name})'
    while name.lower() in taken:
        name += ' 2'
    return None, name


def chart_relation(manager, person):
    """
    What the chart says about `manager` above `person`:
    'has' (the chart gives this manager), 'missing' (it gives no manager) or
    'conflict' (it gives other managers, listed in 'managers').
    'also_managers': the other active managers of the unit `place` would use;
    they get read access to the person's reports too.
    """
    from reviews.services import derive_reviewers

    current = derive_reviewers(person)['manager']
    unit, name = _target(manager, person)
    if manager in current:
        state, managers = 'has', []
    elif current:
        state, managers = 'conflict', current
    else:
        state, managers = 'missing', []
    also = [] if unit is None else list(
        Reviewee.objects.filter(
            unit_memberships__unit=unit, unit_memberships__role=OrgUnitMembership.MANAGER, is_active=True,
        ).exclude(pk=manager.pk).order_by('name', 'pk'))
    return {'state': state, 'managers': managers, 'unit_name': name, 'new_unit': unit is None,
            'also_managers': also}


@transaction.atomic
def apply_chart_choice(manager, person, action):
    """
    Make `manager` a manager of `person` in the chart and return the unit used.
    'place' and 'both' only add; 'move' also takes `person` out of the units of
    the managers the chart gave before.
    """
    if action not in ACTIONS:
        raise ValueError(f'Unknown action {action!r}')
    if manager.pk == person.pk:
        raise ValueError('A person cannot be their own manager')
    if manager.organization_id != person.organization_id:
        raise ValueError('Manager and person are in different organizations')
    if not (manager.is_active and person.is_active):
        raise ValueError('Manager and person must both be active')

    relation = chart_relation(manager, person)
    unit, name = _target(manager, person)
    if relation['state'] == 'has':
        return OrgUnit.objects.filter(
            memberships__reviewee=manager, memberships__role=OrgUnitMembership.MANAGER,
        ).filter(memberships__reviewee=person, memberships__role=OrgUnitMembership.MEMBER).first()
    if unit is not None and unit.memberships.filter(reviewee=person).exists():
        # A second row would break the unique rule. The person leads this unit with the manager,
        # or is a member of it already (that is state 'has', returned above; kept as a guard).
        return unit

    if action == 'move' and relation['managers']:
        OrgUnitMembership.objects.filter(
            reviewee=person, role=OrgUnitMembership.MEMBER,
            unit__memberships__reviewee__in=relation['managers'],
            unit__memberships__role=OrgUnitMembership.MANAGER,
        ).delete()

    if unit is None:
        last = OrgUnit.objects.filter(organization=manager.organization_id).aggregate(m=Max('display_order'))['m'] or 0
        unit = OrgUnit.objects.create(organization_id=manager.organization_id, name=name, display_order=last + 1)
        append_membership(unit, manager, OrgUnitMembership.MANAGER)
    append_membership(unit, person, OrgUnitMembership.MEMBER)
    if not person.department:
        person.department = unit.name
        person.save(update_fields=['department'])
    return unit


def unplaced_with_manager(organization):
    """
    (person, manager, unit name, new unit) for each active person who is a member
    of no unit and whose reviewer list names exactly one manager. By person name.
    """
    from reviews.setup import review_setup

    found = []
    people = (Reviewee.objects.for_organization(organization).filter(is_active=True)
              .exclude(unit_memberships__role=OrgUnitMembership.MEMBER).order_by('name', 'pk'))
    for person in people:
        # Only users who may edit the chart see this list, and they see the status per reviewer.
        managers = review_setup(person, with_previous=True).people['manager']
        if len(managers) == 1:
            unit, name = _target(managers[0], person)
            found.append((person, managers[0], name, unit is None))
    return found
