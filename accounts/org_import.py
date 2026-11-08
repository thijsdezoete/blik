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

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
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
    return errors


def import_org_chart(organization, rows):
    """Replace the organization's org chart with the one in `rows`.

    Creates or updates the reviewees (matched by email). People not in the file
    stay, but are no longer in a unit. Returns (stats, errors); nothing is
    written when there are errors.
    """
    errors = check_rows(rows)
    if errors:
        return None, errors

    stats = {'created': 0, 'updated': 0, 'units': 0}
    with transaction.atomic():
        people = {}
        for row in rows:
            email = row['email'].lower()
            reviewee = Reviewee.objects.filter(organization=organization, email=email).first()
            if reviewee is None:
                allowed, message = check_employee_limit(organization)
                if not allowed:
                    transaction.set_rollback(True)
                    return None, [message]
                reviewee = Reviewee(organization=organization, email=email)
                stats['created'] += 1
            else:
                stats['updated'] += 1
            reviewee.name = row['name']
            reviewee.department = row.get('department', '')
            reviewee.is_active = True
            reviewee.save()
            people[email] = reviewee

        OrgUnit.objects.filter(organization=organization).delete()

        reports = {}
        for row in rows:
            manager = row.get('manager_email', '').lower()
            if manager:
                reports.setdefault(manager, []).append(people[row['email'].lower()])

        names = set()
        for order, (manager_email, members) in enumerate(reports.items()):
            manager = people[manager_email]
            name = manager.department or manager.name
            if name in names:
                name = f'{name} ({manager.name})'
            names.add(name)

            unit = OrgUnit.objects.create(organization=organization, name=name, display_order=order)
            OrgUnitMembership.objects.create(unit=unit, reviewee=manager, row=0, col=0)
            for col, member in enumerate(sorted(members, key=lambda r: r.name.lower())):
                OrgUnitMembership.objects.create(unit=unit, reviewee=member, row=1, col=col)
            stats['units'] += 1

    return stats, []
