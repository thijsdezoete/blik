"""
Tests for webhook system.
"""
import json
import hmac
import hashlib
from unittest.mock import patch, Mock
from django.test import TestCase
from rest_framework.test import APIClient
from accounts.models import Organization, User, Reviewee
from api.models import APIToken, WebhookEndpoint, WebhookDelivery
from api.webhooks import send_webhook, deliver_webhook, verify_webhook_signature
from reviews.models import ReviewCycle
from questionnaires.models import Questionnaire


class WebhookDeliveryTest(TestCase):
    """Test webhook delivery functionality."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        self.endpoint = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['cycle.created', 'report.generated'],
            is_active=True
        )

    def test_webhook_endpoint_generates_secret(self):
        """Webhook endpoint should auto-generate secret."""
        self.assertIsNotNone(self.endpoint.secret)
        self.assertEqual(len(self.endpoint.secret), 64)

    @patch('api.webhooks.requests.post')
    def test_deliver_webhook_success(self, mock_post):
        """Successful webhook delivery should update stats."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type='test.event',
            payload={'message': 'test'}
        )

        deliver_webhook(delivery)

        # Refresh from database
        delivery.refresh_from_db()
        self.endpoint.refresh_from_db()

        self.assertEqual(delivery.status_code, 200)
        self.assertIsNotNone(delivery.delivered_at)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(self.endpoint.success_count, 1)
        self.assertEqual(self.endpoint.failure_count, 0)

    @patch('api.webhooks.requests.post')
    def test_deliver_webhook_failure(self, mock_post):
        """Failed webhook delivery should record error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = 'Internal Server Error'
        mock_post.return_value = mock_response

        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type='test.event',
            payload={'message': 'test'}
        )

        deliver_webhook(delivery)

        # Refresh from database
        delivery.refresh_from_db()
        self.endpoint.refresh_from_db()

        self.assertEqual(delivery.status_code, 500)
        self.assertIsNone(delivery.delivered_at)  # Not successful
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(self.endpoint.success_count, 0)
        self.assertEqual(self.endpoint.failure_count, 1)

    @patch('api.webhooks.requests.post')
    def test_webhook_signature_generated(self, mock_post):
        """Webhook should include HMAC signature."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type='test.event',
            payload={'message': 'test'}
        )

        deliver_webhook(delivery)

        # Check that requests.post was called with signature header
        self.assertTrue(mock_post.called)
        call_kwargs = mock_post.call_args[1]
        headers = call_kwargs['headers']

        self.assertIn('X-Blik-Signature', headers)
        self.assertTrue(headers['X-Blik-Signature'].startswith('sha256='))

    @patch('api.webhooks.requests.post')
    def test_webhook_headers(self, mock_post):
        """Webhook should include required headers."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type='test.event',
            payload={'message': 'test'}
        )

        deliver_webhook(delivery)

        call_kwargs = mock_post.call_args[1]
        headers = call_kwargs['headers']

        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(headers['X-Blik-Event'], 'test.event')
        self.assertIn('X-Blik-Signature', headers)
        self.assertEqual(headers['X-Blik-Delivery'], str(delivery.delivery_id))

    @patch('api.webhooks.requests.post')
    def test_modern_webhook_payload_structure(self, mock_post):
        """Webhook payload should have modern structure with event metadata."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = 'OK'
        mock_post.return_value = mock_response

        delivery = WebhookDelivery.objects.create(
            endpoint=self.endpoint,
            event_type='cycle.created',
            payload={'cycle_id': 123, 'reviewee': {'name': 'Test'}}
        )

        deliver_webhook(delivery)

        # Get the actual payload sent
        call_kwargs = mock_post.call_args[1]
        sent_payload = json.loads(call_kwargs['data'])

        # Verify modern structure
        self.assertIn('id', sent_payload)
        self.assertEqual(sent_payload['id'], str(delivery.delivery_id))
        self.assertIn('event', sent_payload)
        self.assertEqual(sent_payload['event'], 'cycle.created')
        self.assertIn('created', sent_payload)
        self.assertIn('data', sent_payload)

        # Original payload should be nested in 'data'
        self.assertEqual(sent_payload['data']['cycle_id'], 123)
        self.assertEqual(sent_payload['data']['reviewee']['name'], 'Test')

    def test_send_webhook_creates_deliveries(self):
        """send_webhook should create delivery records for subscribed endpoints."""
        # Create another endpoint with different events
        other_endpoint = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Other Webhook',
            url='https://other.example.com/webhook',
            events=['feedback.submitted'],  # Different event
            is_active=True
        )

        with patch('api.webhooks.deliver_webhook') as mock_deliver:
            send_webhook(
                organization=self.org,
                event_type='cycle.created',
                payload={'cycle_id': 123}
            )

            # Should only deliver to endpoint subscribed to 'cycle.created'
            self.assertEqual(WebhookDelivery.objects.count(), 1)

            delivery = WebhookDelivery.objects.first()
            self.assertEqual(delivery.endpoint, self.endpoint)  # Not other_endpoint
            self.assertEqual(delivery.event_type, 'cycle.created')

    def test_inactive_endpoint_not_triggered(self):
        """Inactive endpoints should not receive webhooks."""
        self.endpoint.is_active = False
        self.endpoint.save()

        with patch('api.webhooks.deliver_webhook') as mock_deliver:
            send_webhook(
                organization=self.org,
                event_type='cycle.created',
                payload={'cycle_id': 123}
            )

            # Should not create any deliveries
            self.assertEqual(WebhookDelivery.objects.count(), 0)

    def test_verify_webhook_signature_valid(self):
        """Valid signature should pass verification."""
        secret = 'test-secret'
        payload = '{"message": "test"}'

        signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        is_valid = verify_webhook_signature(
            secret,
            payload,
            f'sha256={signature}'
        )

        self.assertTrue(is_valid)

    def test_verify_webhook_signature_invalid(self):
        """Invalid signature should fail verification."""
        secret = 'test-secret'
        payload = '{"message": "test"}'

        is_valid = verify_webhook_signature(
            secret,
            payload,
            'sha256=invalid-signature'
        )

        self.assertFalse(is_valid)


