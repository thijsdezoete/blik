from django.urls import path
from . import views

app_name = 'landing'

urlpatterns = [
    path('', views.index, name='index'),
    path('open-source/', views.open_source, name='open_source'),
    path('dreyfus-model/', views.dreyfus_model, name='dreyfus_model'),
    path('eu-tech/', views.eu_tech, name='eu_tech'),
    path('privacy/', views.privacy, name='privacy'),
    path('og-image.png', views.og_image, name='og_image'),
]
