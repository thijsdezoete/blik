"""Permission tests for the questionnaire views in blik/admin_views.py.

Creating and editing questionnaires is gated by the dedicated
`can_manage_questionnaires` permission — organization members that only have
`@login_required` must not get through.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import (
    assign_organization_admin,
    assign_organization_member,
    ensure_permission_groups,
)
from core.models import Organization
from questionnaires.models import Questionnaire


class QuestionnairePermissionTestCase(TestCase):
    def setUp(self):
        ensure_permission_groups()
        self.org = Organization.objects.create(name='Acme', email='org@acme.example')

        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=self.org)
        assign_organization_admin(self.admin)

        self.member = User.objects.create_user(
            username='member', email='member@acme.example', password='pw')
        UserProfile.objects.create(user=self.member, organization=self.org)
        assign_organization_member(self.member)

        self.questionnaire = Questionnaire.objects.create(
            name='Professional Skills', organization=self.org)


class QuestionnaireGroupPermissionTests(QuestionnairePermissionTestCase):
    def test_admin_group_carries_the_permission(self):
        admin = User.objects.get(pk=self.admin.pk)
        self.assertTrue(admin.has_perm('accounts.can_manage_questionnaires'))

    def test_member_group_does_not_carry_the_permission(self):
        member = User.objects.get(pk=self.member.pk)
        self.assertFalse(member.has_perm('accounts.can_manage_questionnaires'))

    def test_demoting_an_admin_removes_the_permission(self):
        assign_organization_member(self.admin)
        admin = User.objects.get(pk=self.admin.pk)
        self.assertFalse(admin.has_perm('accounts.can_manage_questionnaires'))


class QuestionnaireCreateAccessTests(QuestionnairePermissionTestCase):
    def test_member_cannot_open_the_create_form(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('questionnaire_create'))
        self.assertRedirects(response, reverse('questionnaire_list'))

    def test_member_cannot_create_a_questionnaire(self):
        self.client.force_login(self.member)
        self.client.post(reverse('questionnaire_create'), {'name': 'Sneaky'})
        self.assertFalse(Questionnaire.objects.filter(name='Sneaky').exists())

    def test_admin_can_create_a_questionnaire(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('questionnaire_create'), {'name': 'Leadership'})
        self.assertTrue(Questionnaire.objects.filter(
            name='Leadership', organization=self.org).exists())


class QuestionnaireEditAccessTests(QuestionnairePermissionTestCase):
    def _edit_url(self):
        return reverse('questionnaire_edit', args=[self.questionnaire.uuid])

    def test_member_cannot_open_the_edit_form(self):
        self.client.force_login(self.member)
        response = self.client.get(self._edit_url())
        self.assertRedirects(response, reverse('questionnaire_list'))

    def test_member_cannot_rename_a_questionnaire(self):
        self.client.force_login(self.member)
        self.client.post(self._edit_url(), {'action': 'save_info', 'name': 'Renamed', 'source_language': 'en'})

        self.questionnaire.refresh_from_db()
        self.assertEqual(self.questionnaire.name, 'Professional Skills')

    def test_member_cannot_add_a_section(self):
        self.client.force_login(self.member)
        section_count = self.questionnaire.sections.count()

        self.client.post(self._edit_url(), {
            'action': 'add_section',
            'section_title': 'Injected',
        })

        self.assertEqual(self.questionnaire.sections.count(), section_count)

    def test_admin_can_rename_a_questionnaire(self):
        self.client.force_login(self.admin)
        self.client.post(self._edit_url(), {'action': 'save_info', 'name': 'Renamed', 'source_language': 'en'})

        self.questionnaire.refresh_from_db()
        self.assertEqual(self.questionnaire.name, 'Renamed')


class QuestionnaireListVisibilityTests(QuestionnairePermissionTestCase):
    def test_member_still_sees_the_list_without_edit_controls(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse('questionnaire_list'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('questionnaire_create'))
        self.assertNotContains(
            response, reverse('questionnaire_edit', args=[self.questionnaire.uuid]))

    def test_admin_sees_the_edit_controls(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('questionnaire_list'))

        self.assertContains(response, reverse('questionnaire_create'))
        self.assertContains(
            response, reverse('questionnaire_edit', args=[self.questionnaire.uuid]))


class QuestionnaireImportAccessTests(QuestionnairePermissionTestCase):
    def test_import_needs_the_questionnaire_permission(self):
        """can_manage_organization alone must not create questionnaires."""
        from django.contrib.auth.models import Group, Permission
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.permissions import ORG_ADMIN_GROUP

        Group.objects.get(name=ORG_ADMIN_GROUP).permissions.remove(
            Permission.objects.get(codename='can_manage_questionnaires'))
        upload = SimpleUploadedFile(
            'data.json',
            b'{"version": "1.0", "organization": {"name": "Acme"}, "questionnaires": [{"name": "Smuggled", "sections": []}]}',
            content_type='application/json')

        self.client.force_login(self.admin)
        self.client.post(reverse('account:import_data'), {
            'import_file': upload, 'import_questionnaires': 'on'})

        self.assertFalse(Questionnaire.objects.filter(name='Smuggled').exists())
