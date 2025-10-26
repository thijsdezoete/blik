"""
URL configuration for blik project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views, admin_views, seo_views

# Error handlers
handler404 = 'blik.views.handler404'
handler500 = 'blik.views.handler500'

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health_check, name='health_check'),
    path('sitemap.xml', seo_views.sitemap, name='sitemap'),
    path('robots.txt', seo_views.robots, name='robots'),
    path('admin/', admin.site.urls),

    # Admin dashboard
    path('dashboard/', admin_views.dashboard, name='admin_dashboard'),
    path('dashboard/settings/', admin_views.settings_view, name='settings'),
    path('dashboard/team/', admin_views.team_list, name='team_list'),
    path('dashboard/reviewees/', admin_views.reviewee_list, name='reviewee_list'),
    path('dashboard/reviewees/create/', admin_views.reviewee_create, name='reviewee_create'),
    path('dashboard/reviewees/<int:reviewee_id>/edit/', admin_views.reviewee_edit, name='reviewee_edit'),
    path('dashboard/reviewees/<int:reviewee_id>/delete/', admin_views.reviewee_delete, name='reviewee_delete'),
    path('dashboard/questionnaires/', admin_views.questionnaire_list, name='questionnaire_list'),
    path('dashboard/questionnaires/create/', admin_views.questionnaire_create, name='questionnaire_create'),
    path('dashboard/questionnaires/<int:questionnaire_id>/edit/', admin_views.questionnaire_edit, name='questionnaire_edit'),
    path('dashboard/questionnaires/<int:questionnaire_id>/preview/', admin_views.questionnaire_preview, name='questionnaire_preview'),
    path('dashboard/cycles/', admin_views.review_cycle_list, name='review_cycle_list'),
    path('dashboard/cycles/create/', admin_views.review_cycle_create, name='review_cycle_create'),
    path('dashboard/cycles/<int:cycle_id>/', admin_views.review_cycle_detail, name='review_cycle_detail'),
    path('dashboard/cycles/<int:cycle_id>/invitations/', admin_views.manage_invitations, name='manage_invitations'),
    path('dashboard/cycles/<int:cycle_id>/invitations/assign/', admin_views.assign_invitations, name='assign_invitations'),
    path('dashboard/cycles/<int:cycle_id>/invitations/send/', admin_views.send_invitations, name='send_invitations'),
    path('dashboard/cycles/<int:cycle_id>/generate-report/', admin_views.generate_report_view, name='generate_report'),
    path('dashboard/cycles/<int:cycle_id>/close/', admin_views.close_cycle, name='close_cycle'),
    path('dashboard/cycles/<int:cycle_id>/send-reminder/', admin_views.send_reminder_form, name='send_reminder_form'),
    path('dashboard/cycles/<int:cycle_id>/send-reminder/send/', admin_views.send_reminder, name='send_reminder'),

    # Other apps
    path('setup/', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('account/', include('blik.account_urls')),
    path('', include('reviews.urls')),
    path('', include('reports.urls')),
    path('landing/', include('landing.urls')),
    path('api/', include('subscriptions.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
