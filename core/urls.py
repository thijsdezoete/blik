from django.urls import path
from . import views

urlpatterns = [
    path('', views.setup_welcome, name='setup_welcome'),
    path('admin/', views.setup_admin, name='setup_admin'),
    path('organization/', views.setup_organization, name='setup_organization'),
    path('email/', views.setup_email, name='setup_email'),
    path('complete/', views.setup_complete, name='setup_complete'),
]
