"""Which Organization fields the environment owns.

`setup_organization` runs on every container start and writes any field whose
env var is set. Letting the admin UI edit those same fields produces edits that
silently vanish on the next restart — the bug behind issue #4.

So the environment wins, visibly: fields it sets are rendered read-only on the
settings page and rejected server-side if posted anyway. Fields with no env var
(anonymity threshold, registration flags) stay editable in the UI.
"""
import os

# Organization model field -> environment variable that owns it
ENV_MANAGED_FIELDS = {
    'name': 'ORGANIZATION_NAME',
    'email': 'DEFAULT_FROM_EMAIL',
    'from_email': 'DEFAULT_FROM_EMAIL',
    'smtp_host': 'EMAIL_HOST',
    'smtp_port': 'EMAIL_PORT',
    'smtp_username': 'EMAIL_HOST_USER',
    'smtp_password': 'EMAIL_HOST_PASSWORD',
    'smtp_use_tls': 'EMAIL_USE_TLS',
    'default_language': 'ORGANIZATION_LANGUAGE',
}


# setup_organization writes this organization, and no other.
ENV_ORGANIZATION_ID = 1


def env_managed_fields(organization=None):
    """
    Return {field: env_var} for the fields the environment currently owns.

    An env var that is set but empty does not count as owning the field —
    that is how you hand a field back to the UI without editing compose files.

    With an organization: the fields the environment owns of that organization.
    On a service with more than one organization, ORGANIZATION_NAME names only
    the organization that setup_organization writes. The others keep their own
    name. The email settings stay locked for all of them: every organization
    sends through the mail server of the service.
    """
    fields = {
        field: var
        for field, var in ENV_MANAGED_FIELDS.items()
        if os.environ.get(var)
    }
    if organization is not None and organization.pk != ENV_ORGANIZATION_ID:
        fields.pop('name', None)
    return fields
