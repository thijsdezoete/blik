from django.core.management.base import BaseCommand
from reviews.models import ReviewerToken
from notifications.utils import send_feedback_invitation


class Command(BaseCommand):
    help = 'Send feedback invitation email for a specific token'

    def add_arguments(self, parser):
        parser.add_argument('token', type=str, help='Reviewer token UUID')
        parser.add_argument('email', type=str, help='Reviewer email address')

    def handle(self, *args, **options):
        token_uuid = options['token']
        email = options['email']

        try:
            token = ReviewerToken.objects.get(token=token_uuid)
        except ReviewerToken.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Token {token_uuid} not found'))
            return

        if token.is_completed:
            self.stdout.write(self.style.WARNING(f'Token already completed'))
            return

        try:
            send_feedback_invitation(token, email)
            self.stdout.write(self.style.SUCCESS(
                f'Sent invitation to {email} for {token.get_category_display()} feedback'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to send email: {str(e)}'))
