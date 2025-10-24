from django.urls import path
from . import views

app_name = 'landing'

urlpatterns = [
    path('', views.index, name='index'),
    path('og-image.png', views.og_image, name='og_image'),
]
