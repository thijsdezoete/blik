from django.contrib import admin
from django.utils.formats import date_format
from django.utils import timezone
from django.utils.translation import gettext as _

from subscriptions.utils import billing_enabled

from .models import CronRun, EmailLog

# The daily commands that docker-entrypoint.sh puts in cron.
COMMANDS = ['send_cycle_reminders', 'send_trial_reminders', 'send_lifecycle_emails']


class OperatorAdmin(admin.ModelAdmin):
    """Read-only, and only on the hosted SaaS: self-hosters don't run the billing emails."""

    def has_module_permission(self, request):
        return billing_enabled() and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return billing_enabled() and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EmailLog)
class EmailLogAdmin(OperatorAdmin):
    list_display = ['sent_at', 'organization', 'kind', 'recipient', 'error']
    list_filter = ['kind']
    search_fields = ['organization__name', 'recipient']
    list_select_related = ['organization']


@admin.register(CronRun)
class CronRunAdmin(OperatorAdmin):
    list_display = ['ran_at', 'command', 'sent', 'errors']
    list_filter = ['command']

    def get_queryset(self, request):
        # Only the runs that tried to send; runs with nothing due are kept for the last-run line.
        return super().get_queryset(request).exclude(sent=0, errors='')

    def changelist_view(self, request, extra_context=None):
        # One line per command, so a command that stopped running stands out next to the others.
        last_runs = [CronRun.objects.filter(command=c).first() for c in COMMANDS]
        subtitle = ' · '.join(
            _('%(command)s: last run %(time)s') % {
                'command': c, 'time': date_format(timezone.localtime(run.ran_at), 'DATETIME_FORMAT'),
            } if run else _('%(command)s: never ran') % {'command': c}
            for c, run in zip(COMMANDS, last_runs)
        )
        return super().changelist_view(request, {'subtitle': subtitle, **(extra_context or {})})
