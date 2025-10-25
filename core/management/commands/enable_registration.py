"""
Management command to enable/disable registration for an organization
"""
from django.core.management.base import BaseCommand
from core.models import Organization


class Command(BaseCommand):
    help = 'Enable or disable user registration for an organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id',
            type=int,
            help='Organization ID (leave empty for first organization)',
        )
        parser.add_argument(
            '--enable',
            action='store_true',
            help='Enable registration',
        )
        parser.add_argument(
            '--disable',
            action='store_true',
            help='Disable registration',
        )
        parser.add_argument(
            '--allow-cycle-creation',
            action='store_true',
            help='Allow new users to create cycles for others by default',
        )

    def handle(self, *args, **options):
        org_id = options.get('org_id')
        enable = options.get('enable')
        disable = options.get('disable')
        allow_cycle_creation = options.get('allow_cycle_creation')

        if enable and disable:
            self.stdout.write(self.style.ERROR('Cannot use both --enable and --disable'))
            return

        # Get organization
        if org_id:
            try:
                org = Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Organization with ID {org_id} not found'))
                return
        else:
            org = Organization.objects.first()
            if not org:
                self.stdout.write(self.style.ERROR('No organizations found'))
                return

        # Update settings
        if enable:
            org.allow_registration = True
            self.stdout.write(self.style.SUCCESS(f'Registration enabled for "{org.name}"'))

        if disable:
            org.allow_registration = False
            self.stdout.write(self.style.SUCCESS(f'Registration disabled for "{org.name}"'))

        if allow_cycle_creation:
            org.default_users_can_create_cycles = True
            self.stdout.write(
                self.style.SUCCESS(f'New users will be able to create cycles for others by default')
            )

        org.save()

        # Show current status
        self.stdout.write(self.style.WARNING('\nCurrent settings:'))
        self.stdout.write(f'  Organization: {org.name}')
        self.stdout.write(f'  Registration: {"Enabled" if org.allow_registration else "Disabled"}')
        self.stdout.write(f'  Default cycle creation permission: {"Enabled" if org.default_users_can_create_cycles else "Self-only"}')
        self.stdout.write(f'\nRegistration URL: /accounts/register/')
        self.stdout.write(f'Login URL: /accounts/login/')
