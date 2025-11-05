"""
Webhook delivery system.

Handles sending webhook events to registered endpoints with HMAC signatures.
"""
import requests
import hmac
import hashlib
import json
import logging
import threading
from django.utils import timezone
from .models import WebhookEndpoint, WebhookDelivery

logger = logging.getLogger("api")


def send_webhook(organization, event_type, payload):
    """
    Send webhook to all endpoints subscribed to this event.

    Args:
        organization: Organization instance
        event_type: String like "cycle.created", "feedback.submitted"
        payload: Dict of event data (will be wrapped in modern webhook format)

    Returns:
        int: Number of webhooks sent
    """
    from django.utils import timezone
    from django.db import transaction

    endpoints = WebhookEndpoint.objects.filter(
        organization=organization, is_active=True, events__contains=[event_type]
    )

    sent_count = 0
    for endpoint in endpoints:
        # Create delivery record
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type=event_type,
            payload=payload  # Store original payload for reference
        )

        # Deliver webhook asynchronously in a background thread
        # Use on_commit to ensure the delivery record is committed before the thread starts
        def start_delivery(delivery_id):
            thread = threading.Thread(
                target=_deliver_webhook_thread_safe,
                args=(delivery_id,),
                daemon=True  # Daemon thread won't prevent app shutdown
            )
            thread.start()

        transaction.on_commit(lambda d_id=delivery.id: start_delivery(d_id))
        sent_count += 1

    return sent_count


def _deliver_webhook_thread_safe(delivery_id):
    """
    Thread-safe wrapper for webhook delivery.

    Creates a new database connection for the thread to avoid
    connection sharing issues with Django ORM.

    Args:
        delivery_id: ID of WebhookDelivery to deliver
    """
    from django.db import connection

    try:
        # Close any existing connection to force a new one in this thread
        connection.close()

        # Fetch the delivery in this thread's connection
        delivery = WebhookDelivery.objects.get(id=delivery_id)
        deliver_webhook(delivery)
    except Exception as e:
        logger.error(f"Error in webhook delivery thread for delivery {delivery_id}: {str(e)}")


def deliver_webhook(delivery):
    """
    Deliver webhook with HMAC signature verification.

    Sends a modern webhook payload structure with event metadata wrapped around the data.

    Args:
        delivery: WebhookDelivery instance

    Raises:
        requests.RequestException: If delivery fails
    """
    from django.utils import timezone

    endpoint = delivery.endpoint

    # Prepare modern webhook payload structure
    webhook_payload = {
        "id": str(delivery.delivery_id),  # Non-enumerable UUID
        "event": delivery.event_type,
        "created": delivery.created_at.isoformat(),
        "data": delivery.payload,  # Original event data nested in "data"
    }

    # Serialize to JSON
    payload_json = json.dumps(webhook_payload, separators=(",", ":"))  # Compact JSON

    # Generate HMAC-SHA256 signature
    signature = hmac.new(
        endpoint.secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()

    # Send request with modern headers
    headers = {
        "Content-Type": "application/json",
        "X-Blik-Event": delivery.event_type,
        "X-Blik-Signature": f"sha256={signature}",
        "X-Blik-Delivery": str(delivery.delivery_id),  # Modern header name with UUID
        "User-Agent": "Blik-Webhooks/1.0",
    }

    try:
        response = requests.post(
            endpoint.url, data=payload_json, headers=headers, timeout=10
        )

        delivery.status_code = response.status_code
        delivery.response_body = response.text[:1000]  # Limit size
        delivery.attempt_count += 1

        if 200 <= response.status_code < 300:
            # Success
            delivery.delivered_at = timezone.now()
            endpoint.success_count += 1
            endpoint.last_triggered_at = timezone.now()
            logger.info(
                f"Webhook delivered successfully: {delivery.event_type} to {endpoint.url}"
            )
        else:
            # HTTP error
            endpoint.failure_count += 1
            delivery.error_message = f"HTTP {response.status_code}"
            logger.warning(
                f"Webhook delivery failed with HTTP {response.status_code}: "
                f"{delivery.event_type} to {endpoint.url}"
            )

        endpoint.save()
        delivery.save()

    except requests.RequestException as e:
        # Network/connection error
        delivery.attempt_count += 1
        delivery.error_message = str(e)
        delivery.save()

        endpoint.failure_count += 1
        endpoint.save()

        logger.error(
            f"Webhook delivery request failed: {delivery.event_type} to {endpoint.url} - {str(e)}"
        )

        raise


def retry_failed_delivery(delivery_id):
    """
    Retry a failed webhook delivery.

    Args:
        delivery_id: ID of WebhookDelivery to retry

    Raises:
        ValueError: If delivery already succeeded or max attempts reached
    """
    delivery = WebhookDelivery.objects.get(id=delivery_id)

    if delivery.delivered_at:
        raise ValueError("Delivery already succeeded")

    if delivery.attempt_count >= 3:
        raise ValueError("Max attempts (3) reached")

    deliver_webhook(delivery)


def verify_webhook_signature(secret, payload_json, signature_header):
    """
    Verify webhook signature (for use by webhook receivers).

    Args:
        secret: Webhook endpoint secret
        payload_json: JSON payload as string
        signature_header: Value of X-Blik-Signature header

    Returns:
        bool: True if signature is valid

    Example:
        # In your webhook receiver:
        payload = request.body.decode('utf-8')
        signature = request.headers.get('X-Blik-Signature')
        secret = 'your-webhook-secret'

        if verify_webhook_signature(secret, payload, signature):
            # Process webhook
            pass
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_signature = signature_header[7:]  # Remove "sha256=" prefix
    actual_signature = hmac.new(
        secret.encode(), payload_json.encode(), hashlib.sha256
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, actual_signature)
