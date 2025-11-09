from django.urls import path
from . import views
from blik import seo_views

app_name = 'landing'

urlpatterns = [
    path('', views.index, name='index'),
    path('hr-managers/', views.hr_managers, name='hr_managers'),
    path('signup/', views.signup, name='signup'),
    path('developers/', views.developers, name='developers'),
    path('open-source/', views.open_source, name='open_source'),
    path('dreyfus-model/', views.dreyfus_model, name='dreyfus_model'),
    path('agency-levels/', views.agency_levels, name='agency_levels'),
    path('performance-matrix/', views.performance_matrix, name='performance_matrix'),
    path('eu-tech/', views.eu_tech, name='eu_tech'),
    path('privacy/', views.privacy, name='privacy'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms/', views.terms, name='terms'),
    path('vs-lattice/', views.vs_lattice, name='vs_lattice'),
    path('vs-culture-amp/', views.vs_culture_amp, name='vs_culture_amp'),
    path('vs-15five/', views.vs_15five, name='vs_15five'),
    path('vs-orangehrm/', views.vs_orangehrm, name='vs_orangehrm'),
    path('vs-odoo/', views.vs_odoo, name='vs_odoo'),
    path('why-blik/', views.why_blik, name='why_blik'),
    path('people-analytics/', views.people_analytics, name='people_analytics'),
    path('about/', views.about, name='about'),
    path('og-image.png', views.og_image, name='og_image'),
    path('robots.txt', seo_views.robots, name='robots'),
    path('sitemap.xml', seo_views.sitemap, name='sitemap'),

    # Growth hack: Developer Skills Assessment
    path('dreyfus-assessment/', views.dreyfus_assessment_start, name='dreyfus_assessment_start'),
    path('dreyfus-assessment/submit/', views.dreyfus_assessment_submit, name='dreyfus_assessment_submit'),
    path('dreyfus-assessment/capture-email/', views.dreyfus_capture_email, name='dreyfus_capture_email'),
]
