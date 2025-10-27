"""
URL configuration for landing container.

Serves landing pages at root paths instead of /landing/ prefix.
"""
from django.urls import path
from landing import views
from blik import seo_views

urlpatterns = [
    # Landing pages at root
    path('', views.index, name='index'),
    path('signup/', views.signup, name='signup'),
    path('open-source/', views.open_source, name='open_source'),
    path('dreyfus-model/', views.dreyfus_model, name='dreyfus_model'),
    path('eu-tech/', views.eu_tech, name='eu_tech'),
    path('privacy/', views.privacy, name='privacy'),

    # Legal pages
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms/', views.terms, name='terms'),

    # SEO files
    path('og-image.png', views.og_image, name='og_image'),
    path('robots.txt', seo_views.robots, name='robots'),
    path('sitemap.xml', seo_views.sitemap, name='sitemap'),
]
