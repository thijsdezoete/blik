from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.factories import UserFactory, OrganizationFactory
from accounts.factories import UserProfileFactory
from accounts.models import UserProfile
from accounts.permissions import (
    ORG_ADMIN_GROUP,
    ORG_MEMBER_GROUP,
    assign_organization_admin,
    assign_organization_member,
    can_manage_organization_required,
    ensure_permission_groups,
    login_required,
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

    def _grant_directly(self, *codenames):
        content_type = ContentType.objects.get_for_model(UserProfile)
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type=content_type, codename__in=codenames))

    def test_demoting_removes_a_direct_admin_grant(self):
        """The old setup page and import granted admin rights on the user."""
        self._grant_directly('can_invite_members', 'can_manage_organization')

        assign_organization_member(self.user)
        user = self._reload_user()

        self.assertFalse(user.has_perm('accounts.can_manage_organization'))
        self.assertFalse(user.has_perm('accounts.can_invite_members'))

    def test_demoting_keeps_a_per_user_report_grant(self):
        self._grant_directly('can_view_all_reports')

        assign_organization_member(self.user)

        self.assertTrue(self._reload_user().has_perm('accounts.can_view_all_reports'))

    def test_promoting_drops_direct_grants_the_group_covers(self):
        self._grant_directly('can_manage_organization')

        assign_organization_admin(self.user)

        self.assertFalse(self._reload_user().user_permissions.exists())

    def test_a_renamed_permission_is_found_by_codename(self):
        Permission.objects.filter(codename='can_manage_questionnaires').update(
            name='Something else')

        ensure_permission_groups()
        assign_organization_admin(self.user)

        self.assertTrue(self._reload_user().has_perm('accounts.can_manage_questionnaires'))

    def test_admin_group_never_carries_api_access(self):
        """API access is off for everyone and granted per user, admins too."""
        group = Group.objects.get(name=ORG_ADMIN_GROUP)

        ensure_permission_groups()
        self.assertFalse(group.permissions.filter(codename='can_use_api').exists())

        # A group without permissions is filled anew.
        group.permissions.clear()
        ensure_permission_groups()
        self.assertTrue(group.permissions.exists())
        self.assertFalse(group.permissions.filter(codename='can_use_api').exists())

    def test_remove_from_all_org_groups_preserves_groups(self):
        assign_organization_admin(self.user)
        remove_from_all_org_groups(self.user)

        self.assertFalse(self.user.groups.filter(name=ORG_ADMIN_GROUP).exists())
        self.assertFalse(self.user.groups.filter(name=ORG_MEMBER_GROUP).exists())
        # The Group objects themselves must still exist — other users depend on them.
        self.assertTrue(Group.objects.filter(name=ORG_ADMIN_GROUP).exists())
        self.assertTrue(Group.objects.filter(name=ORG_MEMBER_GROUP).exists())


class PermissionDecoratorTestCase(TestCase):
    """The decorators are built by a shared factory in permissions.py.

    Both call styles have to keep working — @decorator is what the codebase
    uses today, @decorator(redirect_url=...) is not used anywhere and would
    otherwise break unnoticed.
    """

    def setUp(self):
        ensure_permission_groups()
        self.org = OrganizationFactory()
        self.user = UserFactory()
        UserProfileFactory(user=self.user, organization=self.org)
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        # The decorators report denials through the message framework.
        # CookieStorage, not the configured default: SessionStorage wants a
        # session, which a RequestFactory request does not have.
        self.request._messages = CookieStorage(self.request)

    @staticmethod
    def _view(request):
        return HttpResponse('reached')

    def test_bare_decorator_lets_a_permitted_user_through(self):
        assign_organization_admin(self.user)
        self.request.user = User.objects.get(pk=self.user.pk)

        view = can_manage_organization_required(self._view)

        self.assertEqual(view(self.request).content, b'reached')

    def test_bare_decorator_redirects_without_the_permission(self):
        assign_organization_member(self.user)
        self.request.user = User.objects.get(pk=self.user.pk)

        response = can_manage_organization_required(self._view)(self.request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('admin_dashboard'))

    def test_called_decorator_honours_a_custom_redirect(self):
        assign_organization_member(self.user)
        self.request.user = User.objects.get(pk=self.user.pk)

        view = can_manage_organization_required(redirect_url='home')(self._view)
        response = view(self.request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home'))

    def test_as_json_answers_403_instead_of_redirecting(self):
        assign_organization_member(self.user)
        self.request.user = User.objects.get(pk=self.user.pk)

        view = can_manage_organization_required(as_json=True)(self._view)
        response = view(self.request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_as_json_queues_no_message(self):
        """A queued message would surface on whatever page is opened next."""
        assign_organization_member(self.user)
        self.request.user = User.objects.get(pk=self.user.pk)

        can_manage_organization_required(as_json=True)(self._view)(self.request)
        self.assertEqual(len(self.request._messages), 0)

        # Control, so the assertion above cannot pass for the wrong reason:
        # the redirecting variant does queue one.
        can_manage_organization_required(self._view)(self.request)
        self.assertEqual(len(self.request._messages), 1)

    def test_decorated_view_keeps_its_name(self):
        view = can_manage_organization_required(self._view)
        self.assertEqual(view.__name__, '_view')


class LoginRequiredTestCase(TestCase):
    """Our login_required stands in for Django's, plus an as_json mode."""

    def setUp(self):
        self.request = RequestFactory().get('/')

    @staticmethod
    def _view(request):
        return JsonResponse({'ok': True})

    def test_bare_decorator_still_redirects_like_djangos(self):
        self.request.user = AnonymousUser()

        response = login_required(self._view)(self.request)

        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response.url)

    def test_login_url_is_still_honoured(self):
        self.request.user = AnonymousUser()

        view = login_required(login_url='/elsewhere/')(self._view)
        response = view(self.request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/elsewhere/', response.url)

    def test_as_json_answers_401_instead_of_redirecting(self):
        self.request.user = AnonymousUser()

        response = login_required(as_json=True)(self._view)(self.request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_logged_in_user_passes_through(self):
        self.request.user = UserFactory()

        for view in (login_required(self._view),
                     login_required(as_json=True)(self._view)):
            self.assertEqual(view(self.request).status_code, 200)
