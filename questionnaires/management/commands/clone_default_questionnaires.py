from django.core.management.base import BaseCommand
from core.models import Organization
from questionnaires.models import Questionnaire
from questionnaires.signals import clone_questionnaire_for_organization


class Command(BaseCommand):
    help = 'Clone default questionnaires to all existing organizations that don\'t have them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force clone even if organization already has questionnaires',
        )

    def handle(self, *args, **options):
        force = options['force']

        # Get all template questionnaires
        template_questionnaires = Questionnaire.objects.templates()

        if not template_questionnaires.exists():
            self.stdout.write(self.style.WARNING('No default questionnaires found to clone.'))
            return

        self.stdout.write(f'Found {template_questionnaires.count()} default questionnaire(s) to clone.')

        # Get all organizations
        organizations = Organization.objects.all()

        if not organizations.exists():
            self.stdout.write(self.style.WARNING('No organizations found.'))
            return

        cloned_count = 0
        skipped_count = 0

        for org in organizations:
            # Check if org already has questionnaires
            existing_questionnaires = Questionnaire.objects.filter(organization=org).count()

            if existing_questionnaires > 0 and not force:
                self.stdout.write(
                    self.style.WARNING(f'Skipping {org.name} - already has {existing_questionnaires} questionnaire(s)')
                )
                skipped_count += 1
                continue

            # Clone each template
            org_cloned = 0
            for template in template_questionnaires:
                clone_questionnaire_for_organization(template, org)
                org_cloned += 1
                cloned_count += 1

            self.stdout.write(
                self.style.SUCCESS(f'Cloned {org_cloned} questionnaire(s) to {org.name}')
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nComplete! Cloned {cloned_count} questionnaire(s) total. Skipped {skipped_count} organization(s).'
            )
        )
