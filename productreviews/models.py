"""
Product reviews for gathering customer testimonials and ratings.
Used for JSON-LD structured data on landing pages.
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from core.models import TimeStampedModel, Organization
from core.managers import OrganizationManager


class ProductReview(TimeStampedModel):
    """
    Customer reviews of the Blik platform for displaying on landing pages.
    These reviews feed into JSON-LD structured data for SEO.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='product_reviews',
        help_text='Organization this review belongs to'
    )

    # Review content
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text='Rating from 1-5 stars'
    )
    review_title = models.CharField(
        max_length=200,
        help_text='Short title/headline for the review'
    )
    review_text = models.TextField(
        help_text='Full review text from the customer'
    )

    # Reviewer information
    reviewer_name = models.CharField(
        max_length=100,
        help_text='Name of the person giving the review'
    )
    reviewer_title = models.CharField(
        max_length=150,
        blank=True,
        help_text='Job title of the reviewer (e.g., "HR Manager")'
    )
    reviewer_company = models.CharField(
        max_length=100,
        blank=True,
        help_text='Company/organization the reviewer works for'
    )
    reviewer_email = models.EmailField(
        help_text='Email address of the reviewer (not shown publicly)'
    )

    # Verification and status
    verified_customer = models.BooleanField(
        default=False,
        help_text='Verified as actual customer/subscriber'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text='Review approval status'
    )

    # Publishing
    is_active = models.BooleanField(
        default=True,
        help_text='Active reviews can be displayed publicly'
    )
    featured = models.BooleanField(
        default=False,
        help_text='Featured reviews are highlighted on landing pages'
    )
    published_date = models.DateField(
        null=True,
        blank=True,
        help_text='Date the review was published (shown in JSON-LD)'
    )

    # Metadata
    source = models.CharField(
        max_length=100,
        blank=True,
        help_text='Where the review came from (e.g., "Email Survey", "G2", "Direct")'
    )
    notes = models.TextField(
        blank=True,
        help_text='Internal notes about this review (not shown publicly)'
    )

    objects = OrganizationManager()

    class Meta:
        db_table = 'product_reviews'
        ordering = ['-published_date', '-created_at']
        verbose_name = 'Product Review'
        verbose_name_plural = 'Product Reviews'

    def __str__(self):
        return f"{self.reviewer_name} - {self.rating}★ ({self.get_status_display()})"

    @property
    def star_display(self):
        """Return star rating as visual string"""
        return '★' * self.rating + '☆' * (5 - self.rating)

    @property
    def is_published(self):
        """Check if review is approved and active"""
        return self.status == 'approved' and self.is_active
