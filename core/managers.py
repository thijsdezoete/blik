"""
Custom model managers for organization-scoped multitenancy.

These managers enforce organization-level data isolation by default.
"""
from django.db import models


class OrganizationQuerySet(models.QuerySet):
    """Custom QuerySet with active filtering"""

    def for_organization(self, organization, include_deleted=False):
        """
        Filter by organization, excluding GDPR-deleted records by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include soft-deleted records (default: False)

        Returns:
            QuerySet filtered by organization (or empty if org is None)
        """
        if organization is None:
            return self.none()

        queryset = self.filter(organization=organization)

        # Exclude GDPR soft-deleted records by default
        if not include_deleted:
            model = self.model
            if hasattr(model, '_meta'):
                model_name = model._meta.model_name
                if model_name == 'userprofile':
                    # UserProfile: filter by user__email
                    queryset = queryset.exclude(user__email__icontains='@deleted.invalid')
                else:
                    # Reviewee, OrganizationInvitation: filter by email directly
                    queryset = queryset.exclude(email__icontains='@deleted.invalid')

        return queryset


class OrganizationManager(models.Manager):
    """
    Manager that filters querysets by organization.

    Usage:
        Model.objects.for_organization(org)  # Returns org-scoped queryset (excludes GDPR-deleted)
        Model.objects.for_organization(org, include_deleted=True)  # Include soft-deleted records
        Model.objects.all()                   # Returns all (use with caution)
    """

    def get_queryset(self):
        """Return custom QuerySet"""
        return OrganizationQuerySet(self.model, using=self._db)

    def for_organization(self, organization, include_deleted=False):
        """
        Return queryset filtered by organization, excluding GDPR-deleted by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include soft-deleted records (default: False)

        Returns:
            QuerySet filtered by organization (or empty if org is None)
        """
        return self.get_queryset().for_organization(organization, include_deleted=include_deleted)


class QuestionnaireManager(models.Manager):
    """
    Manager for Questionnaire with special handling for default templates.

    Default questionnaires (organization=None, is_default=True) are shared
    templates that get cloned to new organizations. They should NOT be
    shown in normal org-scoped queries.
    """

    def for_organization(self, organization):
        """
        Return questionnaires for a specific organization.
        Excludes default templates (organization=None).

        Args:
            organization: Organization instance or None

        Returns:
            QuerySet filtered by organization (excludes templates)
        """
        if organization is None:
            return self.none()
        return self.filter(organization=organization)

    def templates(self):
        """
        Return default template questionnaires.
        These are shared across all orgs and cloned when new orgs are created.
        """
        return self.filter(organization__isnull=True, is_default=True, is_active=True)


class ReviewCycleQuerySet(models.QuerySet):
    """Custom QuerySet for ReviewCycle with organization and active filtering"""

    def for_organization(self, organization, include_deleted=False):
        """
        Filter cycles by organization through reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include cycles for soft-deleted reviewees (default: False)

        Returns:
            QuerySet filtered by organization
        """
        if organization is None:
            return self.none()

        queryset = self.filter(reviewee__organization=organization)

        # Exclude GDPR soft-deleted reviewees by default
        if not include_deleted:
            queryset = queryset.exclude(reviewee__email__icontains='@deleted.invalid').filter(reviewee__is_active=True)

        return queryset


class ReviewCycleManager(models.Manager):
    """Manager for ReviewCycle with organization filtering through reviewee."""

    def get_queryset(self):
        """Return custom QuerySet"""
        return ReviewCycleQuerySet(self.model, using=self._db)

    def for_organization(self, organization, include_deleted=False):
        """
        Filter cycles by organization through reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include cycles for soft-deleted reviewees (default: False)
        """
        return self.get_queryset().for_organization(organization, include_deleted=include_deleted)


class ReviewerTokenQuerySet(models.QuerySet):
    """Custom QuerySet for ReviewerToken"""

    def for_organization(self, organization, include_deleted=False):
        """
        Filter tokens by organization through cycle->reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include tokens for soft-deleted reviewees (default: False)

        Returns:
            QuerySet filtered by organization
        """
        if organization is None:
            return self.none()

        queryset = self.filter(cycle__reviewee__organization=organization)

        # Exclude GDPR soft-deleted reviewees by default
        if not include_deleted:
            queryset = queryset.exclude(cycle__reviewee__email__icontains='@deleted.invalid').filter(cycle__reviewee__is_active=True)

        return queryset


class ReviewerTokenManager(models.Manager):
    """Manager for ReviewerToken with organization filtering through cycle."""

    def get_queryset(self):
        """Return custom QuerySet"""
        return ReviewerTokenQuerySet(self.model, using=self._db)

    def for_organization(self, organization, include_deleted=False):
        """
        Filter tokens by organization through cycle->reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include tokens for soft-deleted reviewees (default: False)
        """
        return self.get_queryset().for_organization(organization, include_deleted=include_deleted)


class ResponseQuerySet(models.QuerySet):
    """Custom QuerySet for Response"""

    def for_organization(self, organization, include_deleted=False):
        """
        Filter responses by organization through cycle->reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include responses for soft-deleted reviewees (default: False)

        Returns:
            QuerySet filtered by organization
        """
        if organization is None:
            return self.none()

        queryset = self.filter(cycle__reviewee__organization=organization)

        # Exclude GDPR soft-deleted reviewees by default
        if not include_deleted:
            queryset = queryset.exclude(cycle__reviewee__email__icontains='@deleted.invalid').filter(cycle__reviewee__is_active=True)

        return queryset


class ResponseManager(models.Manager):
    """Manager for Response with organization filtering through cycle."""

    def get_queryset(self):
        """Return custom QuerySet"""
        return ResponseQuerySet(self.model, using=self._db)

    def for_organization(self, organization, include_deleted=False):
        """
        Filter responses by organization through cycle->reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include responses for soft-deleted reviewees (default: False)
        """
        return self.get_queryset().for_organization(organization, include_deleted=include_deleted)


class ReportQuerySet(models.QuerySet):
    """Custom QuerySet for Report"""

    def for_organization(self, organization, include_deleted=False):
        """
        Filter reports by organization through cycle->reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include reports for soft-deleted reviewees (default: False)

        Returns:
            QuerySet filtered by organization
        """
        if organization is None:
            return self.none()

        queryset = self.filter(cycle__reviewee__organization=organization)

        # Exclude GDPR soft-deleted reviewees by default
        if not include_deleted:
            queryset = queryset.exclude(cycle__reviewee__email__icontains='@deleted.invalid').filter(cycle__reviewee__is_active=True)

        return queryset


class ReportManager(models.Manager):
    """Manager for Report with organization filtering through cycle."""

    def get_queryset(self):
        """Return custom QuerySet"""
        return ReportQuerySet(self.model, using=self._db)

    def for_organization(self, organization, include_deleted=False):
        """
        Filter reports by organization through cycle->reviewee relationship.
        Excludes GDPR-deleted reviewees by default.

        Args:
            organization: Organization instance or None
            include_deleted: If True, include reports for soft-deleted reviewees (default: False)
        """
        return self.get_queryset().for_organization(organization, include_deleted=include_deleted)
