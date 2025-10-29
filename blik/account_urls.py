"""URL patterns for account management."""
from django.urls import path
from . import account_views

app_name = 'account'

urlpatterns = [
    path('settings/', account_views.account_settings, name='settings'),
    path('export/', account_views.export_data, name='export_data'),
    path('import/', account_views.import_data, name='import_data'),
    path('import/preview/', account_views.preview_import, name='preview_import'),
    path('subscription/cancel/', account_views.cancel_subscription_view, name='cancel_subscription'),
    path('subscription/reactivate/', account_views.reactivate_subscription_view, name='reactivate_subscription'),
    path('delete/', account_views.delete_account, name='delete_account'),
    path('organization/delete/', account_views.delete_organization, name='delete_organization'),
]
