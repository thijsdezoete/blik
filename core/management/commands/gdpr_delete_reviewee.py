"""
Management command to delete or anonymize a reviewee (GDPR compliance)

Usage:
    python manage.py gdpr_delete_reviewee <reviewee_id> [--hard] [--full-anonymization]
    python manage.py gdpr_delete_reviewee 123
    python manage.py gdpr_delete_reviewee 123 --hard
    python manage.py gdpr_delete_reviewee 123 --full-anonymization
"""

from django.core.management.base import BaseCommand, CommandError
from accounts.models import Reviewee
from core.gdpr import GDPRDeletionService
import json


class Command(BaseCommand):
    help = 'Delete or anonymize a reviewee for GDPR compliance'

    def add_arguments(self, parser):
        parser.add_argument(
            'reviewee_id',
            type=int,
            help='ID of the reviewee to delete'
        )
        parser.add_argument(
            '--hard',
            action='store_true',
            help='Perform hard delete (complete removal with all review cycles). Default is soft delete (anonymization).'
        )
        parser.add_argument(
            '--full-anonymization',
            action='store_true',
            help='Anonymize reviewee AND all reviewer emails in their cycles'
        )
        parser.add_argument(
            '--summary',
            action='store_true',
            help='Show data summary without deleting'
        )

    def handle(self, *args, **options):
        reviewee_id = options['reviewee_id']
        hard_delete = options['hard']
        full_anonymization = options['full_anonymization']
        show_summary = options['summary']

        # Validate options
        if hard_delete and full_anonymization:
            raise CommandError('Cannot use both --hard and --full-anonymization')

        # Check if reviewee exists
        try:
            reviewee = Reviewee.objects.get(pk=reviewee_id)
        except Reviewee.DoesNotExist:
            raise CommandError(f'Reviewee with ID {reviewee_id} does not exist')

        # Show summary if requested
        if show_summary:
            self.stdout.write(self.style.SUCCESS(f'\nData summary for Reviewee {reviewee_id}:'))
            summary = GDPRDeletionService.get_reviewee_data_summary(reviewee_id)
            self.stdout.write(json.dumps(summary, indent=2))
            return

        # Determine deletion type
        if hard_delete:
            deletion_type = 'HARD DELETE (complete removal)'
        elif full_anonymization:
            deletion_type = 'FULL ANONYMIZATION (reviewee + reviewer emails)'
        else:
            deletion_type = 'SOFT DELETE (anonymization)'

        self.stdout.write(
            self.style.WARNING(
                f'\n{deletion_type} for Reviewee {reviewee_id}:\n'
                f'  Name: {reviewee.name}\n'
                f'  Email: {reviewee.email}\n'
                f'  Department: {reviewee.department}\n'
                f'  Organization: {reviewee.organization.name}\n'
            )
        )

        # Get summary
        summary = GDPRDeletionService.get_reviewee_data_summary(reviewee_id)
        self.stdout.write(
            self.style.WARNING(
                f'  Total review cycles: {summary["review_cycles"]["total"]}\n'
                f'  Active cycles: {summary["review_cycles"]["active"]}\n'
                f'  Completed cycles: {summary["review_cycles"]["completed"]}\n'
                f'  Reviewer tokens: {summary["tokens"]}\n'
                f'  Responses: {summary["responses"]}\n'
                f'  Reports: {summary["reports"]}\n'
            )
        )

        if hard_delete:
            self.stdout.write(
                self.style.ERROR(
                    '\nWARNING: This will permanently delete:\n'
                    '  - Reviewee record\n'
                    '  - ALL review cycles\n'
                    '  - ALL reviewer tokens\n'
                    '  - ALL responses\n'
                    '  - ALL reports\n'
                )
            )
        elif full_anonymization:
            self.stdout.write(
                self.style.NOTICE(
                    '\nThis will anonymize:\n'
                    '  - Reviewee name, email, department\n'
                    '  - ALL reviewer emails in tokens\n'
                    '  - Review cycles, responses, reports preserved but anonymized\n'
                )
            )
        else:
            self.stdout.write(
                self.style.NOTICE(
                    '\nThis will anonymize the reviewee data:\n'
                    '  - Name, email, department will be anonymized\n'
                    '  - Account will be deactivated\n'
                    '  - Review cycles, responses, reports preserved\n'
                    '  - Reviewer emails in tokens are NOT anonymized\n'
                )
            )

        confirm = input('\nType "yes" to confirm: ')
        if confirm.lower() != 'yes':
            self.stdout.write(self.style.ERROR('Deletion cancelled'))
            return

        # Perform deletion
        try:
            if full_anonymization:
                result = GDPRDeletionService.delete_reviewee_and_anonymize_reviewer_emails(
                    reviewee_id,
                    performed_by=None  # CLI command
                )
            else:
                result = GDPRDeletionService.delete_reviewee(
                    reviewee_id,
                    hard_delete=hard_delete,
                    performed_by=None  # CLI command
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSuccessfully processed Reviewee {reviewee_id}\n'
                )
            )
            self.stdout.write(json.dumps(result, indent=2))

        except Exception as e:
            raise CommandError(f'Error during deletion: {str(e)}')
