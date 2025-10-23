from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('report/<int:cycle_id>/', views.view_report, name='view_report'),
    path('report/<int:cycle_id>/regenerate/', views.regenerate_report, name='regenerate_report'),
]