class WebhookEndpointViewSetTest(TestCase):
    """Test webhook endpoint API endpoints."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        self.user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        # Grant manage permission
        from django.contrib.auth.models import Permission
        perm = Permission.objects.get(codename='can_manage_organization')
        self.user.user_permissions.add(perm)

        self.token = APIToken.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Token'
        )

        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.token}')

    def test_create_webhook_endpoint(self):
        """POST /webhooks/ creates new webhook endpoint."""
        response = self.client.post('/api/v1/webhooks/', {
            'name': 'My Webhook',
            'url': 'https://example.com/webhook',
            'events': ['cycle.created', 'report.generated']
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'My Webhook')

        # Verify secret was generated
        self.assertIn('secret', response.data)
        self.assertEqual(len(response.data['secret']), 64)

    def test_list_webhooks(self):
        """GET /webhooks/ returns list of webhooks."""
        WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Webhook 1',
            url='https://example.com/webhook1',
            events=['cycle.created']
        )
        WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Webhook 2',
            url='https://example.com/webhook2',
            events=['report.generated']
        )

        response = self.client.get('/api/v1/webhooks/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)

    def test_retrieve_webhook(self):
        """GET /webhooks/{id}/ returns webhook details."""
        webhook = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['cycle.created']
        )

        response = self.client.get(f'/api/v1/webhooks/{webhook.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Test Webhook')
        self.assertEqual(response.data['events'], ['cycle.created'])

    def test_update_webhook(self):
        """PUT /webhooks/{id}/ updates webhook."""
        webhook = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Original Name',
            url='https://example.com/webhook',
            events=['cycle.created']
        )

        response = self.client.put(f'/api/v1/webhooks/{webhook.id}/', {
            'name': 'Updated Name',
            'url': 'https://example.com/webhook',
            'events': ['cycle.created', 'report.generated']
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Updated Name')
        self.assertEqual(len(response.data['events']), 2)

    def test_delete_webhook(self):
        """DELETE /webhooks/{id}/ deletes webhook."""
        webhook = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['cycle.created']
        )

        response = self.client.delete(f'/api/v1/webhooks/{webhook.id}/')

        self.assertEqual(response.status_code, 204)

        # Verify deleted
        self.assertFalse(
            WebhookEndpoint.objects.filter(id=webhook.id).exists()
        )

    @patch('api.webhooks.send_webhook')
    def test_test_webhook_action(self, mock_send):
        """POST /webhooks/{id}/test/ sends test webhook."""
        webhook = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['test.event']
        )

        response = self.client.post(f'/api/v1/webhooks/{webhook.id}/test/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_send.called)

        # Check test event was sent
        call_args = mock_send.call_args
        self.assertEqual(call_args[1]['event_type'], 'test.event')

    def test_deliveries_action(self):
        """GET /webhooks/{id}/deliveries/ returns delivery history."""
        webhook = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['cycle.created']
        )

        # Create some deliveries
        WebhookDelivery.objects.create(
            endpoint=webhook,
            event_type='cycle.created',
            payload={'cycle_id': 1},
            status_code=200
        )
        WebhookDelivery.objects.create(
            endpoint=webhook,
            event_type='cycle.created',
            payload={'cycle_id': 2},
            status_code=500
        )

        response = self.client.get(f'/api/v1/webhooks/{webhook.id}/deliveries/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_organization_isolation(self):
        """Cannot access other organization's webhooks."""
        other_org = Organization.objects.create(name='Other Org')

        other_webhook = WebhookEndpoint.objects.create(
            organization=other_org,
            created_by=self.user,
            name='Other Webhook',
            url='https://example.com/webhook',
            events=['cycle.created']
        )

        response = self.client.get(f'/api/v1/webhooks/{other_webhook.id}/')

        self.assertEqual(response.status_code, 404)


