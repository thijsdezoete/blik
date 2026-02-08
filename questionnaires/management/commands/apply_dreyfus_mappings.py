"""
Management command to apply Dreyfus model mappings to all questionnaire questions.

Updates existing DB records (templates + org copies) for all questionnaires that
need dreyfus_mapping in their question config. Also normalizes Manager 360 Review
wording from "My manager" to "This person" for 360-degree reviewer neutrality.

Idempotent -- safe to run multiple times.

Usage:
    python manage.py apply_dreyfus_mappings           # Apply changes
    python manage.py apply_dreyfus_mappings --dry-run  # Preview without saving
"""
from django.core.management.base import BaseCommand
from questionnaires.models import Questionnaire, Question


# Mappings keyed by questionnaire name -> question text substring -> dreyfus_mapping value.
# Substrings are chosen to match regardless of wording variants (e.g. "My manager" vs "This person").
# Only questions that should have a mapping are listed; text and unmapped questions are skipped.
QUESTIONNAIRE_MAPPINGS = {
    "Software Engineering 360 Review": {
        "Understanding customer problems": {"skill": 1.0},
        "translate ideas into clear, readable code": {"skill": 1.5},
        "work with the team to solve complex problems": {"agency": 0.5},
        # pk5 friendly/approachable -- unmapped
        "approach solving technical problems": {"skill": 1.5},
        "familiarity with the full technology stack": {"skill": 1.0},
        "emerging technologies and industry trends": {"skill": 0.5, "agency": 0.5},
        "enthusiasm for the work": {"agency": 0.5},
        "demonstrate initiative in solving problems": {"agency": 1.5},
        "application of sound software development principles": {"skill": 1.0},
        "refactor and improve existing code": {"skill": 0.5, "agency": 1.0},
        "awareness of their limitations and display humility": {"agency": 0.5},
        "balance technical excellence with practical business": {"skill": 1.0},
        "appreciate simplicity and avoid over-engineering": {"skill": 1.0},
        "listen and accept that others might have better ideas": {"agency": 0.5},
        "share knowledge and mentor less experienced": {"skill": 0.5, "agency": 0.5},
        "explain technical decisions and system architecture": {"skill": 1.0},
        "learn and adopt new technologies": {"skill": 0.5},
        "curiosity for new languages, frameworks": {"agency": 1.0},
        "adapt to changing requirements or circumstances": {"skill": 0.5, "agency": 0.5},
        "understand the broader product and business context": {"skill": 1.0},
        "foresight for problems not yet encountered": {"skill": 1.0},
        "contribute to and align with the shared team vision": {"agency": 1.0},
    },
    "Professional Skills 360 Review": {
        "analyze and solve problems": {"skill": 1.5},
        "make decisions under pressure": {"skill": 1.0},
        "clearly and effectively": {"skill": 0.5},
        "collaborate and work with others": {"agency": 0.5},
        # pk1006 active listening -- unmapped
        "proactively": {"agency": 1.5},
        "takes ownership and follows through on commitments": {"agency": 1.0},
        "learn new skills and concepts": {"skill": 0.5},
        "adapt to change and handle ambiguity": {"skill": 0.5, "agency": 0.5},
        "quality of work": {"skill": 1.0},
        "balance quality with practical deadlines": {"skill": 1.0},
        "influence and guide others": {"agency": 1.0},
        "develop and support the growth of others": {"skill": 0.5, "agency": 0.5},
        "understand and contribute to broader organizational": {"skill": 1.0},
        # pk1021 professionalism -- unmapped
        "handle feedback and demonstrate self-awareness": {"agency": 0.5},
        # pk1023 positive attitude -- unmapped
    },
    "Manager 360 Review": {
        "visible and engaged with the team": {"agency": 1.0},
        "intentions and decisions": {"skill": 1.0},
        "communicates clearly about decisions": {"skill": 1.0},
        "Goals and priorities are clearly defined": {"skill": 1.5},
        "clear direction and gives": {"skill": 1.0, "agency": 0.5},
        "obstacles are discussed and addressed in time": {"skill": 0.5, "agency": 1.5},
        "understands the content of our work well enough to guide": {"skill": 1.5},
        "makes informed decisions about our work": {"skill": 1.0},
        "way of leading contributes visibly to team performance": {"skill": 1.0, "agency": 0.5},
        "encourages results-oriented work": {"agency": 1.0},
        "regular, useful feedback": {"skill": 0.5, "agency": 1.0},
        "recognizes good work when it happens": {"agency": 1.0},
        "encourages personal and professional growth": {"agency": 1.0},
        "recognizes and names individual strengths": {"skill": 1.0},
        "supports the development of new skills": {"skill": 0.5, "agency": 0.5},
    },
    "360 Degree Feedback": {
        "Problem solving ability": {"skill": 1.5},
        "Code quality and clarity": {"skill": 1.0},
        "Technical expertise level": {"skill": 1.5},
        "Teamwork and collaboration": {"agency": 0.5},
        "communicates clearly and effectively": {"skill": 0.5},
        "Helps and mentors others": {"skill": 0.5, "agency": 0.5},
        "Initiative and motivation": {"agency": 1.5},
        "flexible and adapts well to change": {"skill": 0.5, "agency": 0.5},
        "Delivers quality work on time": {"skill": 1.0},
    },
    "Agency & Initiative Assessment": {
        "identify problems before they escalate": {"agency": 1.5},
        "proactively suggests solutions when raising issues": {"agency": 1.0},
        "Quality of solutions": {"skill": 1.0, "agency": 0.5},
        "recommends their preferred solution with reasoning": {"skill": 0.5, "agency": 1.0},
        "independently implement solutions": {"agency": 2.0},
        "keeps stakeholders appropriately informed when taking initiative": {"agency": 1.0},
    },
}

