"""Build the org chart from a spreadsheet (CSV).

Any CSV works: the admin maps its columns to name (or first and last name),
email, department and manager. The manager column can hold an email or a name.
Each person who is someone's manager gets one unit: they are its manager, the
people who report to them are its members. Units stack by themselves: a head of
department is a member of the professor's unit and the manager of their own.
"""
import csv
import io
import re
from collections import Counter

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _, gettext_lazy

from accounts.models import OrgUnit, OrgUnitMembership, Reviewee
from subscriptions.utils import check_employee_limit

FIELDS = [
    ('name', gettext_lazy('Name')),
    ('first_name', gettext_lazy('First name')),
    ('last_name', gettext_lazy('Last name')),
    ('email', gettext_lazy('Email')),
    ('department', gettext_lazy('Department')),
    ('manager', gettext_lazy('Manager (email or name)')),
]

# Normalized header names (lower case, letters and digits only) per field, in
# English, German and Dutch. Manager comes first so "Manager email" is not taken
# for the person's own email.
SYNONYMS = {
    'manager': ['manager', 'manageremail', 'managername', 'supervisor', 'supervisoremail', 'reportsto',
                'linemanager', 'vorgesetzter', 'vorgesetzte', 'vorgesetzterin', 'fuehrungskraft',
                'führungskraft', 'leidinggevende'],
    'email': ['email', 'mail', 'emailaddress', 'workemail', 'businessemail', 'emailadresse', 'mailadresse',
              'geschäftlicheemail', 'zakelijkeemail'],
    'first_name': ['firstname', 'givenname', 'vorname', 'voornaam'],
    'last_name': ['lastname', 'surname', 'familyname', 'nachname', 'achternaam'],
    'name': ['name', 'fullname', 'displayname', 'employee', 'employeename', 'mitarbeiter', 'naam',
             'vollständigername', 'volledigenaam'],
    'department': ['department', 'dept', 'team', 'unit', 'abteilung', 'bereich', 'afdeling', 'division',
                   'organisationseinheit', 'lehrstuhl'],
}


def read_table(raw):
    """(headers, rows) of a CSV file; rows are lists. Excel uses ';' in many locales."""
    text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0] if text else '', delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    table = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect=dialect)]
    table = [row for row in table if any(row)]
    if not table:
        return [], []
    headers, rows = table[0], table[1:]
    return headers, [row + [''] * (len(headers) - len(row)) for row in rows]


def guess_mapping(headers):
    """{field: column index or None}, guessed from the header names."""
    normalized = [re.sub(r'[^\w]|_', '', h.lower()) for h in headers]
    mapping, taken = {}, set()
    for field, names in SYNONYMS.items():
        found = next((i for i, h in enumerate(normalized) if h in names and i not in taken), None)
        mapping[field] = found
        if found is not None:
            taken.add(found)
    if mapping['name'] is not None:
        mapping['first_name'] = mapping['last_name'] = None
    return mapping


def map_rows(headers, rows, mapping):
    """
    Rows as dicts (name, email, department, manager_email) using the column
    mapping, plus error messages. A manager given by name is looked up among
    the names in the file.
    """
    def column(field):
        index = mapping.get(field)
        return index if index is not None and 0 <= index < len(headers) else None

    if column('email') is None:
        return [], [_('Choose the column with the email addresses.')]
    if column('name') is None and column('first_name') is None and column('last_name') is None:
        return [], [_('Choose the column with the names, or the columns with first and last names.')]

    def cell(row, field):
        index = column(field)
        return row[index] if index is not None else ''

    mapped = []
    for row in rows:
        name = cell(row, 'name') or ' '.join(p for p in (cell(row, 'first_name'), cell(row, 'last_name')) if p)
        mapped.append({'name': name, 'email': cell(row, 'email'), 'department': cell(row, 'department'),
                       'manager': cell(row, 'manager')})

    by_name = {}
    for row in mapped:
        by_name.setdefault(row['name'].lower(), []).append(row['email'].lower())

    errors = []
    for line, row in enumerate(mapped, start=2):
        manager = row.pop('manager')
        if manager and '@' not in manager:
            emails = by_name.get(manager.lower(), [])
            if not emails:
                errors.append(_('Line %(line)s: manager "%(name)s" is not in the file.') % {'line': line, 'name': manager})
            elif len(emails) > 1:
                errors.append(_('Line %(line)s: more than one person is called "%(name)s". Use the email of the manager.')
                              % {'line': line, 'name': manager})
            manager = emails[0] if len(emails) == 1 else ''
        row['manager_email'] = manager
    return mapped, errors


def rows_from_csv(raw):
    """Read a CSV file with the guessed mapping: (rows, errors)."""
    headers, rows = read_table(raw)
    return map_rows(headers, rows, guess_mapping(headers))


