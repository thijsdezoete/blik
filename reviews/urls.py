from django.urls import path
from . import views

app_name = 'reviews'

urlpatterns = [
    # Token claiming flow (for invitation links) - uses secure invitation token
    path('feedback/invite/<uuid:invitation_token>/', views.claim_token, name='claim_token'),

    # Direct feedback access
    path('feedback/<uuid:token>/', views.feedback_form, name='feedback_form'),
    path('feedback/<uuid:token>/submit/', views.submit_feedback, name='submit_feedback'),
    path('feedback/<uuid:token>/complete/', views.feedback_complete, name='feedback_complete'),
]
