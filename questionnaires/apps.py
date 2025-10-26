from django.apps import AppConfig


class QuestionnairesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'questionnaires'

    def ready(self):
        import questionnaires.signals  # noqa
