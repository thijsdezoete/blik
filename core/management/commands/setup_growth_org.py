"""
Management command to create or update the "Blik Growth Leads" organization.

Usage:
    python manage.py setup_growth_org
"""
from django.core.management.base import BaseCommand
from core.models import Organization


class Command(BaseCommand):
    help = 'Create or update the "Blik Growth Leads" organization for landing page assessments'

    def handle(self, *args, **options):
        """Create or update the growth leads organization."""

        # Create or get the organization
        org, created = Organization.objects.get_or_create(
            name="Blik Growth Leads",
            defaults={
                'email': 'growth@blik360.com',
                'min_responses_for_anonymity': 1,  # Allow single self-assessment
                'auto_send_report_email': False,  # Custom email sent from landing app
                'allow_registration': False,
                'default_users_can_create_cycles': False,
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully created "Blik Growth Leads" organization'
                )
            )
            self.stdout.write(f'  ID: {org.id}')
        else:
            # Update settings if organization already exists
            org.min_responses_for_anonymity = 1
            org.auto_send_report_email = False  # Custom email sent from landing app
            org.save()

            self.stdout.write(
                self.style.WARNING(
                    f'"Blik Growth Leads" organization already exists (updated settings)'
                )
            )
            self.stdout.write(f'  ID: {org.id}')

        # Provide instructions for next steps
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Next steps:'))
        self.stdout.write(f'  1. Add to .env: GROWTH_ORG_ID={org.id}')
        self.stdout.write('  2. Create API token for landing service')
        self.stdout.write('  3. Run: python manage.py create_growth_questionnaire')
        self.stdout.write(f'  4. Note questionnaire UUID and add to .env: GROWTH_QUESTIONNAIRE_UUID=<uuid>')
