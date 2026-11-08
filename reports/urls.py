from django.urls import path
from . import views
from .sample import sample_report_pdf

app_name = 'reports'

urlpatterns = [
    # Public sample for the landing pages; built from the current code, nothing stored
    path('reports/sample.pdf', sample_report_pdf, name='sample_report_pdf'),

    # Admin views (require staff authentication)
    path('report/<uuid:cycle_uuid>/', views.view_report, name='view_report'),
    path('report/<uuid:cycle_uuid>/pdf/', views.report_pdf, name='report_pdf'),
    path('report/<uuid:cycle_uuid>/regenerate/', views.regenerate_report, name='regenerate_report'),

    # Reviewee views (require secure token)
    path('my-report/<uuid:access_token>/', views.reviewee_report, name='reviewee_report'),
    path('my-report/<uuid:access_token>/pdf/', views.reviewee_report_pdf, name='reviewee_report_pdf'),
]
