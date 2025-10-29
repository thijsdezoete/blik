"""
Management command to delete or anonymize a user (GDPR compliance)

Usage:
    python manage.py gdpr_delete_user <user_id> [--hard]
    python manage.py gdpr_delete_user 123
    python manage.py gdpr_delete_user 123 --hard
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from core.gdpr import GDPRDeletionService
import json


class Command(BaseCommand):
    help = 'Delete or anonymize a user for GDPR compliance'

    def add_arguments(self, parser):
        parser.add_argument(
            'user_id',
            type=int,
            help='ID of the user to delete'
        )
        parser.add_argument(
            '--hard',
            action='store_true',
            help='Perform hard delete (complete removal). Default is soft delete (anonymization).'
        )
        parser.add_argument(
            '--summary',
            action='store_true',
            help='Show data summary without deleting'
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        hard_delete = options['hard']
        show_summary = options['summary']

        # Check if user exists
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise CommandError(f'User with ID {user_id} does not exist')

        # Show summary if requested
        if show_summary:
            self.stdout.write(self.style.SUCCESS(f'\nData summary for User {user_id}:'))
            summary = GDPRDeletionService.get_user_data_summary(user_id)
            self.stdout.write(json.dumps(summary, indent=2))
            return

        # Confirm deletion
        deletion_type = 'HARD DELETE (complete removal)' if hard_delete else 'SOFT DELETE (anonymization)'
        self.stdout.write(
            self.style.WARNING(
                f'\n{deletion_type} for User {user_id}:\n'
                f'  Username: {user.username}\n'
                f'  Email: {user.email}\n'
                f'  Name: {user.first_name} {user.last_name}\n'
            )
        )

        # Get summary
        summary = GDPRDeletionService.get_user_data_summary(user_id)
        self.stdout.write(
            self.style.WARNING(
                f'  Created review cycles: {summary["created_cycles"]}\n'
            )
        )

        if hard_delete:
            self.stdout.write(
                self.style.ERROR(
                    '\nWARNING: This will permanently delete the user account.\n'
                    'The user profile will also be deleted.\n'
                )
            )
        else:
            self.stdout.write(
                self.style.NOTICE(
                    '\nThis will anonymize the user data:\n'
                    '  - Username, email, first name, last name will be anonymized\n'
                    '  - Account will be deactivated\n'
                    '  - Profile structure preserved\n'
                )
            )

        confirm = input('\nType "yes" to confirm: ')
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.ERROR('Deletion cancelled'))
            return

        # Perform deletion
        try:
            result = GDPRDeletionService.delete_user(
                user_id,
                hard_delete=hard_delete,
                performed_by=None  # CLI command
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSuccessfully {result["deletion_type"]} deleted User {user_id}\n'
                )
            )
            self.stdout.write(json.dumps(result, indent=2))

        except Exception as e:
            raise CommandError(f'Error during deletion: {str(e)}')
