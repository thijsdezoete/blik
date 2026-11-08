"""
Factory definitions for accounts models
"""
import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import timedelta
from .models import UserProfile, OrganizationInvitation, Reviewee, OrgUnit, OrgUnitMembership
from core.factories import UserFactory, OrganizationFactory


class UserProfileFactory(DjangoModelFactory):
    """Factory for creating user profiles"""

    class Meta:
        model = UserProfile

    user = factory.SubFactory(UserFactory)
    organization = factory.SubFactory(OrganizationFactory)
    can_create_cycles_for_others = False
    has_seen_welcome = False


class OrganizationInvitationFactory(DjangoModelFactory):
    """Factory for creating organization invitations"""

    class Meta:
        model = OrganizationInvitation

    organization = factory.SubFactory(OrganizationFactory)
    email = factory.Faker('email')
    invited_by = factory.SubFactory(UserFactory)
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))
    accepted_at = None


class RevieweeFactory(DjangoModelFactory):
    """Factory for creating reviewees"""

    class Meta:
        model = Reviewee

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Faker('name')
    email = factory.Faker('email')
    department = factory.Faker('job')
    is_active = True


class OrgUnitFactory(DjangoModelFactory):
    """Factory for creating units in the org chart"""

    class Meta:
        model = OrgUnit

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Unit {n}')
    display_order = 0


class OrgUnitMembershipFactory(DjangoModelFactory):
    """Factory for creating org unit memberships"""

    class Meta:
        model = OrgUnitMembership

    unit = factory.SubFactory(OrgUnitFactory)
    reviewee = factory.SubFactory(RevieweeFactory)
    # role defaults are derived from row in the model's save()
    row = 0
    col = 0
