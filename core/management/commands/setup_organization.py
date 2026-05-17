import os

from django.core.management.base import BaseCommand
from core.models import Organization


class Command(BaseCommand):
    help = 'Create or update the default organization from environment variables'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            help='Organization name (defaults to ORGANIZATION_NAME env var)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Organization email (defaults to DEFAULT_FROM_EMAIL env var)',
        )

    def handle(self, *args, **options):
        # Check if org already exists
        try:
            org = Organization.objects.get(id=1)
            created = False
        except Organization.DoesNotExist:
            org = Organization(id=1)
            created = True

        if created:
            # First run: use env vars with sensible defaults
            org.name = options.get('name') or os.getenv('ORGANIZATION_NAME', 'Blik Organization')
            org.email = options.get('email') or os.getenv('DEFAULT_FROM_EMAIL', 'noreply@example.com')
            org.smtp_host = os.getenv('EMAIL_HOST', '')
            org.smtp_port = int(os.getenv('EMAIL_PORT', '587'))
            org.smtp_username = os.getenv('EMAIL_HOST_USER', '')
            org.smtp_password = os.getenv('EMAIL_HOST_PASSWORD', '')
            org.smtp_use_tls = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
            org.from_email = os.getenv('DEFAULT_FROM_EMAIL', org.email)
            org.is_active = True
            org.save()
            self.stdout.write(
                self.style.SUCCESS(f'Created organization: {org.name}')
            )
        else:
            # Subsequent runs: only update fields whose env vars are explicitly set
            updated_fields = []

            if options.get('name'):
                org.name = options['name']
                updated_fields.append('name')
            elif os.environ.get('ORGANIZATION_NAME'):
                org.name = os.environ['ORGANIZATION_NAME']
                updated_fields.append('name')

            if options.get('email'):
                org.email = options['email']
                updated_fields.append('email')
            elif os.environ.get('DEFAULT_FROM_EMAIL'):
                org.email = os.environ['DEFAULT_FROM_EMAIL']
                org.from_email = os.environ['DEFAULT_FROM_EMAIL']
                updated_fields.extend(['email', 'from_email'])

            if os.environ.get('EMAIL_HOST'):
                org.smtp_host = os.environ['EMAIL_HOST']
                updated_fields.append('smtp_host')

            if os.environ.get('EMAIL_PORT'):
                org.smtp_port = int(os.environ['EMAIL_PORT'])
                updated_fields.append('smtp_port')

            if os.environ.get('EMAIL_HOST_USER'):
                org.smtp_username = os.environ['EMAIL_HOST_USER']
                updated_fields.append('smtp_username')

            if os.environ.get('EMAIL_HOST_PASSWORD'):
                org.smtp_password = os.environ['EMAIL_HOST_PASSWORD']
                updated_fields.append('smtp_password')

            if os.environ.get('EMAIL_USE_TLS'):
                org.smtp_use_tls = os.environ['EMAIL_USE_TLS'].lower() in ('true', '1', 'yes')
                updated_fields.append('smtp_use_tls')

            if updated_fields:
                org.save(update_fields=updated_fields)
                self.stdout.write(
                    self.style.SUCCESS(f'Updated organization: {org.name} (fields: {", ".join(updated_fields)})')
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f'Organization already configured: {org.name} (no changes)')
                )

        # Display configuration
        self.stdout.write('\nOrganization Configuration:')
        self.stdout.write(f'  Name: {org.name}')
        self.stdout.write(f'  Email: {org.email}')
        self.stdout.write(f'  SMTP Host: {org.smtp_host or "(not configured)"}')
        self.stdout.write(f'  SMTP Port: {org.smtp_port}')
        self.stdout.write(f'  SMTP TLS: {org.smtp_use_tls}')
        self.stdout.write(f'  From Email: {org.from_email}')
