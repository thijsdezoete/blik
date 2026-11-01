"""Make the database agree with Stripe where a webhook was missed. Safe to run more than once.

- A subscription that Stripe has canceled, or no longer has, is marked canceled here. No email:
  the customer canceled it long ago.
- A Stripe customer that was deleted is removed from its organization, so the next checkout makes
  a new one and does not fail on "No such customer".
"""
import stripe
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Organization
from subscriptions.fulfilment import _ts
from subscriptions.models import Subscription


def _retrieve(resource, object_id):
    """The Stripe object as a dict, or None when Stripe does not have it."""
    try:
        return resource.retrieve(object_id).to_dict()
    except stripe.InvalidRequestError as e:
        if e.code == 'resource_missing':
            return None
        raise


class Command(BaseCommand):
    help = 'Mark subscriptions canceled in Stripe as canceled, and forget deleted Stripe customers'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would change, change nothing')

    def handle(self, *args, dry_run=False, **options):
        stripe.api_key = settings.STRIPE_SECRET_KEY

        for subscription in Subscription.objects.exclude(status='canceled').select_related('organization'):
            remote = _retrieve(stripe.Subscription, subscription.stripe_subscription_id)
            if remote is not None and remote['status'] != 'canceled':
                continue
            ended = _ts(remote.get('ended_at') or remote.get('canceled_at')) if remote else None
            self.stdout.write(f'{subscription.organization}: subscription {subscription.stripe_subscription_id} '
                              f'is {"canceled" if remote else "missing"} in Stripe, {subscription.status} here')
            if not dry_run:
                subscription.status = 'canceled'
                subscription.canceled_at = subscription.canceled_at or ended or timezone.now()
                subscription.save(update_fields=['status', 'canceled_at', 'updated_at'])

        for organization in Organization.objects.exclude(stripe_customer_id=''):
            customer = _retrieve(stripe.Customer, organization.stripe_customer_id)
            if customer is not None and not customer.get('deleted'):
                continue
            self.stdout.write(f'{organization}: customer {organization.stripe_customer_id} is deleted in Stripe')
            if not dry_run:
                organization.stripe_customer_id = ''
                organization.save(update_fields=['stripe_customer_id'])
