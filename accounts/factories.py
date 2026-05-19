"""
Factory definitions for accounts models
"""
import factory
from factory.django import DjangoModelFactory
from django.utils import timezone
from datetime import timedelta
from .models import UserProfile, OrganizationInvitation, Reviewee, Team, TeamMembership
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


class TeamFactory(DjangoModelFactory):
    """Factory for creating teams (pyramids) in the org chart"""

    class Meta:
        model = Team

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f'Team {n}')
    display_order = 0
    shape = factory.LazyFunction(
        lambda: {'manager_cols': 3, 'member_rows': [{'cols': 5}]}
    )


class TeamMembershipFactory(DjangoModelFactory):
    """Factory for creating team memberships"""

    class Meta:
        model = TeamMembership

    team = factory.SubFactory(TeamFactory)
    reviewee = factory.SubFactory(RevieweeFactory)
    # role defaults are derived from row in the model's save()
    row = 0
    col = 0
