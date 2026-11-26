"""
Remove the skill and initiative weights that the old questionnaire editor gave every new question.

The old "Add question" form had two collapsed dropdowns, Skill and Agency, both set to "Medium (1.0)". A creator who
never opened them got {"skill": 1.0, "agency": 1.0} on every question, so the report of a plain questionnaire showed
the skill level (Dreyfus model) and the initiative (agency model) although nobody chose them.

A questionnaire is cleaned only when all of this holds:
- an organization made it, and not from a shipped template (the shipped templates carry weights on purpose);
- it has at least one question with exactly skill 1.0 and agency 1.0;
- no question has another weight. One other weight shows that somebody set the weights on purpose, so such a
  questionnaire is listed and left alone.

Without --apply the command only lists. A report that was already made keeps its sections, because a report stores the
weights it was made with: generate it again after the clean-up.

Usage:
    python manage.py clear_default_model_weights                       # List, change nothing
    python manage.py clear_default_model_weights --apply               # Remove the weights of every listed questionnaire
    python manage.py clear_default_model_weights --apply --questionnaire 12 --questionnaire 15
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from questionnaires.models import Question, Questionnaire
from reports.models import Report


def is_default(mapping):
    """Whether the weights are the ones the old add form sent: skill 1.0 and agency 1.0, nothing else."""

    return isinstance(mapping, dict) and set(mapping) == {'skill', 'agency'} and all(
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight == 1 for weight in mapping.values()
    )


def has_weight(mapping):
    """Whether a mapping counts toward a model, in the new format or the older one with "dimension"."""

    if not isinstance(mapping, dict):
        return False

    weights = [mapping.get('skill'), mapping.get('agency')]

    if mapping.get('dimension') in ('skill', 'agency'):
        weights.append(mapping.get('weight', 1))

    return any(isinstance(weight, (int, float)) and weight != 0 for weight in weights)


class Command(BaseCommand):
    help = 'Remove the skill and initiative weights the old editor gave every new question (lists only without --apply)'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Remove the weights; without it the command only lists')
        parser.add_argument(
            '--questionnaire', action='append', type=int, default=[], metavar='ID',
            help='Only this questionnaire (its id from the list); can be given more than once',
        )

    def handle(self, *args, **options):
        questionnaires = Questionnaire.objects.filter(organization__isnull=False, template_key='') \
            .select_related('organization').prefetch_related('sections__questions').order_by('organization__name', 'name')

        if options['questionnaire']:
            questionnaires = questionnaires.filter(id__in=options['questionnaire'])

        cleaned = left_alone = 0

        for questionnaire in questionnaires:
            questions = [question for section in questionnaire.sections.all() for question in section.questions.all()]
            mappings = [(question.config or {}).get('dreyfus_mapping') for question in questions]
            defaults = [question for question, mapping in zip(questions, mappings) if is_default(mapping)]
            chosen = sum(has_weight(mapping) and not is_default(mapping) for mapping in mappings)

            if not defaults:
                continue

            reports = Report.objects.filter(cycle__questionnaire=questionnaire).count()
            line = (
                f'{questionnaire.id}: "{questionnaire.name}" ({questionnaire.organization.name}): '
                f'{len(defaults)} of {len(questions)} questions have skill 1.0 and initiative 1.0'
            )

            if chosen:
                left_alone += 1
                self.stdout.write(self.style.WARNING(
                    f'{line}; left alone, because {chosen} other question(s) have a weight that somebody chose'
                ))
                continue

            cleaned += 1
            self.stdout.write(f'{line}; {reports} report(s) already made')

            if options['apply']:
                self.clear([question.id for question in defaults])

        if not cleaned and not left_alone:
            self.stdout.write('No questionnaire has the weights of the old editor.')
            return

        if options['apply']:
            self.stdout.write(self.style.SUCCESS(
                f'Removed the weights from {cleaned} questionnaire(s). Reports that were already made keep their '
                f'sections until they are generated again.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'{cleaned} questionnaire(s) would be cleaned, {left_alone} left alone. Nothing was changed: '
                f'run again with --apply, and with --questionnaire ID to clean only some of them.'
            ))

    @transaction.atomic
    def clear(self, question_ids):
        """Take the default weights off these questions; everything else in their config stays."""

        for question in Question.objects.select_for_update().filter(id__in=question_ids):
            # The row is read again under the lock: only a mapping that is still the default goes
            if is_default((question.config or {}).get('dreyfus_mapping')):
                del question.config['dreyfus_mapping']
                question.save(update_fields=['config', 'updated_at'])
