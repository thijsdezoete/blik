"""Live billing details from Stripe for the billing page. Nothing here is stored."""
import calendar
import logging
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

import stripe

from .fulfilment import _ts
from .utils import payment_error_text, stripe_customer_id

logger = logging.getLogger(__name__)


def money(amount, currency):
    """Stripe's amount in cents as {'amount': Decimal, 'currency': 'EUR'}."""
    return {'amount': Decimal(amount or 0) / 100, 'currency': (currency or 'eur').upper()}


def card_expires_before(card, moment):
    """True when the card's last valid day is before `moment` (a datetime)."""
    last_day = calendar.monthrange(card['exp_year'], card['exp_month'])[1]
    expires = datetime(card['exp_year'], card['exp_month'], last_day, 23, 59, 59, tzinfo=dt_timezone.utc)
    return expires < moment


def _invoices(customer_id):
    return [
        {
            'number': invoice['number'],
            'date': _ts(invoice['created']),
            'total': money(invoice['total'], invoice['currency']),
            'status': invoice['status'],
            'pdf_url': invoice['invoice_pdf'],
            'url': invoice['hosted_invoice_url'],
        }
        for invoice in stripe.Invoice.list(customer=customer_id, limit=24)['data']
        if invoice['status'] != 'draft'
    ]


def _payment_error(invoice):
    """Why the invoice's newest payment failed. Not the customer's newest payment: that can be a round purchase."""
    payments = ((invoice or {}).get('payments') or {}).get('data') or []
    intent_id = payments[0]['payment'].get('payment_intent') if payments else None
    if not intent_id:
        return None
    return payment_error_text(stripe.PaymentIntent.retrieve(intent_id).to_dict().get('last_payment_error'))


def live_details(organization, subscription):
    """Card, payment failure, next invoice and invoice list, or None when Stripe cannot be reached."""
    customer_id = stripe_customer_id(organization)
    details = {'invoices': [], 'card': None, 'payment_error': None, 'next_attempt': None, 'upcoming': None}
    if not customer_id:
        return details
    try:
        details['invoices'] = _invoices(customer_id)
        if subscription is None or subscription.status == 'canceled':
            return details

        # .to_dict(): StripeObject has no .get(). payment.payment_intent would be a 5th expand level, Stripe allows 4.
        stripe_sub = stripe.Subscription.retrieve(
            subscription.stripe_subscription_id,
            expand=['default_payment_method', 'latest_invoice.payments']).to_dict()
        method = stripe_sub['default_payment_method']
        if method and method['type'] == 'card':
            card = method['card']
            details['card'] = {
                'brand': card['brand'], 'last4': card['last4'],
                'exp_month': card['exp_month'], 'exp_year': card['exp_year'],
            }
            details['card']['expires_soon'] = card_expires_before(details['card'], subscription.current_period_end)

        if subscription.status in ('past_due', 'unpaid'):
            invoice = stripe_sub['latest_invoice']
            details['next_attempt'] = _ts(invoice['next_payment_attempt']) if invoice else None
            details['payment_error'] = _payment_error(invoice)
        elif not subscription.cancel_at_period_end:
            preview = stripe.Invoice.create_preview(subscription=subscription.stripe_subscription_id)
            details['upcoming'] = {
                'total': money(preview['amount_due'], preview['currency']),
                'date': _ts(preview['next_payment_attempt'] or preview['period_end']),
            }
    except stripe.StripeError:
        logger.exception('Could not load live billing details for organization %s', organization.pk)
        return None
    return details
