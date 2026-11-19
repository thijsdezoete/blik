"""The sender that an invitation email shows: the name of the person who invites and the name of the organization.

A free signup has neither. The user has no name, and the organization is named after the email
address. An invitation then reads "a@acme.example invited you to join a@acme.example", which
looks like spam to a person and to a spam filter. The pages that send invitations ask for the
missing names first.
"""
from core.env_config import env_managed_fields

# The form fields, in the forms that send invitations and in the preview request.
FIRST_NAME, LAST_NAME, ORGANIZATION_NAME = 'sender_first_name', 'sender_last_name', 'sender_organization_name'


def named_after_email(organization):
    return '@' in organization.name


def missing(user, organization):
    """The names this user must give before an invitation goes out: a set of 'name' and 'organization'."""
    fields = set()
    if not user.get_full_name():
        fields.add('name')
    if (named_after_email(organization) and 'name' not in env_managed_fields(organization)
            and user.has_perm('accounts.can_manage_organization')):
        fields.add('organization')
    return fields


def apply(user, organization, data, fields):
    """Put the posted names on the user and the organization, without a save. Empty values change nothing."""
    first = data.get(FIRST_NAME, '').strip()
    if 'name' in fields and first:
        user.first_name = first[:150]
        user.last_name = data.get(LAST_NAME, '').strip()[:150]
    name = data.get(ORGANIZATION_NAME, '').strip()
    if 'organization' in fields and name:
        organization.name = name[:255]


def save(user, organization, data):
    """Save the posted names. A user can only give the names that are missing: this is not a profile form."""
    fields = missing(user, organization)
    apply(user, organization, data, fields)
    if 'name' in fields:
        user.save(update_fields=['first_name', 'last_name'])
    if 'organization' in fields:
        organization.save(update_fields=['name'])
