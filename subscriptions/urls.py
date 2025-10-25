from django.urls import path
from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('stripe/webhook/', views.stripe_webhook, name='stripe_webhook'),
    path('stripe/create-checkout-session/', views.create_checkout_session, name='create_checkout_session'),
    path('stripe/checkout-success/', views.checkout_success, name='checkout_success'),
    path('stripe/billing-portal/', views.billing_portal, name='billing_portal'),
    path('auto-login/<str:token>/', views.auto_login, name='auto_login'),
]
