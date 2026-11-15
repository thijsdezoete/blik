from django.db import migrations
from django.db.models import Q


def grant_to_admins_with_tokens(apps, schema_editor):
    """Give API access to the admins of every organization that has an API token.

    The permission is off by default and no group carries it. Without this
    grant the people who use the API now would lose the API parts of the
    interface. The grant goes to the user, not to the Organization Admin group.
    """
    User = apps.get_model('auth', 'User')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    APIToken = apps.get_model('api', 'APIToken')

    try:
        content_type = ContentType.objects.get(app_label='accounts', model='userprofile')
    except ContentType.DoesNotExist:
        return

    permission, _ = Permission.objects.get_or_create(
        codename='can_use_api',
        content_type=content_type,
        defaults={'name': 'Can see the API parts of the interface'},
    )

    # Admins are in the admin group; accounts from the old setup page and
    # import hold can_manage_organization directly instead.
    admins = User.objects.filter(
        Q(groups__name='Organization Admin')
        | Q(user_permissions__codename='can_manage_organization',
            user_permissions__content_type=content_type),
        profile__organization__in=APIToken.objects.values('organization'),
    ).distinct()

    for user in admins:
        user.user_permissions.add(permission)


def remove_permission(apps, schema_editor):
    """Delete the permission; its grants go with it."""
    Permission = apps.get_model('auth', 'Permission')

    Permission.objects.filter(
        codename='can_use_api', content_type__app_label='accounts').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_invitation_message_and_outbox'),
        ('api', '0005_hash_api_tokens'),
        ('auth', '__latest__'),
        ('contenttypes', '__latest__'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='userprofile',
            options={
                'ordering': ['user__username'],
                'permissions': [
                    ('can_invite_members', 'Can invite team members'),
                    ('can_manage_organization', 'Can manage organization settings'),
                    ('can_delete_organization', 'Can delete organization'),
                    ('can_view_all_reports', 'Can view all organization reports'),
                    ('can_manage_questionnaires', 'Can create and edit questionnaires'),
                    ('can_use_api', 'Can see the API parts of the interface'),
                ],
                'verbose_name': 'user profile',
                'verbose_name_plural': 'user profiles',
            },
        ),
        migrations.RunPython(grant_to_admins_with_tokens, remove_permission),
    ]
