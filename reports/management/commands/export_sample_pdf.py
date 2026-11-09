"""Write the sample report PDF to a file. The landing container runs this at start."""
from django.core.management.base import BaseCommand, CommandError

from reports.sample import SAMPLE_QUESTIONNAIRE, build_sample_pdf


class Command(BaseCommand):
    help = 'Render the sample report PDF to PATH'

    def add_arguments(self, parser):
        parser.add_argument('path')

    def handle(self, path, **options):
        pdf = build_sample_pdf('en')
        if pdf is None:
            raise CommandError(f'The shipped questionnaire "{SAMPLE_QUESTIONNAIRE}" is not installed; run manage.py upgrade first')
        with open(path, 'wb') as f:
            f.write(pdf)
        self.stdout.write(f'Wrote {len(pdf)} bytes to {path}')
