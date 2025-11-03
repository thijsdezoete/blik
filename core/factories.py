"""
Factory definitions for core models
"""
import factory
from factory.django import DjangoModelFactory
from django.contrib.auth.models import User
from .models import Organization


class UserFactory(DjangoModelFactory):
    """Factory for creating test users"""

    class Meta:
        model = User
        django_get_or_create = ('username',)

    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda obj: f'{obj.username}@test.local')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True
    is_staff = False
    is_superuser = False

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        """Set password for user"""
        if extracted:
            obj.set_password(extracted)
        else:
            obj.set_password('testpass123')


class AdminUserFactory(UserFactory):
    """Factory for creating admin users"""

    is_staff = True
    is_superuser = True
    username = factory.Sequence(lambda n: f'admin{n}')


class OrganizationFactory(DjangoModelFactory):
    """Factory for creating test organizations"""

    class Meta:
        model = Organization
        django_get_or_create = ('name',)

    name = factory.Sequence(lambda n: f'Test Organization {n}')
    email = factory.LazyAttribute(lambda obj: f'admin@{obj.name.lower().replace(" ", "")}.local')
    is_active = True

    # Email settings (optional)
    smtp_host = ''
    smtp_port = 587
    smtp_username = ''
    smtp_use_tls = True
    from_email = factory.LazyAttribute(lambda obj: obj.email)

    # Report settings
    min_responses_for_anonymity = 3
    auto_send_report_email = True

    # Registration settings
    allow_registration = False
    default_users_can_create_cycles = False
