"""
Custom model managers for organization-scoped multitenancy.

These managers enforce organization-level data isolation by default.
"""
from django.db import models


class OrganizationManager(models.Manager):
    """
    Manager that filters querysets by organization.

    Usage:
        Model.objects.for_organization(org)  # Returns org-scoped queryset
        Model.objects.all()                   # Returns all (use with caution)
    """

    def for_organization(self, organization):
        """
        Return queryset filtered by organization.

        Args:
            organization: Organization instance or None

        Returns:
            QuerySet filtered by organization (or empty if org is None)
        """
        if organization is None:
            return self.none()
        return self.filter(organization=organization)


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


class ReviewCycleManager(models.Manager):
    """Manager for ReviewCycle with organization filtering through reviewee."""

    def for_organization(self, organization):
        """Filter cycles by organization through reviewee relationship."""
        if organization is None:
            return self.none()
        return self.filter(reviewee__organization=organization)


class ReviewerTokenManager(models.Manager):
    """Manager for ReviewerToken with organization filtering through cycle."""

    def for_organization(self, organization):
        """Filter tokens by organization through cycle->reviewee relationship."""
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)


class ResponseManager(models.Manager):
    """Manager for Response with organization filtering through cycle."""

    def for_organization(self, organization):
        """Filter responses by organization through cycle->reviewee relationship."""
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)


class ReportManager(models.Manager):
    """Manager for Report with organization filtering through cycle."""

    def for_organization(self, organization):
        """Filter reports by organization through cycle->reviewee relationship."""
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)
