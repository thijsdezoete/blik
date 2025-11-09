"""
DRF ViewSets for Blik API.

These viewsets provide CRUD operations for all models with proper
organization scoping and permission checks.
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiExample

from accounts.models import Reviewee
from reviews.models import ReviewCycle, ReviewerToken
from questionnaires.models import Questionnaire
from reports.models import Report

from .serializers import (
    RevieweeSerializer,
    RevieweeListSerializer,
    ReviewCycleSerializer,
    ReviewCycleCreateSerializer,
    ReviewCycleListSerializer,
    QuestionnaireSerializer,
    QuestionnaireListSerializer,
    ReportSerializer,
    WebhookEndpointSerializer,
    WebhookDeliverySerializer,
    APITokenSerializer,
)
from .models import WebhookEndpoint, WebhookDelivery, APIToken
from .permissions import (
    IsOrganizationMember,
    CanManageOrganization,
    CanCreateCycles,
    CanViewAllReports,
)


# =============================================================================
# REVIEWEE VIEWSET
# =============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["reviewees"],
        description="List all reviewees in your organization. Returns UUIDs instead of integer IDs for security.",
    ),
    create=extend_schema(
        tags=["reviewees"],
        description="Create a new reviewee",
        examples=[
            OpenApiExample(
                name="create_reviewee_example",
                summary="Create a new reviewee",
                description="Create a reviewee with name, email, and optional department",
                value={
                    "name": "John Doe",
                    "email": "john.doe@example.com",
                    "department": "Engineering",
                    "is_active": True
                }
            )
        ]
    ),
    retrieve=extend_schema(
        tags=["reviewees"],
        description="Get reviewee details by UUID",
        parameters=[
            OpenApiParameter(
                name="uuid",
                type=str,
                location=OpenApiParameter.PATH,
                description="UUID of the reviewee (e.g., 7a44880e-2f99-4593-b3a7-58109af8a468)"
            )
        ]
    ),
    update=extend_schema(
        tags=["reviewees"],
        description="Update reviewee information by UUID",
    ),
    destroy=extend_schema(
        tags=["reviewees"],
        description="Soft-delete reviewee (mark as inactive) by UUID",
    ),
)
class RevieweeViewSet(viewsets.ModelViewSet):
    """
    API endpoints for managing reviewees (people being reviewed).

    Permissions:
    - All operations require organization membership
    - Create/Update/Delete require organization management permission
    """

    permission_classes = [IsOrganizationMember, CanManageOrganization]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["is_active", "department"]
    search_fields = ["name", "email", "department"]
    ordering_fields = ["name", "email", "created_at"]
    ordering = ["name"]
    lookup_field = "uuid"

    def get_serializer_class(self):
        """Use minimal serializer for list view."""
        if self.action == "list":
            return RevieweeListSerializer
        return RevieweeSerializer

    def get_queryset(self):
        """
        Always filter by organization.
        Annotate with review count for list view.
        """
        org = self.request.organization
        qs = Reviewee.objects.for_organization(org)

        if self.action == "list":
            qs = qs.annotate(review_count=Count("review_cycles"))

        return qs

    def perform_destroy(self, instance):
        """
        Soft delete by marking inactive.
        Hard delete requires separate permission and manual operation.
        """
        instance.is_active = False
        instance.save()

    @extend_schema(
        tags=["reviewees"],
        description="Get all review cycles for this reviewee",
    )
    @action(detail=True, methods=["get"])
    def cycles(self, request, uuid=None):
        """
        Get all review cycles for this reviewee.

        GET /api/v1/reviewees/{id}/cycles/
        """
        reviewee = self.get_object()
        cycles = (
            ReviewCycle.objects.filter(reviewee=reviewee)
            .select_related("questionnaire", "created_by")
            .prefetch_related("tokens")
        )

        serializer = ReviewCycleListSerializer(cycles, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["reviewees"],
        description="Create multiple reviewees at once",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "reviewees": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string", "format": "email"},
                                "department": {"type": "string"},
                            },
                        },
                    }
                },
            }
        },
    )
    @action(detail=False, methods=["post"])
    def bulk_create(self, request):
        """
        Create multiple reviewees at once.

        POST /api/v1/reviewees/bulk_create/
        Body: {"reviewees": [{"name": "...", "email": "...", "department": "..."}, ...]}
        """
        reviewees_data = request.data.get("reviewees", [])

        if not reviewees_data:
            return Response(
                {"error": "No reviewees provided"}, status=status.HTTP_400_BAD_REQUEST
            )

        created = []
        errors = []

        for data in reviewees_data:
            serializer = RevieweeSerializer(data=data, context={"request": request})
            if serializer.is_valid():
                serializer.save()
                created.append(serializer.data)
            else:
                errors.append({"data": data, "errors": serializer.errors})

        response_status = status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST

        return Response(
            {
                "created": created,
                "errors": errors,
                "summary": {
                    "total": len(reviewees_data),
                    "created": len(created),
                    "failed": len(errors),
                },
            },
            status=response_status,
        )


# =============================================================================
# REVIEW CYCLE VIEWSET
# =============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["cycles"],
        description="List all review cycles in your organization. Returns UUIDs instead of integer IDs for security.",
    ),
    create=extend_schema(
        tags=["cycles"],
        description="Create a new review cycle. Use UUIDs for reviewee and questionnaire references.",
        examples=[
            OpenApiExample(
                name="create_cycle_example",
                summary="Create cycle with reviewers",
                description="Create a review cycle with reviewer emails by category. Use UUIDs for reviewee and questionnaire.",
                value={
                    "reviewee": "7a44880e-2f99-4593-b3a7-58109af8a468",
                    "questionnaire": "f3d7c2a1-8b9e-4f5a-9c1d-2e3f4a5b6c7d",
                    "reviewer_emails": {
                        "self": ["reviewee@example.com"],
                        "peer": ["peer1@example.com", "peer2@example.com"],
                        "manager": ["manager@example.com"],
                        "direct_report": ["report1@example.com"]
                    },
                    "send_invitations": True
                }
            )
        ]
    ),
    retrieve=extend_schema(
        tags=["cycles"],
        description="Get cycle details with completion stats by UUID",
        parameters=[
            OpenApiParameter(
                name="uuid",
                type=str,
                location=OpenApiParameter.PATH,
                description="UUID of the cycle"
            )
        ]
    ),
    update=extend_schema(
        tags=["cycles"],
        description="Update review cycle by UUID",
    ),
    destroy=extend_schema(
        tags=["cycles"],
        description="Delete review cycle by UUID",
    ),
)
class ReviewCycleViewSet(viewsets.ModelViewSet):
    """
    API endpoints for managing review cycles.

    Permissions:
    - List/Retrieve: All organization members
    - Create: Requires can_create_cycles_for_others
    - Update/Delete: Organization admins only
    """

    permission_classes = [IsOrganizationMember]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status", "reviewee"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]
    lookup_field = "uuid"

    def get_serializer_class(self):
        """Select serializer based on action."""
        if self.action == "create":
            return ReviewCycleCreateSerializer
        elif self.action == "list":
            return ReviewCycleListSerializer
        return ReviewCycleSerializer

    def get_queryset(self):
        """
        Filter by organization via reviewee relationship.
        """
        org = self.request.organization
        return (
            ReviewCycle.objects.for_organization(org)
            .select_related("reviewee", "questionnaire", "created_by")
            .prefetch_related("tokens")
        )

    def get_permissions(self):
        """
        Dynamic permission based on action.
        """
        if self.action == "create":
            return [IsOrganizationMember(), CanCreateCycles()]
        elif self.action in ["update", "partial_update", "destroy"]:
            return [IsOrganizationMember(), CanManageOrganization()]
        return [IsOrganizationMember()]

    @extend_schema(
        tags=["cycles"],
        description="Send reminder emails to incomplete reviewers",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "token_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional list of token IDs to send reminders to",
                    }
                },
            }
        },
    )
    @action(detail=True, methods=["post"])
    def send_reminders(self, request, uuid=None):
        """
        Send reminder emails to incomplete reviewers.

        POST /api/v1/cycles/{id}/send_reminders/
        Body: {"token_ids": [1, 2, 3]}  # Optional, all pending if not provided
        """
        cycle = self.get_object()
        token_ids = request.data.get("token_ids", [])

        # Get pending tokens
        pending_tokens = cycle.tokens.filter(completed_at__isnull=True)
        if token_ids:
            pending_tokens = pending_tokens.filter(id__in=token_ids)

        # Send reminders
        from core.email import send_reviewer_reminder

        sent_count = 0
        for token in pending_tokens:
            if token.reviewer_email:
                send_reviewer_reminder(token)
                sent_count += 1

        return Response({"sent": sent_count, "total_pending": pending_tokens.count()})

    @extend_schema(
        tags=["cycles"],
        description="Manually mark cycle as complete and generate report",
    )
    @action(detail=True, methods=["post"])
    def complete(self, request, uuid=None):
        """
        Manually mark cycle as complete and generate report.

        POST /api/v1/cycles/{id}/complete/
        """
        cycle = self.get_object()

        if cycle.status == "completed":
            return Response({"error": "Cycle already completed"}, status=status.HTTP_400_BAD_REQUEST)

        # Generate report
        from reports.services import generate_report

        report = generate_report(cycle)

        # Update cycle status
        cycle.status = "completed"
        cycle.save()

        return Response(
            {
                "message": "Cycle completed",
                "report_id": report.id,
                "report_url": f"/my-report/{report.access_token}/",
            }
        )

    @extend_schema(
        tags=["cycles"],
        description="Submit responses for a review cycle using a reviewer token",
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'token': {
                        'type': 'string',
                        'format': 'uuid',
                        'description': 'Reviewer token UUID'
                    },
                    'responses': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'question_uuid': {
                                    'type': 'string',
                                    'format': 'uuid',
                                    'description': 'Question UUID'
                                },
                                'value': {
                                    'oneOf': [
                                        {'type': 'integer'},
                                        {'type': 'string'},
                                        {'type': 'array', 'items': {'type': 'string'}}
                                    ],
                                    'description': 'Answer value (int for ratings, string for text, array for multiple choice)'
                                }
                            },
                            'required': ['question_uuid', 'value']
                        }
                    }
                },
                'required': ['token', 'responses']
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'count': {'type': 'integer'}
                }
            },
            400: {'description': 'Token required or responses already submitted'},
            404: {'description': 'Invalid token'},
            410: {'description': 'Review cycle has been closed'}
        },
        examples=[
            OpenApiExample(
                'Rating responses',
                value={
                    "token": "7a11e37c-32f6-4027-a807-16c43dd21626",
                    "responses": [
                        {"question_uuid": "4da69a6f-2d8a-4461-a851-899b371e4956", "value": 4},
                        {"question_uuid": "bf9ff592-255c-443a-bc0b-ff377f543732", "value": 5}
                    ]
                },
                request_only=True
            )
        ]
    )
    @action(detail=True, methods=["post"])
    def submit_responses(self, request, uuid=None):
        """
        Submit responses for a review cycle using a token.
        """
        from reviews.models import ReviewerToken, Response as QuestionResponse
        from questionnaires.models import Question

        cycle = self.get_object()
        token_uuid = request.data.get('token')
        responses_data = request.data.get('responses', [])

        if not token_uuid:
            return Response({"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Get and validate token
        try:
            reviewer_token = ReviewerToken.objects.get(token=token_uuid, cycle=cycle)
        except ReviewerToken.DoesNotExist:
            return Response({"error": "Invalid token"}, status=status.HTTP_404_NOT_FOUND)

        if reviewer_token.is_completed:
            return Response({"error": "Responses already submitted"}, status=status.HTTP_400_BAD_REQUEST)

        if cycle.status == 'completed':
            return Response(
                {"error": "This review cycle has been closed"},
                status=status.HTTP_410_GONE
            )

        # Get all questions for validation
        questions = Question.objects.filter(section__questionnaire=cycle.questionnaire)
        question_dict = {str(q.uuid): q for q in questions}

        # Process responses
        created_responses = []
        for resp_data in responses_data:
            question_uuid = resp_data.get('question_uuid')
            value = resp_data.get('value')

            if not question_uuid or question_uuid not in question_dict:
                continue

            question = question_dict[question_uuid]

            # Create response with answer_data
            response = QuestionResponse.objects.create(
                cycle=cycle,
                question=question,
                token=reviewer_token,
                category=reviewer_token.category,
                answer_data={'value': value}
            )
            created_responses.append(response)

        # Mark token as completed
        reviewer_token.completed_at = timezone.now()
        reviewer_token.save()

        return Response({
            "message": "Responses submitted successfully",
            "count": len(created_responses)
        })

    @extend_schema(
        tags=["cycles"],
        description="Get detailed progress information including per-category stats",
    )
    @action(detail=True, methods=["get"])
    def progress(self, request, uuid=None):
        """
        Get detailed progress information.

        GET /api/v1/cycles/{id}/progress/
        """
        cycle = self.get_object()
        tokens = cycle.tokens.all()

        by_category = {}
        for category in ["self", "peer", "manager", "direct_report"]:
            cat_tokens = [t for t in tokens if t.category == category]
            by_category[category] = {
                "total": len(cat_tokens),
                "completed": sum(1 for t in cat_tokens if t.is_completed),
                "claimed": sum(1 for t in cat_tokens if t.claimed_at),
                "invited": sum(1 for t in cat_tokens if t.invitation_sent_at),
            }

        return Response(
            {
                "cycle_id": cycle.id,
                "status": cycle.status,
                "overall": {
                    "total": len(tokens),
                    "completed": sum(1 for t in tokens if t.is_completed),
                    "percentage": (
                        round(sum(1 for t in tokens if t.is_completed) / len(tokens) * 100, 1)
                        if tokens
                        else 0
                    ),
                },
                "by_category": by_category,
            }
        )


# =============================================================================
# QUESTIONNAIRE VIEWSET
# =============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["questionnaires"],
        description="List available questionnaires",
    ),
    retrieve=extend_schema(
        tags=["questionnaires"],
        description="Get questionnaire details with all questions",
    ),
)
class QuestionnaireViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for questionnaires.

    Read-only for now - questionnaire creation/editing via admin UI.
    Returns org-specific questionnaires + shared templates.
    """

    permission_classes = [IsOrganizationMember]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering = ["name"]
    lookup_field = "uuid"

    def get_serializer_class(self):
        """Use minimal serializer for list view."""
        if self.action == "list":
            return QuestionnaireListSerializer
        return QuestionnaireSerializer

    def get_queryset(self):
        """
        Return org questionnaires + shared templates.
        """
        org = self.request.organization
        return (
            Questionnaire.objects.filter(
                Q(organization=org) | Q(organization__isnull=True), is_active=True
            )
            .prefetch_related("sections__questions")
            .order_by("name")
        )