def check_rows(rows):
    """Error messages for the rows; empty when the file can be imported."""
    if not rows:
        return [_('The file has no rows.')]

    errors = []
    emails = set()
    for line, row in enumerate(rows, start=2):
        email = row['email'].lower()
        try:
            validate_email(email)
        except ValidationError:
            errors.append(_('Line %(line)s: invalid email "%(email)s".') % {'line': line, 'email': row['email']})
            continue
        if email in emails:
            errors.append(_('Line %(line)s: %(email)s is in the file twice.') % {'line': line, 'email': email})
        if not row['name']:
            errors.append(_('Line %(line)s: the name is empty.') % {'line': line})
        emails.add(email)

    for line, row in enumerate(rows, start=2):
        manager = row.get('manager_email', '').lower()
        if manager and manager not in emails:
            errors.append(_('Line %(line)s: manager %(email)s is not in the file.') % {'line': line, 'email': manager})
        if manager and manager == row['email'].lower():
            errors.append(_('Line %(line)s: a person cannot be their own manager.') % {'line': line})

    # A reporting line that comes back to the same person (A reports to B, B to A).
    manager_of = {row['email'].lower(): row.get('manager_email', '').lower() for row in rows}
    for line, row in enumerate(rows, start=2):
        start = row['email'].lower()
        seen, current = {start}, manager_of.get(start, '')
        while current and current not in seen:
            seen.add(current)
            current = manager_of.get(current, '')
        if current == start and manager_of[start] != start:
            errors.append(_('Line %(line)s: the reporting line of %(email)s comes back to the same person.')
                          % {'line': line, 'email': start})
    return errors


def count_new_people(organization, rows):
    """How many people in `rows` are not yet reviewees of the organization."""
    emails = {row['email'].lower() for row in rows}
    known = set(Reviewee.objects.filter(organization=organization, email__in=emails).values_list('email', flat=True))
    return len(emails - {e.lower() for e in known})


def _placements(organization):
    """Where each person is in the chart: {reviewee id: [(key, text), ...]}.

    The key changes when the unit or its managers change; the text says it in words.
    """
    memberships = list(OrgUnitMembership.objects.filter(unit__organization=organization)
                       .select_related('unit', 'reviewee').order_by('unit__display_order', 'row', 'col'))
    managers = {}
    for m in memberships:
        if m.role == OrgUnitMembership.MANAGER:
            managers.setdefault(m.unit_id, []).append(m.reviewee)
    places = {}
    for m in memberships:
        above = managers.get(m.unit_id, [])
        if m.role == OrgUnitMembership.MANAGER:
            key, text = ('manager', m.unit_id), _('Manager of %(unit)s') % {'unit': m.unit.name}
        elif above:
            key = ('member', m.unit_id, tuple(r.pk for r in above))
            text = _('In %(unit)s, reports to %(manager)s') % {
                'unit': m.unit.name, 'manager': ', '.join(r.name for r in above)}
        else:
            key, text = ('member', m.unit_id, ()), _('In %(unit)s') % {'unit': m.unit.name}
        places.setdefault(m.reviewee_id, []).append((key, text))
    return places


