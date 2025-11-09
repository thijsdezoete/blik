"""
DRF Serializers for Blik API.

These serializers handle conversion between model instances and JSON,
with organization scoping and anonymity preservation.
"""
from rest_framework import serializers
from django.db.models import Count, Q
from accounts.models import Reviewee
from reviews.models import ReviewCycle, ReviewerToken, Response
from questionnaires.models import Questionnaire, QuestionSection, Question
from reports.models import Report
from .models import APIToken, WebhookEndpoint, WebhookDelivery


# =============================================================================
# REVIEWEE SERIALIZERS
# =============================================================================


class RevieweeSerializer(serializers.ModelSerializer):
    """
    Full serializer for Reviewee model.
    Organization is auto-set from request context.
    """

    class Meta:
        model = Reviewee
        fields = [
            "uuid",
            "name",
            "email",
            "department",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uuid", "created_at", "updated_at"]

    def validate_email(self, value):
        """
        Ensure email is unique within organization.
        """
        org = self.context["request"].organization

        # Check for existing reviewee (excluding current instance if updating)
        qs = Reviewee.objects.for_organization(org).filter(email=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError(
                "A reviewee with this email already exists in your organization."
            )

        return value

    def create(self, validated_data):
        """
        Auto-set organization from request context.
        """
        validated_data["organization"] = self.context["request"].organization
        return super().create(validated_data)


class RevieweeListSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for list views (performance optimization).
    """

    review_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Reviewee
        fields = ["uuid", "name", "email", "department", "is_active", "review_count"]


# =============================================================================
# QUESTIONNAIRE SERIALIZERS
# =============================================================================


class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for individual questions."""

    class Meta:
        model = Question
        fields = [
            "uuid",
            "question_text",
            "question_type",
            "config",
            "required",
            "order",
            "section",
        ]
        read_only_fields = ["uuid"]


class QuestionSectionSerializer(serializers.ModelSerializer):
    """Serializer for question sections with nested questions."""

    questions = QuestionSerializer(many=True, read_only=True)

    class Meta:
        model = QuestionSection
        fields = ["title", "description", "order", "questions"]
        read_only_fields = []


class QuestionnaireSerializer(serializers.ModelSerializer):
    """
    Full questionnaire serializer with sections and questions.
    """

    sections = QuestionSectionSerializer(many=True, read_only=True)
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = Questionnaire
        fields = [
            "uuid",
            "name",
            "description",
            "is_default",
            "is_active",
            "created_at",
            "updated_at",
            "sections",
            "question_count",
        ]
        read_only_fields = ["uuid", "created_at", "updated_at"]

    def get_question_count(self, obj):
        """Count total questions across all sections."""
        return sum(section.questions.count() for section in obj.sections.all())


class QuestionnaireListSerializer(serializers.ModelSerializer):
    """Minimal serializer for questionnaire lists."""

    class Meta:
        model = Questionnaire
        fields = ["uuid", "name", "description", "is_default", "is_active"]


# =============================================================================
# REVIEWER TOKEN SERIALIZERS
# =============================================================================


class ReviewerTokenSerializer(serializers.ModelSerializer):
    """
    CRITICAL: Never expose reviewer_email to maintain anonymity.
    Only show completion status and category.
    Note: We intentionally don't expose token UUID here for security.
    """

    is_completed = serializers.BooleanField(read_only=True)

    class Meta:
        model = ReviewerToken
        fields = [
            "category",
            "is_completed",
            "claimed_at",
            "completed_at",
            "invitation_sent_at",
        ]
        read_only_fields = fields  # All fields are read-only


class ReviewerTokenWithUUIDSerializer(serializers.ModelSerializer):
    """
    Token serializer that includes UUID - ONLY for cycle creation response.
    Used by API clients that need to submit responses programmatically.
    """

    is_completed = serializers.BooleanField(read_only=True)
    uuid = serializers.UUIDField(source='token', read_only=True)

    class Meta:
        model = ReviewerToken
        fields = [
            "uuid",
            "category",
            "is_completed",
            "claimed_at",
            "completed_at",
        ]
        read_only_fields = fields


# =============================================================================
# REVIEW CYCLE SERIALIZERS
# =============================================================================


class ReviewCycleSerializer(serializers.ModelSerializer):
    """
    Full review cycle serializer with related data.
    """

    reviewee = serializers.UUIDField(source="reviewee.uuid", read_only=True)
    reviewee_detail = RevieweeSerializer(source="reviewee", read_only=True)
    questionnaire = serializers.UUIDField(source="questionnaire.uuid", read_only=True)
    questionnaire_detail = QuestionnaireListSerializer(source="questionnaire", read_only=True)
    tokens = ReviewerTokenSerializer(many=True, read_only=True)
    completion_stats = serializers.SerializerMethodField()

    class Meta:
        model = ReviewCycle
        fields = [
            "uuid",
            "reviewee",
            "reviewee_detail",
            "questionnaire",
            "questionnaire_detail",
            "status",
            "created_by",
            "created_at",
            "updated_at",
            "tokens",
            "completion_stats",
        ]
        read_only_fields = ["uuid", "created_at", "updated_at", "created_by"]

    def get_completion_stats(self, obj):
        """Calculate completion statistics."""
        tokens = obj.tokens.all()
        completed = sum(1 for t in tokens if t.is_completed)
        return {
            "total": len(tokens),
            "completed": completed,
            "pending": len(tokens) - completed,
            "percentage": round((completed / len(tokens) * 100), 1) if tokens else 0,
        }

    def validate(self, data):
        """
        Ensure reviewee and questionnaire belong to organization.
        """
        org = self.context["request"].organization

        if "reviewee" in data and data["reviewee"].organization != org:
            raise serializers.ValidationError(
                {"reviewee": "Reviewee does not belong to your organization."}
            )

        if "questionnaire" in data:
            quest = data["questionnaire"]
            # Questionnaire must be org-owned or a shared template (org=None)
            if quest.organization not in [org, None]:
                raise serializers.ValidationError(
                    {"questionnaire": "Questionnaire not available to your organization."}
                )

        return data

    def create(self, validated_data):
        """Auto-set created_by from request user."""
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class ReviewCycleCreateSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for creating cycles with reviewer emails.
    """

    reviewee = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Reviewee.objects.none(),  # Will be set in __init__
        help_text="UUID of the reviewee"
    )
    questionnaire = serializers.SlugRelatedField(
        slug_field="uuid",
        queryset=Questionnaire.objects.none(),  # Will be set in __init__
        help_text="UUID of the questionnaire"
    )
    reviewer_emails = serializers.DictField(
        child=serializers.ListField(child=serializers.EmailField()),
        required=False,
        write_only=True,
        help_text='Reviewer emails by category: {"self": ["email@example.com"], "peer": [...], ...}',
    )
    send_invitations = serializers.BooleanField(
        default=True,
        write_only=True,
        help_text="Automatically send invitation emails to reviewers",
    )

    tokens = ReviewerTokenWithUUIDSerializer(many=True, read_only=True)

    class Meta:
        model = ReviewCycle
        fields = ["uuid", "reviewee", "questionnaire", "reviewer_emails", "send_invitations", "tokens"]
        read_only_fields = ["uuid", "tokens"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "request" in self.context:
            org = self.context["request"].organization
            self.fields["reviewee"].queryset = Reviewee.objects.filter(organization=org, is_active=True)
            # Questionnaires can be org-specific or shared templates (org=None)
            from django.db.models import Q
            self.fields["questionnaire"].queryset = Questionnaire.objects.filter(
                Q(organization=org) | Q(organization__isnull=True)
            )

    def validate_reviewer_emails(self, value):
        """Validate reviewer email structure."""
        valid_categories = ["self", "peer", "manager", "direct_report"]
        for category in value.keys():
            if category not in valid_categories:
                raise serializers.ValidationError(
                    f"Invalid category '{category}'. Must be one of: {', '.join(valid_categories)}"
                )
        return value

    def validate(self, data):
        """
        Ensure reviewee and questionnaire belong to organization.
        """
        org = self.context["request"].organization

        if "reviewee" in data and data["reviewee"].organization != org:
            raise serializers.ValidationError(
                {"reviewee": "Reviewee does not belong to your organization."}
            )

        if "questionnaire" in data:
            quest = data["questionnaire"]
            # Questionnaire must be org-owned or a shared template (org=None)
            if quest.organization not in [org, None]:
                raise serializers.ValidationError(
                    {"questionnaire": "Questionnaire not available to your organization."}
                )

        return data

    def create(self, validated_data):
        """
        Create cycle and optionally create reviewer tokens and send invitations.
        """
        reviewer_emails = validated_data.pop("reviewer_emails", {})
        send_invitations = validated_data.pop("send_invitations", True)

        validated_data["created_by"] = self.context["request"].user
        cycle = super().create(validated_data)

        # Create reviewer tokens if emails provided
        if reviewer_emails:
            created_tokens = []

            # Create tokens for each category and email
            for category, emails in reviewer_emails.items():
                for email in emails:
                    token = ReviewerToken.objects.create(
                        cycle=cycle,
                        category=category,
                        reviewer_email=email.strip().lower()
                    )
                    created_tokens.append(token)

            # Send invitations if requested
            if send_invitations and created_tokens:
                from reviews.services import send_reviewer_invitations
                send_reviewer_invitations(cycle)

        return cycle


class ReviewCycleListSerializer(serializers.ModelSerializer):
    """Minimal serializer for cycle lists."""

    reviewee = serializers.UUIDField(source="reviewee.uuid", read_only=True)
    reviewee_name = serializers.CharField(source="reviewee.name", read_only=True)
    questionnaire = serializers.UUIDField(source="questionnaire.uuid", read_only=True)
    questionnaire_name = serializers.CharField(source="questionnaire.name", read_only=True)
    completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = ReviewCycle
        fields = [
            "uuid",
            "reviewee",
            "reviewee_name",
            "questionnaire",
            "questionnaire_name",
            "status",
            "created_at",
            "completion_percentage",
        ]

    def get_completion_percentage(self, obj):
        """Calculate completion percentage."""
        tokens = obj.tokens.all()
        if not tokens:
            return 0
        completed = sum(1 for t in tokens if t.is_completed)
        return round(completed / len(tokens) * 100, 1)


# =============================================================================
# REPORT SERIALIZERS
# =============================================================================


class ReportSerializer(serializers.ModelSerializer):
    """
    Report serializer with anonymity safeguards.
    Never expose access_token in list views.
    """

    cycle_uuid = serializers.UUIDField(source="cycle.uuid", read_only=True)
    reviewee_name = serializers.CharField(source="cycle.reviewee.name", read_only=True)

    class Meta:
        model = Report
        fields = [
            "uuid",
            "cycle_uuid",
            "reviewee_name",
            "generated_at",
            "available",
            "access_token",
            "access_token_expires",
            "last_accessed",
            "access_count",
            "report_data",
        ]
        read_only_fields = fields  # All fields are read-only

    def to_representation(self, instance):
        """
        Conditionally hide sensitive data in list views.
        """
        data = super().to_representation(instance)

        # In list views, don't expose access token or full report data
        if self.context.get("view") and hasattr(self.context["view"], "action"):
            if self.context["view"].action == "list":
                data.pop("access_token", None)
                data.pop("report_data", None)  # Too large for lists

        return data


# =============================================================================
# WEBHOOK SERIALIZERS
# =============================================================================


class WebhookEndpointSerializer(serializers.ModelSerializer):
    """Serializer for webhook endpoints."""

    class Meta:
        model = WebhookEndpoint
        fields = [
            "uuid",
            "name",
            "url",
            "events",
            "is_active",
            "secret",
            "last_triggered_at",
            "success_count",
            "failure_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "uuid",
            "secret",
            "last_triggered_at",
            "success_count",
            "failure_count",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        """Auto-set organization and created_by."""
        validated_data["organization"] = self.context["request"].organization
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class WebhookDeliverySerializer(serializers.ModelSerializer):
    """Serializer for webhook delivery logs."""

    is_successful = serializers.BooleanField(read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = [
            "id",
            "event_type",
            "created_at",
            "delivered_at",
            "status_code",
            "error_message",
            "attempt_count",
            "is_successful",
        ]
        read_only_fields = fields  # All fields are read-only


# =============================================================================
# API TOKEN SERIALIZERS
# =============================================================================


class APITokenSerializer(serializers.ModelSerializer):
    """
    Serializer for API tokens.
    Only show token value on creation.
    """

    class Meta:
        model = APIToken
        fields = [
            "uuid",
            "name",
            "token",
            "permissions",
            "is_active",
            "expires_at",
            "last_used_at",
            "rate_limit",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["uuid", "token", "last_used_at", "created_at", "updated_at"]

    def to_representation(self, instance):
        """
        Hide token value except on creation.
        """
        data = super().to_representation(instance)

        # Only show token on create (when instance is new)
        if instance.pk and not self.context.get("show_token", False):
            # Mask the token after creation
            data["token"] = f"{instance.token[:8]}...{instance.token[-8:]}"

        return data

    def create(self, validated_data):
        """Auto-set organization and created_by."""
        validated_data["organization"] = self.context["request"].organization
        validated_data["created_by"] = self.context["request"].user

        # Set flag to show full token on creation
        self.context["show_token"] = True

        return super().create(validated_data)
