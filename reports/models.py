import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext, gettext_lazy as _
from core.models import TimeStampedModel
from core.managers import ReportManager
from reviews.models import ReviewCycle
from reports.storage import get_private_storage, private_storage


class Report(TimeStampedModel):
    """Generated report for a review cycle"""

    # Public UUID for external references (API, URLs)
    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text=_('Public identifier for API and URL usage (non-enumerable)'),
        verbose_name=_('UUID')
    )

    cycle = models.OneToOneField(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name='report',
        verbose_name=_('review cycle')
    )

    # Secure access token for reviewee to access their report
    access_token = models.UUIDField(
        unique=True,
        editable=False,
        db_index=True,
        null=True,
        blank=True,
        help_text=_('Secure token for reviewee access to their report'),
        verbose_name=_('access token')
    )

    # JSON field for storing aggregated results
    # Structure:
    # {
    #   "by_section": {
    #     "section_id": {
    #       "title": "Leadership",
    #       "questions": {
    #         "question_id": {
    #           "question_text": "...",
    #           "by_category": {
    #             "peer": {"avg": 4.2, "count": 3, "responses": [...]},
    #             "manager": {"avg": 4.5, "count": 1, "responses": [...]}
    #           }
    #         }
    #       }
    #     }
    #   }
    # }
    report_data = models.JSONField(_('report data'))

    generated_at = models.DateTimeField(_('generated at'), auto_now_add=True)
    available = models.BooleanField(_('available'), default=True)

    # Security tracking for report access
    access_token_expires = models.DateTimeField(_('access token expires'), null=True, blank=True, help_text=_('Expiration date for access token'))
    last_accessed = models.DateTimeField(_('last accessed'), null=True, blank=True, help_text=_('Last time report was accessed'))
    access_count = models.IntegerField(_('access count'), default=0, help_text=_('Number of times report has been accessed'))

    # Rendered PDF of the report, kept only for the retention period
    pdf_file = models.FileField(storage=get_private_storage, upload_to='report_pdfs/', blank=True)
    pdf_generated_at = models.DateTimeField(null=True, blank=True)
    pdf_attempts = models.PositiveSmallIntegerField(default=0)

    objects = ReportManager()

    class Meta:
        verbose_name = _('report')
        verbose_name_plural = _('reports')
        db_table = 'reports'
        ordering = ['-generated_at']

    def __str__(self):
        return gettext('Report for %(cycle)s') % {'cycle': self.cycle}

    @property
    def pdf_retention_days(self):
        return self.cycle.organization.report_pdf_retention_days or settings.REPORT_PDF_RETENTION_DAYS

    @property
    def pdf_expires_at(self):
        if not self.pdf_generated_at:
            return None
        return self.pdf_generated_at + timedelta(days=self.pdf_retention_days)

    def has_valid_pdf(self, now=None):
        if not self.pdf_file or not self.pdf_expires_at:
            return False
        if self.pdf_expires_at <= (now or timezone.now()):
            return False
        return private_storage.exists(self.pdf_file.name)

    @cached_property
    def access_token_expired(self):
        return self.access_token_expires is not None and self.access_token_expires < timezone.now()
