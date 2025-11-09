"""
Management command to create the Developer Skills Assessment questionnaire for growth hack.

Usage:
    python manage.py create_growth_questionnaire
"""
from django.core.management.base import BaseCommand
from questionnaires.models import Questionnaire, QuestionSection, Question


class Command(BaseCommand):
    help = 'Create the Developer Skills Assessment questionnaire for landing page growth hack'

    def handle(self, *args, **options):
        """Create the complete questionnaire with all sections and questions."""

        # Check if questionnaire already exists
        existing = Questionnaire.objects.filter(
            name="Developer Skills Assessment"
        ).first()

        if existing:
            self.stdout.write(
                self.style.WARNING(
                    f'Questionnaire "Developer Skills Assessment" already exists (UUID: {existing.uuid})'
                )
            )
            response = input('Do you want to recreate it? This will delete all existing data. (yes/no): ')
            if response.lower() != 'yes':
                self.stdout.write('Aborting.')
                return
            existing.delete()

        # Create questionnaire
        questionnaire = Questionnaire.objects.create(
            name="Developer Skills Assessment",
            description="Discover your Dreyfus skill level and agency dimension in 8 minutes. Get personalized development recommendations based on how you approach problems and drive initiatives.",
            is_default=False,
            is_active=True,
            organization=None
        )

        self.stdout.write(self.style.SUCCESS(f'Created questionnaire: {questionnaire.name}'))
        self.stdout.write(f'  UUID: {questionnaire.uuid}')

        # Section 1: Technical Skill Assessment
        skill_section = QuestionSection.objects.create(
            questionnaire=questionnaire,
            title="Technical Skill Assessment",
            description="How you approach technical problems and build expertise",
            order=1
        )

        # Skill questions
        skill_questions = [
            {
                "text": "When facing a new technical challenge, how do you typically approach it?",
                "labels": {
                    "1": "I need step-by-step instructions to proceed",
                    "2": "I follow examples and adapt them to my situation",
                    "3": "I plan my approach and adjust based on results",
                    "4": "I quickly identify patterns and choose optimal solutions",
                    "5": "I intuitively know the right approach and create novel solutions"
                },
                "weight": 2.0
            },
            {
                "text": "How would you describe your relationship with design patterns and best practices?",
                "labels": {
                    "1": "I'm still learning what they are",
                    "2": "I recognize them when I see them",
                    "3": "I actively apply them in my work",
                    "4": "I know when to break the rules",
                    "5": "I create new patterns others follow"
                },
                "weight": 1.5
            },
            {
                "text": "When debugging a complex issue, what's your typical process?",
                "labels": {
                    "1": "Trial and error until something works",
                    "2": "Systematic checking using guides/Stack Overflow",
                    "3": "Form hypotheses and test them methodically",
                    "4": "Quickly narrow down root cause using experience",
                    "5": "Often spot issues before they occur"
                },
                "weight": 1.5
            },
            {
                "text": "How do you learn new technologies or frameworks?",
                "labels": {
                    "1": "Guided tutorials only",
                    "2": "Documentation with examples",
                    "3": "Build projects to understand deeply",
                    "4": "Read source code and understand design",
                    "5": "Evaluate multiple options and make architectural decisions"
                },
                "weight": 1.0
            },
            {
                "text": "During code reviews, what role do you typically play?",
                "labels": {
                    "1": "Primarily receiving feedback",
                    "2": "Spotting syntax and style issues",
                    "3": "Identifying logic errors and edge cases",
                    "4": "Suggesting architectural improvements",
                    "5": "Mentoring others and setting standards"
                },
                "weight": 1.0
            },
            {
                "text": "How well do you understand the systems you work on?",
                "labels": {
                    "1": "I focus on my specific tasks",
                    "2": "I understand my component",
                    "3": "I see how components interact",
                    "4": "I grasp system-wide patterns and tradeoffs",
                    "5": "I design systems others build"
                },
                "weight": 1.5
            },
            {
                "text": "Rate your experience with performance optimization:",
                "labels": {
                    "1": "Rarely think about performance",
                    "2": "Follow basic optimization guidelines",
                    "3": "Profile and optimize bottlenecks",
                    "4": "Design with performance in mind",
                    "5": "Deep expertise in performance engineering"
                },
                "weight": 1.0
            },
            {
                "text": "When requirements are unclear or ambiguous, how do you respond?",
                "labels": {
                    "1": "I need clarity before I can start",
                    "2": "I ask questions until I understand",
                    "3": "I make assumptions and validate them",
                    "4": "I use context to fill gaps confidently",
                    "5": "I help define requirements for others"
                },
                "weight": 1.0,
                "agency_weight": 0.5  # Dual dimension
            },
        ]

        for i, q_data in enumerate(skill_questions, 1):
            config = {
                "min": 1,
                "max": 5,
                "labels": q_data["labels"],
                "dreyfus_mapping": {
                    "skill": q_data["weight"]
                }
            }
            if "agency_weight" in q_data:
                config["dreyfus_mapping"]["agency"] = q_data["agency_weight"]

            Question.objects.create(
                section=skill_section,
                question_text=q_data["text"],
                question_type="rating",
                config=config,
                required=True,
                order=i
            )

        self.stdout.write(f'  Created {len(skill_questions)} skill questions')

        # Section 2: Agency & Initiative
        agency_section = QuestionSection.objects.create(
            questionnaire=questionnaire,
            title="Agency & Initiative",
            description="How you drive work forward and take ownership",
            order=2
        )

        # Agency questions
        agency_questions = [
            {
                "text": "When you encounter a problem outside your immediate responsibilities, what do you do?",
                "labels": {
                    "1": "Report it and wait for assignment",
                    "2": "Fix it if asked to help",
                    "3": "Take initiative to solve it",
                    "4": "Proactively prevent similar issues",
                    "5": "Build systems that empower others to solve"
                },
                "weight": 2.0
            },
            {
                "text": "How do you approach giving feedback or suggesting improvements?",
                "labels": {
                    "1": "I don't usually speak up",
                    "2": "I share when asked",
                    "3": "I proactively suggest improvements",
                    "4": "I champion changes and drive adoption",
                    "5": "I create culture of continuous improvement"
                },
                "weight": 1.5
            },
            {
                "text": "Who drives your professional development?",
                "labels": {
                    "1": "I follow required training",
                    "2": "I learn when manager suggests",
                    "3": "I create my own learning plan",
                    "4": "I seek stretch assignments proactively",
                    "5": "I create learning opportunities for team"
                },
                "weight": 1.5
            },
            {
                "text": "When you're blocked or waiting on others, how do you respond?",
                "labels": {
                    "1": "Wait for the blocker to clear",
                    "2": "Ask for help unblocking",
                    "3": "Find alternative approaches",
                    "4": "Prevent blockers before they occur",
                    "5": "Build systems that eliminate common blockers"
                },
                "weight": 1.5
            },
            {
                "text": "What scope do you typically think about when working?",
                "labels": {
                    "1": "My current task",
                    "2": "My current project",
                    "3": "My team's roadmap",
                    "4": "Company-wide impact",
                    "5": "Industry/ecosystem influence"
                },
                "weight": 1.0,
                "skill_weight": 0.5  # Dual dimension
            },
        ]

        for i, q_data in enumerate(agency_questions, 1):
            config = {
                "min": 1,
                "max": 5,
                "labels": q_data["labels"],
                "dreyfus_mapping": {
                    "agency": q_data["weight"]
                }
            }
            if "skill_weight" in q_data:
                config["dreyfus_mapping"]["skill"] = q_data["skill_weight"]

            Question.objects.create(
                section=agency_section,
                question_text=q_data["text"],
                question_type="rating",
                config=config,
                required=True,
                order=i
            )

        self.stdout.write(f'  Created {len(agency_questions)} agency questions')

        # Section 3: Context (Optional)
        context_section = QuestionSection.objects.create(
            questionnaire=questionnaire,
            title="Context (Optional)",
            description="Help us personalize your results",
            order=3
        )

        # Optional text questions
        Question.objects.create(
            section=context_section,
            question_text="What's your current role and years of experience?",
            question_type="text",
            config={"placeholder": "e.g., Senior Engineer, 5 years"},
            required=False,
            order=1
        )

        Question.objects.create(
            section=context_section,
            question_text="What's your biggest professional growth goal right now?",
            question_type="text",
            config={"placeholder": "e.g., Become a tech lead, improve system design skills"},
            required=False,
            order=2
        )

        self.stdout.write(f'  Created 2 optional context questions')

        # Summary
        total_questions = len(skill_questions) + len(agency_questions) + 2
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('✓ Successfully created questionnaire'))
        self.stdout.write(f'  Total: {total_questions} questions (13 required, 2 optional)')
        self.stdout.write(f'  UUID: {questionnaire.uuid}')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Next step:'))
        self.stdout.write(f'  Add to .env: GROWTH_QUESTIONNAIRE_UUID={questionnaire.uuid}')
