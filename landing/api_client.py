"""
API client for calling main Blik app endpoints from landing app.

Centralizes authentication and error handling for all API calls.
All calls use service account authentication via API token.
"""
import requests
import logging
from django.conf import settings


logger = logging.getLogger(__name__)


class BlikAPIError(Exception):
    """Base exception for Blik API errors."""
    pass


class BlikAPIClient:
    """Client for interacting with main Blik app API."""

    def __init__(self):
        self.base_url = settings.MAIN_APP_URL
        self.api_token = getattr(settings, 'LANDING_SERVICE_API_TOKEN', None)

        if not self.api_token:
            logger.warning("LANDING_SERVICE_API_TOKEN not configured")

        self.headers = {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json'
        }

    def _make_request(self, method, endpoint, **kwargs):
        """
        Make HTTP request to main app API with error handling.

        Args:
            method: HTTP method ('get', 'post', 'patch', etc.)
            endpoint: API endpoint (e.g., '/api/v1/questionnaires/...')
            **kwargs: Additional arguments to pass to requests

        Returns:
            dict: JSON response from API

        Raises:
            BlikAPIError: If request fails
        """
        url = f"{self.base_url}{endpoint}"
        kwargs.setdefault('headers', self.headers)
        kwargs.setdefault('timeout', 10)

        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"API request timeout: {method} {url}")
            raise BlikAPIError("Request timed out. Please try again.")
        except requests.exceptions.ConnectionError:
            logger.error(f"API connection error: {method} {url}")
            raise BlikAPIError("Unable to connect to main app. Please try again later.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"API HTTP error: {e.response.status_code} {url} - {e.response.text}")
            try:
                error_data = e.response.json()
                error_msg = error_data.get('detail') or error_data.get('error') or str(e)
            except:
                error_msg = f"API error: {e.response.status_code}"
            raise BlikAPIError(error_msg)
        except ValueError as e:
            logger.error(f"API JSON decode error: {url} - {str(e)}")
            raise BlikAPIError("Invalid response from server.")

    def get_questionnaire(self, questionnaire_uuid):
        """
        Fetch questionnaire by UUID.

        Args:
            questionnaire_uuid: UUID of the questionnaire

        Returns:
            dict: Questionnaire data with sections and questions
        """
        endpoint = f"/api/v1/questionnaires/{questionnaire_uuid}/"
        return self._make_request('get', endpoint)

    def create_reviewee(self, name, email):
        """
        Create a new reviewee. Organization is auto-set from API token.

        Args:
            name: Reviewee name
            email: Reviewee email

        Returns:
            dict: Created reviewee data with UUID
        """
        endpoint = "/api/v1/reviewees/"
        data = {
            'name': name,
            'email': email,
        }
        return self._make_request('post', endpoint, json=data)

    def get_cycle(self, cycle_uuid):
        """
        Get cycle details including tokens.

        Args:
            cycle_uuid: UUID of review cycle

        Returns:
            dict: Cycle data with tokens
        """
        endpoint = f"/api/v1/cycles/{cycle_uuid}/"
        return self._make_request('get', endpoint)

    def create_cycle(self, reviewee_uuid, questionnaire_uuid, send_invitations=False):
        """
        Create a review cycle for self-assessment.

        Args:
            reviewee_uuid: UUID of reviewee
            questionnaire_uuid: UUID of questionnaire
            send_invitations: Whether to send email invitations (default: False)

        Returns:
            dict: Created cycle data with UUID and tokens
        """
        endpoint = "/api/v1/cycles/"
        data = {
            'reviewee': reviewee_uuid,
            'questionnaire': questionnaire_uuid,
            'reviewer_emails': {
                'self': ['placeholder@self-assessment.internal']  # Placeholder to trigger token creation
            },
            'send_invitations': send_invitations
        }
        return self._make_request('post', endpoint, json=data)

    def submit_responses(self, cycle_uuid, responses, token_uuid):
        """
        Submit questionnaire responses via API.

        Args:
            cycle_uuid: UUID of the review cycle
            responses: List of dicts with {question_id, value}
            token_uuid: Reviewer token UUID (required)

        Returns:
            dict: Confirmation of responses submitted
        """
        endpoint = f"/api/v1/cycles/{cycle_uuid}/submit_responses/"
        data = {
            'token': token_uuid,
            'responses': responses
        }
        return self._make_request('post', endpoint, json=data)

    def update_reviewee(self, reviewee_uuid, email=None, name=None):
        """
        Update reviewee details.

        Args:
            reviewee_uuid: UUID of reviewee
            email: New email address (optional)
            name: New name (optional)

        Returns:
            dict: Updated reviewee data
        """
        endpoint = f"/api/v1/reviewees/{reviewee_uuid}/"
        data = {}
        if email:
            data['email'] = email
        if name:
            data['name'] = name

        return self._make_request('patch', endpoint, json=data)

    def complete_cycle(self, cycle_uuid):
        """
        Mark cycle as complete and generate report.

        Args:
            cycle_uuid: UUID of review cycle

        Returns:
            dict: Report data including access_token for reviewee
        """
        endpoint = f"/api/v1/cycles/{cycle_uuid}/complete/"
        return self._make_request('post', endpoint)


# Singleton instance
api_client = BlikAPIClient()