# Manager 360 wording fixes: "My manager" -> "This person" for reviewer neutrality.
# Maps old (DB) text -> new text. Covers both rating and text questions.
MANAGER_360_WORDING = {
    "My manager is visible and engaged with the team":
        "This person is visible and engaged with the team",
    "I trust my manager's intentions and decisions":
        "I trust this person's intentions and decisions",
    "My manager communicates clearly about decisions and their reasoning":
        "This person communicates clearly about decisions and their reasoning",
    "My manager provides clear direction and gives me autonomy to execute":
        "This person provides clear direction and gives appropriate autonomy to execute",
    "My manager understands the content of our work well enough to guide effectively":
        "This person understands the content of our work well enough to guide effectively",
    "My manager makes informed decisions about our work":
        "This person makes informed decisions about our work",
    "My manager's way of leading contributes visibly to team performance":
        "This person's way of leading contributes visibly to team performance",
    "My manager encourages results-oriented work":
        "This person encourages results-oriented work",
    "I receive regular, useful feedback from my manager":
        "I receive regular, useful feedback from this person",
    "My manager recognizes good work when it happens":
        "This person recognizes good work when it happens",
    "My manager encourages personal and professional growth":
        "This person encourages personal and professional growth",
    "My manager recognizes and names individual strengths":
        "This person recognizes and names individual strengths",
    "My manager supports the development of new skills":
        "This person supports the development of new skills",
    "What should my manager keep doing?":
        "What should this person keep doing?",
    "What should my manager do differently?":
        "What should this person do differently?",
}


class Command(BaseCommand):
    help = 'Apply Dreyfus model mappings and fix Manager 360 wording in the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without saving to the database',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN -- no changes will be saved\n'))

        total_updated = 0
        total_skipped = 0

        for questionnaire_name, question_mappings in QUESTIONNAIRE_MAPPINGS.items():
            questionnaires = Questionnaire.objects.filter(name=questionnaire_name)

            if not questionnaires.exists():
                self.stdout.write(
                    self.style.WARNING(f'  No questionnaires found with name "{questionnaire_name}"')
                )
                continue

            q_count = questionnaires.count()
            self.stdout.write(
                f'\n{questionnaire_name} ({q_count} instance{"s" if q_count != 1 else ""})'
            )

            updated_for_questionnaire = 0
            skipped_for_questionnaire = 0

            for questionnaire in questionnaires:
                questions = Question.objects.filter(
                    section__questionnaire=questionnaire
                ).exclude(
                    question_type__in=['text', 'multiple_choice']
                )

                for question in questions:
                    # Find matching mapping by text substring
                    mapping = None
                    for text_substr, dreyfus_mapping in question_mappings.items():
                        if text_substr.lower() in question.question_text.lower():
                            mapping = dreyfus_mapping
                            break

                    if mapping is None:
                        skipped_for_questionnaire += 1
                        continue

                    # Check if already has the correct mapping
                    current = question.config.get('dreyfus_mapping')
                    if current == mapping:
                        skipped_for_questionnaire += 1
                        continue

                    if dry_run:
                        old_desc = f' (was: {current})' if current else ''
                        self.stdout.write(
                            f'  Would update: "{question.question_text[:60]}..." '
                            f'-> {mapping}{old_desc}'
                        )
                    else:
                        question.config['dreyfus_mapping'] = mapping
                        question.save(update_fields=['config'])

                    updated_for_questionnaire += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f'  Updated: {updated_for_questionnaire}, Skipped: {skipped_for_questionnaire}'
                )
            )
            total_updated += updated_for_questionnaire
            total_skipped += skipped_for_questionnaire

        # Fix Manager 360 wording
        wording_updated = self._fix_manager_wording(dry_run)

        action = 'Would update' if dry_run else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'\nComplete! {action} {total_updated} mapping(s), '
                f'{wording_updated} wording fix(es). '
                f'Skipped {total_skipped} (already correct or unmapped).'
            )
        )

    def _fix_manager_wording(self, dry_run):
        """Replace 'My manager' wording with 'This person' in all Manager 360 instances."""
        questionnaires = Questionnaire.objects.filter(name="Manager 360 Review")

        if not questionnaires.exists():
            return 0

        self.stdout.write(f'\nManager 360 wording fixes ({questionnaires.count()} instances)')

        updated = 0
        for questionnaire in questionnaires:
            questions = Question.objects.filter(section__questionnaire=questionnaire)

            for question in questions:
                new_text = MANAGER_360_WORDING.get(question.question_text)
                if new_text is None:
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  Would fix: "{question.question_text[:50]}..." '
                        f'-> "{new_text[:50]}..."'
                    )
                else:
                    question.question_text = new_text
                    question.save(update_fields=['question_text'])

                updated += 1

        self.stdout.write(self.style.SUCCESS(f'  Fixed: {updated} question(s)'))
        return updated
