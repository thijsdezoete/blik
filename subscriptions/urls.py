from django.urls import path
from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('stripe/create-checkout-session/', views.create_checkout_session, name='create_checkout_session'),
]