def import_org_chart(organization, rows, deactivate_missing=False, dry_run=False):
    """Bring the organization's org chart in line with `rows`.

    Creates or updates the reviewees (matched by email). The file is merged into
    the chart: a manager keeps the unit they have (name, order, positions), and
    only the people whose manager changed move. A person without a manager in
    the file stays where they are. A unit that loses all its members is removed.

    People who are not in the file stay as they are, or are deactivated with
    `deactivate_missing`. Nothing is ever deleted from a person.

    With `dry_run` nothing is written; the stats say what the import would do.
    `stats['people']` has one row per person who changes, with their place in
    the chart before and after; `stats['missing']` the same for the people who
    are not in the file (as it is when they stay active).
    Returns (stats, errors); nothing is written when there are errors.
    """
    errors = check_rows(rows)
    if errors:
        return None, errors

    MANAGER, MEMBER = OrgUnitMembership.MANAGER, OrgUnitMembership.MEMBER
    stats = {'created': [], 'updated': 0, 'moved': 0, 'unchanged': 0, 'people': [], 'units_created': [],
             'units_removed': [], 'missing': [], 'deactivated': 0, 'units': 0, 'active': 0}
    with transaction.atomic():
        was = {r.pk: r for r in Reviewee.objects.filter(organization=organization)}
        places_before = _placements(organization)
        people, new = {}, set()
        for row in rows:
            email = row['email'].lower()
            reviewee = Reviewee.objects.filter(organization=organization, email=email).first()
            if reviewee is None:
                allowed, message = check_employee_limit(organization)
                if not allowed:
                    transaction.set_rollback(True)
                    return None, [message]
                reviewee = Reviewee(organization=organization, email=email)
                stats['created'].append(row['name'])
                new.add(email)
            else:
                stats['updated'] += 1
            reviewee.name = row['name']
            reviewee.department = row.get('department', '')
            reviewee.is_active = True
            reviewee.save()
            people[email] = reviewee

        units = OrgUnit.objects.filter(organization=organization)
        memberships = OrgUnitMembership.objects.filter(unit__organization=organization)
        had_members = set(memberships.filter(role=MEMBER).values_list('unit_id', flat=True))

        missing = (Reviewee.objects.filter(organization=organization, is_active=True)
                   .exclude(pk__in=[p.pk for p in people.values()])
                   .exclude(email__icontains='@deleted.invalid').order_by('name'))
        missing_people = list(missing)
        if deactivate_missing:
            stats['deactivated'] = len(missing_people)
            OrgUnitMembership.objects.filter(reviewee__in=missing).delete()
            missing.update(is_active=False)

        names = set(units.values_list('name', flat=True))
        last_order = units.aggregate(m=Max('display_order'))['m']
        order = -1 if last_order is None else last_order

        reports = {}
        for row in rows:
            manager = row.get('manager_email', '').lower()
            if manager:
                reports.setdefault(manager, []).append(people[row['email'].lower()])

        for manager_email, members in reports.items():
            manager = people[manager_email]
            # ponytail: a person who manages several hand-made units gets their reports in the first one
            own = memberships.filter(reviewee=manager, role=MANAGER).order_by('unit__display_order').first()
            unit = own.unit if own else None
            if unit is None:
                # A new manager takes over the unit most of their reports are in, when
                # its manager no longer manages anyone. The unit keeps its name and place.
                current = Counter(memberships.filter(reviewee__in=members, role=MEMBER).values_list('unit_id', flat=True))
                for unit_id, _count in current.most_common():
                    old = memberships.filter(unit_id=unit_id, role=MANAGER).values_list('reviewee__email', flat=True)
                    if not any(email in reports for email in old):
                        unit = units.get(pk=unit_id)
                        memberships.filter(unit=unit, role=MANAGER).delete()
                        memberships.filter(unit=unit, reviewee=manager).delete()
                        break
            if unit is None:
                name = manager.department or manager.name
                if name in names:
                    name = f'{name} ({manager.name})'
                while name in names:
                    name += ' 2'
                names.add(name)
                order += 1
                unit = OrgUnit.objects.create(organization=organization, name=name, display_order=order)
                stats['units_created'].append(name)
            if not own:
                OrgUnitMembership.objects.create(unit=unit, reviewee=manager, row=0, col=0)

            for member in sorted(members, key=lambda r: r.name.lower()):
                memberships.filter(reviewee=member, role=MEMBER).exclude(unit=unit).delete()
                if memberships.filter(unit=unit, reviewee=member, role=MEMBER).exists():
                    continue
                memberships.filter(unit=unit, reviewee=member).delete()
                last_col = memberships.filter(unit=unit, row=1).aggregate(m=Max('col'))['m']
                OrgUnitMembership.objects.create(unit=unit, reviewee=member, row=1,
                                                 col=0 if last_col is None else last_col + 1)

        emptied = units.filter(pk__in=had_members).exclude(memberships__role=MEMBER)
        stats['units_removed'] = list(emptied.values_list('name', flat=True))
        emptied.delete()
        stats['units'] = units.count()

        # What changes per person, from the chart before and after.
        places_after = _placements(organization)
        nowhere = [((), _('Not in a unit'))]

        def texts(places):
            return [text for _key, text in places]

        for person in people.values():
            old = was.get(person.pk)
            before, after = places_before.get(person.pk, nowhere), places_after.get(person.pk, nowhere)
            row = {'name': person.name, 'email': person.email, 'before': texts(before), 'after': texts(after)}
            details = False
            if old:
                # Translators: a line in the preview of an import, such as "Name: Ada Lovelace"
                for text, old_value, new_value in ((_('Name: %(value)s'), old.name, person.name),
                                                   (_('Department: %(value)s'), old.department, person.department)):
                    if old_value != new_value:
                        details = True
                        row['before'].append(text % {'value': old_value or '–'})
                        row['after'].append(text % {'value': new_value or '–'})
            moved = [key for key, _text in before] != [key for key, _text in after]
            if old is None:
                row['kind'], row['before'] = 'new', []
            elif not old.is_active:
                row['kind'] = 'reactivated'
            elif moved:
                # Same units, other manager above them: the person stays, the manager changes.
                same_units = [key[:2] for key, _text in before] == [key[:2] for key, _text in after]
                row['kind'] = 'manager' if same_units else 'moved'
                stats['moved'] += 1
            elif details:
                row['kind'] = 'changed'
            else:
                stats['unchanged'] += 1
                continue
            stats['people'].append(row)
        order = ['new', 'reactivated', 'moved', 'manager', 'changed']
        stats['people'].sort(key=lambda row: (order.index(row['kind']), row['name'].lower()))
        stats['missing'] = [
            {'name': r.name, 'email': r.email, 'before': texts(places_before.get(r.pk, nowhere)),
             'after': texts(places_after.get(r.pk, nowhere))}
            for r in missing_people]
        stats['active'] = Reviewee.objects.filter(organization=organization, is_active=True).count()

        if dry_run:
            transaction.set_rollback(True)

    return stats, []
