"""
Management command to list data summaries for GDPR compliance

Usage:
    python manage.py gdpr_list_data --users
    python manage.py gdpr_list_data --reviewees
    python manage.py gdpr_list_data --user-id 123
    python manage.py gdpr_list_data --reviewee-id 456
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from accounts.models import Reviewee
from core.gdpr import GDPRDeletionService
import json


class Command(BaseCommand):
    help = 'List GDPR data summaries for users and reviewees'

    def add_arguments(self, parser):
        parser.add_argument(
            '--users',
            action='store_true',
            help='List all users'
        )
        parser.add_argument(
            '--reviewees',
            action='store_true',
            help='List all reviewees'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Show detailed summary for specific user ID'
        )
        parser.add_argument(
            '--reviewee-id',
            type=int,
            help='Show detailed summary for specific reviewee ID'
        )
        parser.add_argument(
            '--organization',
            type=int,
            help='Filter by organization ID'
        )

    def handle(self, *args, **options):
        if options['user_id']:
            self._show_user_summary(options['user_id'])
        elif options['reviewee_id']:
            self._show_reviewee_summary(options['reviewee_id'])
        elif options['users']:
            self._list_users(options.get('organization'))
        elif options['reviewees']:
            self._list_reviewees(options.get('organization'))
        else:
            raise CommandError('Please specify --users, --reviewees, --user-id, or --reviewee-id')

    def _show_user_summary(self, user_id):
        """Show detailed summary for a user"""
        try:
            summary = GDPRDeletionService.get_user_data_summary(user_id)
            self.stdout.write(self.style.SUCCESS(f'\nUser {user_id} Data Summary:'))
            self.stdout.write(json.dumps(summary, indent=2, default=str))
        except User.DoesNotExist:
            raise CommandError(f'User {user_id} does not exist')
        except Exception as e:
            raise CommandError(f'Error: {str(e)}')

    def _show_reviewee_summary(self, reviewee_id):
        """Show detailed summary for a reviewee"""
        try:
            summary = GDPRDeletionService.get_reviewee_data_summary(reviewee_id)
            self.stdout.write(self.style.SUCCESS(f'\nReviewee {reviewee_id} Data Summary:'))
            self.stdout.write(json.dumps(summary, indent=2, default=str))
        except Reviewee.DoesNotExist:
            raise CommandError(f'Reviewee {reviewee_id} does not exist')
        except Exception as e:
            raise CommandError(f'Error: {str(e)}')

    def _list_users(self, org_id=None):
        """List all users"""
        users = User.objects.all()

        if org_id:
            users = users.filter(profile__organization_id=org_id)

        self.stdout.write(self.style.SUCCESS(f'\nTotal users: {users.count()}\n'))

        for user in users:
            try:
                profile = user.profile
                org_name = profile.organization.name
            except:
                org_name = 'No profile'

            self.stdout.write(
                f'ID: {user.id:4d} | {user.username:20s} | {user.email:30s} | {org_name}'
            )

    def _list_reviewees(self, org_id=None):
        """List all reviewees"""
        reviewees = Reviewee.objects.select_related('organization')

        if org_id:
            reviewees = reviewees.filter(organization_id=org_id)

        self.stdout.write(self.style.SUCCESS(f'\nTotal reviewees: {reviewees.count()}\n'))

        for reviewee in reviewees:
            from reviews.models import ReviewCycle
            cycle_count = ReviewCycle.objects.filter(reviewee=reviewee).count()

            active_str = 'Active' if reviewee.is_active else 'Inactive'
            self.stdout.write(
                f'ID: {reviewee.id:4d} | {reviewee.name:25s} | {reviewee.email:30s} | '
                f'Cycles: {cycle_count:3d} | {active_str:8s} | {reviewee.organization.name}'
            )
