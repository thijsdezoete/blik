"""One-off: give every paying organization its Stripe customer, so invoices and the portal work.

Subscribers get the customer of their subscription. Round buyers get the
customer of their newest checkout, read from Stripe. Organizations that
already have one are not changed. Safe to run more than once.
"""
import stripe
from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import Organization
from subscriptions.models import CheckoutFulfilment, Subscription


class Command(BaseCommand):
    help = 'Set Organization.stripe_customer_id from subscriptions and past checkouts'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would change, change nothing')

    def handle(self, *args, dry_run=False, **options):
        stripe.api_key = settings.STRIPE_SECRET_KEY
        for organization in Organization.objects.filter(stripe_customer_id=''):
            customer_id = (Subscription.objects.filter(organization=organization)
                           .values_list('stripe_customer_id', flat=True).first())
            if not customer_id:
                customer_id = self._from_checkouts(organization)
            if not customer_id:
                continue
            self.stdout.write(f'{organization.pk} {organization.name}: {customer_id}')
            if not dry_run:
                organization.stripe_customer_id = customer_id
                organization.save(update_fields=['stripe_customer_id'])

    def _from_checkouts(self, organization):
        fulfilments = (CheckoutFulfilment.objects
                       .filter(organization=organization, outcome='fulfilled')
                       .order_by('-created_at'))
        for fulfilment in fulfilments:
            try:
                customer_id = stripe.checkout.Session.retrieve(fulfilment.stripe_session_id)['customer']
            except stripe.StripeError as e:
                self.stderr.write(f'{fulfilment.stripe_session_id}: {e}')
                continue
            if customer_id:
                return customer_id
        return None
