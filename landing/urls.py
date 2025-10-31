from django.urls import path
from . import views
from blik import seo_views

app_name = 'landing'

urlpatterns = [
    path('', views.index, name='index'),
    path('hr-managers/', views.hr_managers, name='hr_managers'),
    path('signup/', views.signup, name='signup'),
    path('open-source/', views.open_source, name='open_source'),
    path('dreyfus-model/', views.dreyfus_model, name='dreyfus_model'),
    path('agency-levels/', views.agency_levels, name='agency_levels'),
    path('eu-tech/', views.eu_tech, name='eu_tech'),
    path('privacy/', views.privacy, name='privacy'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms/', views.terms, name='terms'),
    path('og-image.png', views.og_image, name='og_image'),
    path('robots.txt', seo_views.robots, name='robots'),
    path('sitemap.xml', seo_views.sitemap, name='sitemap'),
]
