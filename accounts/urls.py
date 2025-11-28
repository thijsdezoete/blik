from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views, invitation_views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('signup/', views.signup_view, name='signup_from_invitation'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/<str:token>/', views.reset_password_view, name='reset_password'),
    path('invite/', invitation_views.send_invitation, name='send_invitation'),
    path('invite/<str:token>/', invitation_views.accept_invitation, name='accept_invitation'),
]
