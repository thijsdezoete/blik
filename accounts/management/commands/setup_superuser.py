from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Create a superuser from environment variables if it does not exist'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            help='Admin username (defaults to DJANGO_SUPERUSER_USERNAME env var)',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Admin email (defaults to DJANGO_SUPERUSER_EMAIL env var)',
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Admin password (defaults to DJANGO_SUPERUSER_PASSWORD env var)',
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='Update existing superuser password if user exists',
        )

    def handle(self, *args, **options):
        import os

        User = get_user_model()

        # Get values from arguments or environment
        username = options.get('username') or os.getenv('DJANGO_SUPERUSER_USERNAME', 'admin')
        email = options.get('email') or os.getenv('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
        password = options.get('password') or os.getenv('DJANGO_SUPERUSER_PASSWORD', '')

        if not password:
            self.stdout.write(
                self.style.WARNING(
                    'No password provided. Set DJANGO_SUPERUSER_PASSWORD environment variable '
                    'or use --password argument to create/update superuser.'
                )
            )
            return

        try:
            user = User.objects.get(username=username)
            if options.get('update'):
                user.set_password(password)
                user.email = email
                user.is_superuser = True
                user.is_staff = True
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated superuser: {username}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'Superuser "{username}" already exists. Use --update to update password.'
                    )
                )
        except User.DoesNotExist:
            # Create new superuser
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created superuser: {username} ({email})'
                )
            )
