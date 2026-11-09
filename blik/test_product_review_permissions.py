"""Product reviews come from every customer: only platform superusers may read them."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from accounts.permissions import assign_organization_admin, ensure_permission_groups
from core.models import Organization
from productreviews.models import ProductReview


class ProductReviewAccessTests(TestCase):
    def setUp(self):
        ensure_permission_groups()
        org = Organization.objects.create(name='Acme', email='org@acme.example')
        self.admin = User.objects.create_user(username='admin', email='admin@acme.example', password='pw')
        UserProfile.objects.create(user=self.admin, organization=org)
        assign_organization_admin(self.admin)
        other = Organization.objects.create(name='Other', email='org@other.example')
        self.review = ProductReview.objects.create(
            organization=other, rating=5, review_title='Great', review_text='Text', reviewer_name='Other Customer',
            reviewer_email='other@customer.example')

    def test_organization_admin_cannot_read_reviews(self):
        self.client.force_login(self.admin)
        for url in (reverse('product_review_list'),
                    reverse('product_review_detail', args=[self.review.id])):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_superuser_can_read_reviews(self):
        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse('product_review_detail', args=[self.review.id])).status_code, 200)
