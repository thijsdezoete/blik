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
        import os
        from django.conf import settings

        # Get values from arguments or environment
        org_name = options.get('name') or os.getenv('ORGANIZATION_NAME', 'Blik Organization')
        org_email = options.get('email') or os.getenv('DEFAULT_FROM_EMAIL', 'noreply@example.com')

        # Get email settings from Django settings (which come from env vars)
        smtp_host = os.getenv('EMAIL_HOST', '')
        smtp_port = int(os.getenv('EMAIL_PORT', '587'))
        smtp_username = os.getenv('EMAIL_HOST_USER', '')
        smtp_password = os.getenv('EMAIL_HOST_PASSWORD', '')
        smtp_use_tls = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 'yes')
        from_email = os.getenv('DEFAULT_FROM_EMAIL', org_email)

        # Create or update the organization
        org, created = Organization.objects.get_or_create(
            id=1,  # Always use ID 1 for single-org setup
            defaults={
                'name': org_name,
                'email': org_email,
                'smtp_host': smtp_host,
                'smtp_port': smtp_port,
                'smtp_username': smtp_username,
                'smtp_password': smtp_password,
                'smtp_use_tls': smtp_use_tls,
                'from_email': from_email,
                'is_active': True,
            }
        )

        if not created:
            # Update existing organization
            org.name = org_name
            org.email = org_email
            org.smtp_host = smtp_host
            org.smtp_port = smtp_port
            org.smtp_username = smtp_username
            org.smtp_password = smtp_password
            org.smtp_use_tls = smtp_use_tls
            org.from_email = from_email
            org.save()
            self.stdout.write(
                self.style.SUCCESS(f'Updated organization: {org.name}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Created organization: {org.name}')
            )

        # Display configuration
        self.stdout.write('\nOrganization Configuration:')
        self.stdout.write(f'  Name: {org.name}')
        self.stdout.write(f'  Email: {org.email}')
        self.stdout.write(f'  SMTP Host: {org.smtp_host or "(not configured)"}')
        self.stdout.write(f'  SMTP Port: {org.smtp_port}')
        self.stdout.write(f'  SMTP TLS: {org.smtp_use_tls}')
        self.stdout.write(f'  From Email: {org.from_email}')