class WebhookSignalsTest(TestCase):
    """Test webhook signal handlers."""

    def setUp(self):
        """Set up test data."""
        self.org = Organization.objects.create(name='Test Org')

        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='test123'
        )
        self.user.profile.organization = self.org
        self.user.profile.save()

        self.endpoint = WebhookEndpoint.objects.create(
            organization=self.org,
            created_by=self.user,
            name='Test Webhook',
            url='https://example.com/webhook',
            events=['cycle.created', 'cycle.completed'],
            is_active=True
        )

        self.reviewee = Reviewee.objects.create(
            organization=self.org,
            name='Test Reviewee',
            email='reviewee@example.com'
        )

        self.questionnaire = Questionnaire.objects.create(
            organization=self.org,
            name='Test Questionnaire',
            is_active=True
        )

    @patch('api.webhooks.deliver_webhook')
    def test_cycle_created_triggers_webhook(self, mock_deliver):
        """Creating a cycle should trigger cycle.created webhook."""
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user
        )

        # Check webhook delivery was created
        deliveries = WebhookDelivery.objects.filter(event_type='cycle.created')
        self.assertEqual(deliveries.count(), 1)

        delivery = deliveries.first()
        self.assertEqual(delivery.endpoint, self.endpoint)
        self.assertIn('cycle_id', delivery.payload)
        self.assertEqual(delivery.payload['cycle_id'], cycle.id)

    @patch('api.webhooks.deliver_webhook')
    def test_cycle_completed_triggers_webhook(self, mock_deliver):
        """Completing a cycle should trigger cycle.completed webhook."""
        cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.user,
            status='active'
        )

        # Clear deliveries from creation
        WebhookDelivery.objects.all().delete()

        # Mark as completed
        cycle.status = 'completed'
        cycle.save()

        # Check webhook delivery was created
        deliveries = WebhookDelivery.objects.filter(event_type='cycle.completed')
        self.assertEqual(deliveries.count(), 1)
