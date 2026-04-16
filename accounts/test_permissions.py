from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from core.factories import UserFactory, OrganizationFactory
from accounts.factories import UserProfileFactory
from accounts.permissions import (
    ORG_ADMIN_GROUP,
    ORG_MEMBER_GROUP,
    assign_organization_admin,
    assign_organization_member,
    ensure_permission_groups,
    remove_from_all_org_groups,
)

User = get_user_model()


class PermissionAssignmentTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = OrganizationFactory()
        self.user = UserFactory()
        UserProfileFactory(user=self.user, organization=self.org)

    def _reload_user(self):
        """Re-fetch the user so Django's has_perm() permission cache is cleared."""
        self.user = User.objects.get(pk=self.user.pk)
        return self.user

    def test_demoting_admin_to_member_removes_admin_permissions(self):
        assign_organization_admin(self.user)
        user = self._reload_user()
        self.assertTrue(user.has_perm('accounts.can_manage_organization'))
        self.assertTrue(user.groups.filter(name=ORG_ADMIN_GROUP).exists())

        assign_organization_member(user, can_create_cycles_for_others=False)
        user = self._reload_user()

        self.assertFalse(
            user.groups.filter(name=ORG_ADMIN_GROUP).exists(),
            "Demoted user must not remain in the admin group",
        )
        self.assertTrue(user.groups.filter(name=ORG_MEMBER_GROUP).exists())
        self.assertFalse(user.has_perm('accounts.can_manage_organization'))
        self.assertFalse(user.has_perm('accounts.can_invite_members'))
        self.assertFalse(user.is_staff)

    def test_promoting_member_to_admin_removes_member_group(self):
        assign_organization_member(self.user)
        user = self._reload_user()
        self.assertTrue(user.groups.filter(name=ORG_MEMBER_GROUP).exists())

        assign_organization_admin(user)
        user = self._reload_user()

        self.assertFalse(user.groups.filter(name=ORG_MEMBER_GROUP).exists())
        self.assertTrue(user.groups.filter(name=ORG_ADMIN_GROUP).exists())
        self.assertTrue(user.has_perm('accounts.can_manage_organization'))
        self.assertTrue(user.is_staff)

    def test_remove_from_all_org_groups_preserves_groups(self):
        assign_organization_admin(self.user)
        remove_from_all_org_groups(self.user)

        self.assertFalse(self.user.groups.filter(name=ORG_ADMIN_GROUP).exists())
        self.assertFalse(self.user.groups.filter(name=ORG_MEMBER_GROUP).exists())
        # The Group objects themselves must still exist — other users depend on them.
        self.assertTrue(Group.objects.filter(name=ORG_ADMIN_GROUP).exists())
        self.assertTrue(Group.objects.filter(name=ORG_MEMBER_GROUP).exists())