# =============================================================================
# REPORT VIEWSET
# =============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["reports"],
        description="List all reports (access tokens hidden)",
    ),
    retrieve=extend_schema(
        tags=["reports"],
        description="Get full report with data and access token",
    ),
)
class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoints for reports.

    Note: Access tokens are sensitive - only shown in detail view.
    """

    permission_classes = [IsOrganizationMember]
    serializer_class = ReportSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["available"]
    ordering = ["-generated_at"]
    lookup_field = "uuid"

    def get_queryset(self):
        """Filter by organization."""
        org = self.request.organization
        return Report.objects.for_organization(org).select_related(
            "cycle__reviewee", "cycle__questionnaire"
        )

    @extend_schema(
        tags=["reports"],
        description="Regenerate report with updated data",
    )
    @action(detail=True, methods=["post"], permission_classes=[IsOrganizationMember, CanManageOrganization])
    def regenerate(self, request, uuid=None):
        """
        Regenerate report with updated data.

        POST /api/v1/reports/{id}/regenerate/
        """
        report = self.get_object()

        # Regenerate
        from reports.services import generate_report

        new_report = generate_report(report.cycle, force=True)

        serializer = self.get_serializer(new_report)
        return Response(serializer.data)


# =============================================================================
# WEBHOOK VIEWSET
# =============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["webhooks"],
        description="List all webhook endpoints",
    ),
    create=extend_schema(
        tags=["webhooks"],
        description="Create a new webhook endpoint",
        examples=[
            OpenApiExample(
                name="create_webhook_example",
                summary="Create webhook endpoint",
                description="Create a webhook endpoint to receive event notifications",
                value={
                    "name": "Production Webhook",
                    "url": "https://api.example.com/webhooks/blik",
                    "events": ["cycle.created", "cycle.completed", "review.submitted"],
                    "is_active": True
                }
            )
        ]
    ),
    retrieve=extend_schema(
        tags=["webhooks"],
        description="Get webhook endpoint details",
    ),
    update=extend_schema(
        tags=["webhooks"],
        description="Update webhook endpoint",
    ),
    destroy=extend_schema(
        tags=["webhooks"],
        description="Delete webhook endpoint",
    ),
)
class WebhookEndpointViewSet(viewsets.ModelViewSet):
    """
    Manage webhook endpoints for event notifications.

    Permissions: Organization admins only
    """

    permission_classes = [IsOrganizationMember, CanManageOrganization]
    serializer_class = WebhookEndpointSerializer
    lookup_field = "uuid"

    def get_queryset(self):
        """Filter by organization."""
        return WebhookEndpoint.objects.for_organization(self.request.organization)

    @extend_schema(
        tags=["webhooks"],
        description="Send test webhook event",
    )
    @action(detail=True, methods=["post"])
    def test(self, request, uuid=None):
        """
        Send test webhook event.

        POST /api/v1/webhooks/{id}/test/
        """
        endpoint = self.get_object()

        from .webhooks import send_webhook

        send_webhook(
            organization=endpoint.organization,
            event_type="test.event",
            payload={"message": "Test webhook from Blik API", "timestamp": timezone.now().isoformat()},
        )

        return Response({"message": "Test webhook sent"})

    @extend_schema(
        tags=["webhooks"],
        description="Get delivery history for this endpoint",
    )
    @action(detail=True, methods=["get"])
    def deliveries(self, request, uuid=None):
        """
        Get delivery history for this endpoint.

        GET /api/v1/webhooks/{id}/deliveries/
        """
        endpoint = self.get_object()
        deliveries = WebhookDelivery.objects.filter(endpoint=endpoint).order_by("-created_at")[:50]

        serializer = WebhookDeliverySerializer(deliveries, many=True)
        return Response(serializer.data)


# =============================================================================
# API TOKEN VIEWSET
# =============================================================================


@extend_schema_view(
    list=extend_schema(
        tags=["tokens"],
        description="List all API tokens (token values are masked)",
    ),
    create=extend_schema(
        tags=["tokens"],
        description="Create a new API token (token value shown only once)",
        examples=[
            OpenApiExample(
                name="create_token_example",
                summary="Create API token",
                description="Create a new API token with specific permissions and optional expiration",
                value={
                    "name": "Production API Token",
                    "permissions": ["read", "write"],
                    "is_active": True,
                    "expires_at": "2025-12-31T23:59:59Z",
                    "rate_limit": 1000
                }
            )
        ]
    ),
    retrieve=extend_schema(
        tags=["tokens"],
        description="Get API token details (token value is masked)",
    ),
    update=extend_schema(
        tags=["tokens"],
        description="Update API token (cannot change token value)",
    ),
    destroy=extend_schema(
        tags=["tokens"],
        description="Delete API token (revoke access)",
    ),
)
class APITokenViewSet(viewsets.ModelViewSet):
    """
    Manage API tokens for authentication.

    Permissions: Organization admins only

    IMPORTANT: Token values are only shown once upon creation.
    After creation, tokens are masked for security.
    """

    permission_classes = [IsOrganizationMember, CanManageOrganization]
    serializer_class = APITokenSerializer
    lookup_field = "uuid"

    def get_queryset(self):
        """Filter by organization."""
        return APIToken.objects.for_organization(self.request.organization)
