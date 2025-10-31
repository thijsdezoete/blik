"""
Management command to generate realistic demo data for Blik.
Creates diverse reviewees, cycles in various states, and realistic response patterns.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Reviewee
from questionnaires.models import Questionnaire, Question
from reviews.models import ReviewCycle, ReviewerToken, Response
from reports.services import generate_report
from core.models import Organization
import uuid
import random
from datetime import timedelta

User = get_user_model()


class Command(BaseCommand):
    help = 'Generate realistic demo data for Blik showcase'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reviewees',
            type=int,
            default=15,
            help='Number of reviewees to create (default: 15)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing demo data before generating new data'
        )
        parser.add_argument(
            '--organization',
            type=int,
            help='Organization ID to create demo data for (default: first org)'
        )

    def handle(self, *args, **options):
        num_reviewees = options['reviewees']
        clear_existing = options['clear']
        org_id = options.get('organization')

        if clear_existing:
            self.stdout.write('Clearing existing demo data...')
            Response.objects.all().delete()
            ReviewerToken.objects.all().delete()
            ReviewCycle.objects.all().delete()
            Reviewee.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared existing data'))

        # Get organization
        if org_id:
            try:
                organization = Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Organization with ID {org_id} not found.'))
                return
        else:
            organization = Organization.objects.first()
            if not organization:
                self.stdout.write(self.style.ERROR('No organization found. Run setup first.'))
                return

        # Get admin user from organization
        from accounts.models import UserProfile
        admin_profile = UserProfile.objects.filter(
            organization=organization,
            can_create_cycles_for_others=True
        ).first()

        if not admin_profile:
            self.stdout.write(self.style.ERROR(f'No admin user found for organization {organization.name}.'))
            return

        admin_user = admin_profile.user

        # Get questionnaires
        questionnaires = list(Questionnaire.objects.filter(is_active=True))
        if not questionnaires:
            self.stdout.write(self.style.ERROR('No questionnaires found. Load fixtures first.'))
            return

        self.stdout.write(f'Found {len(questionnaires)} questionnaires')

        # Generate reviewees
        first_names = [
            'Sarah', 'Michael', 'Emily', 'David', 'Lisa', 'James', 'Jessica',
            'Daniel', 'Amanda', 'Christopher', 'Ashley', 'Matthew', 'Jennifer',
            'Joshua', 'Melissa', 'Andrew', 'Michelle', 'Ryan', 'Kimberly', 'Brian',
            'Nicole', 'Kevin', 'Elizabeth', 'Jason', 'Rebecca', 'Justin', 'Laura',
            'Robert', 'Stephanie', 'Brandon'
        ]
        last_names = [
            'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller',
            'Davis', 'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez',
            'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin',
            'Lee', 'Thompson', 'White', 'Harris', 'Sanchez', 'Clark', 'Ramirez',
            'Lewis', 'Robinson', 'Walker'
        ]
        departments = [
            'Engineering', 'Product', 'Design', 'Sales', 'Marketing',
            'Customer Success', 'Operations', 'Finance', 'HR', 'Legal'
        ]

        reviewees = []
        for i in range(num_reviewees):
            first = random.choice(first_names)
            last = random.choice(last_names)
            email = f'{first.lower()}.{last.lower()}@example.com'

            reviewee = Reviewee.objects.create(
                name=f'{first} {last}',
                email=email,
                department=random.choice(departments),
                organization=organization
            )
            reviewees.append(reviewee)

        self.stdout.write(self.style.SUCCESS(f'Created {len(reviewees)} reviewees'))

        # Create review cycles with diverse states
        cycle_count = 0
        completed_count = 0
        active_count = 0
        partial_count = 0

        for reviewee in reviewees:
            # 70% chance of having at least one cycle
            if random.random() > 0.3:
                questionnaire = random.choice(questionnaires)

                # Determine cycle state
                rand = random.random()
                if rand < 0.4:  # 40% completed cycles
                    cycle = self._create_completed_cycle(
                        reviewee, questionnaire, admin_user
                    )
                    completed_count += 1
                elif rand < 0.7:  # 30% partially completed (active)
                    cycle = self._create_partial_cycle(
                        reviewee, questionnaire, admin_user
                    )
                    partial_count += 1
                else:  # 30% just started (active)
                    cycle = self._create_new_cycle(
                        reviewee, questionnaire, admin_user
                    )
                    active_count += 1

                cycle_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Created {cycle_count} review cycles:\n'
            f'  - {completed_count} completed with reports\n'
            f'  - {partial_count} partially completed\n'
            f'  - {active_count} newly created'
        ))

    def _create_completed_cycle(self, reviewee, questionnaire, admin_user):
        """Create a completed cycle with all responses and generated report"""
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=admin_user,
            status='completed'
        )

        # Create 5-9 tokens (varied team sizes)
        num_tokens = random.randint(5, 9)
        categories = ['self'] + ['peer'] * 3 + ['manager'] + ['direct_report'] * 2

        # Randomly add more peers or direct reports
        while len(categories) < num_tokens:
            categories.append(random.choice(['peer', 'direct_report']))

        categories = categories[:num_tokens]
        random.shuffle(categories)

        tokens = []
        for category in categories:
            completed_time = timezone.now() - timedelta(days=random.randint(1, 14))
            token = ReviewerToken.objects.create(
                cycle=cycle,
                category=category,
                token=uuid.uuid4(),
                claimed_at=completed_time - timedelta(hours=random.randint(1, 48)),
                completed_at=completed_time
            )
            tokens.append(token)

        # Create responses with realistic patterns
        questions = list(Question.objects.filter(
            section__questionnaire=questionnaire
        ).order_by('section__order', 'order'))

        # Choose a performance pattern
        pattern = random.choice([
            'high_performer',
            'solid_performer',
            'solid_performer',  # More common
            'developing',
            'imposter_syndrome',
            'overconfident'
        ])

        for token in tokens:
            for question in questions:
                answer_data = self._generate_answer(
                    question, token.category, pattern
                )
                Response.objects.create(
                    cycle=cycle,
                    question=question,
                    token=token,
                    category=token.category,
                    answer_data=answer_data
                )

        # Generate report
        try:
            generate_report(cycle)
        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f'Could not generate report for {reviewee.name}: {e}'
            ))

        return cycle

    def _create_partial_cycle(self, reviewee, questionnaire, admin_user):
        """Create a cycle with some completed tokens, some in progress"""
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=admin_user,
            status='active'
        )

        num_tokens = random.randint(5, 8)
        categories = ['self'] + ['peer'] * 3 + ['manager'] + ['direct_report'] * 2
        categories = categories[:num_tokens]
        random.shuffle(categories)

        # 40-70% of tokens completed
        num_completed = random.randint(int(num_tokens * 0.4), int(num_tokens * 0.7))

        for i, category in enumerate(categories):
            claimed_time = timezone.now() - timedelta(days=random.randint(3, 21))

            if i < num_completed:
                # Completed token
                token = ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=claimed_time,
                    completed_at=claimed_time + timedelta(hours=random.randint(1, 72))
                )

                # Add responses
                questions = list(Question.objects.filter(
                    section__questionnaire=questionnaire
                ).order_by('section__order', 'order'))

                pattern = random.choice(['high_performer', 'solid_performer', 'developing'])
                for question in questions:
                    answer_data = self._generate_answer(question, category, pattern)
                    Response.objects.create(
                        cycle=cycle,
                        question=question,
                        token=token,
                        category=category,
                        answer_data=answer_data
                    )
            elif random.random() < 0.5:
                # Claimed but not completed
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=claimed_time
                )
            else:
                # Not yet claimed
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4()
                )

        return cycle

    def _create_new_cycle(self, reviewee, questionnaire, admin_user):
        """Create a newly started cycle with tokens but minimal completion"""
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=admin_user,
            status='active'
        )

        num_tokens = random.randint(5, 8)
        categories = ['self'] + ['peer'] * 3 + ['manager'] + ['direct_report'] * 2
        categories = categories[:num_tokens]
        random.shuffle(categories)

        for category in categories:
            # Maybe 0-2 tokens claimed
            if random.random() < 0.3:
                claimed_time = timezone.now() - timedelta(days=random.randint(0, 5))
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=claimed_time
                )
            else:
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4()
                )

        return cycle

    def _generate_answer(self, question, category, pattern):
        """Generate realistic answer based on question type and pattern"""
        if question.question_type in ['rating', 'likert']:
            # Generate rating based on pattern and category
            if pattern == 'high_performer':
                base_range = (4, 5)
            elif pattern == 'solid_performer':
                base_range = (3, 5)
            elif pattern == 'developing':
                base_range = (2, 4)
            elif pattern == 'imposter_syndrome':
                # Self rates lower than others
                base_range = (2, 3) if category == 'self' else (4, 5)
            elif pattern == 'overconfident':
                # Self rates higher than others
                base_range = (4, 5) if category == 'self' else (2, 3)
            else:
                base_range = (3, 4)

            rating = random.randint(*base_range)

            # Add some variance
            if random.random() < 0.2:
                rating = max(1, min(5, rating + random.choice([-1, 1])))

            return {'value': rating}

        elif question.question_type == 'text':
            # Generate contextual text responses
            if random.random() < 0.3:
                # 30% chance of no comment
                return {'value': ''}

            positive_comments = [
                'Consistently delivers high-quality work and exceeds expectations.',
                'Great team player who actively helps others succeed.',
                'Shows strong initiative and takes ownership of challenges.',
                'Excellent communication skills across all levels of the organization.',
                'Demonstrates deep expertise and shares knowledge generously.',
                'Adapts quickly to change and handles ambiguity well.',
                'Builds strong relationships and collaborates effectively.',
                'Brings creative solutions to complex problems.',
                'Mentors junior team members with patience and clarity.',
                'Reliable and dependable - always follows through on commitments.',
            ]

            constructive_comments = [
                'Would benefit from improving time management on large projects.',
                'Could be more proactive in seeking feedback and clarification.',
                'Sometimes struggles with prioritization when juggling multiple tasks.',
                'Would benefit from more active participation in team discussions.',
                'Could improve on delegation and trusting team members more.',
                'Sometimes gets too focused on details at the expense of the bigger picture.',
                'Would benefit from being more receptive to alternative approaches.',
                'Could work on communicating progress more regularly with stakeholders.',
                'Would benefit from developing stronger cross-functional collaboration skills.',
                'Could improve on meeting deadlines more consistently.',
            ]

            if pattern in ['high_performer', 'solid_performer']:
                if random.random() < 0.8:
                    return {'value': random.choice(positive_comments)}
                else:
                    return {'value': random.choice(constructive_comments)}
            else:
                if random.random() < 0.5:
                    return {'value': random.choice(constructive_comments)}
                else:
                    return {'value': random.choice(positive_comments)}

        elif question.question_type == 'scale':
            # Handle scale questions (e.g., 1-100)
            config = question.config or {}
            min_val = config.get('min', 1)
            max_val = config.get('max', 100)
            scale_range = max_val - min_val

            # Determine scale position based on pattern
            if pattern == 'high_performer':
                pct = random.uniform(0.75, 0.95)
            elif pattern == 'solid_performer':
                pct = random.uniform(0.6, 0.85)
            elif pattern == 'developing':
                pct = random.uniform(0.4, 0.65)
            elif pattern == 'imposter_syndrome':
                pct = random.uniform(0.4, 0.6) if category == 'self' else random.uniform(0.75, 0.9)
            elif pattern == 'overconfident':
                pct = random.uniform(0.8, 0.95) if category == 'self' else random.uniform(0.4, 0.6)
            else:
                pct = random.uniform(0.5, 0.75)

            scale_value = min_val + int(scale_range * pct)
            return {'value': scale_value}

        elif question.question_type == 'single_choice':
            # Handle single choice questions
            config = question.config or {}
            choices = config.get('choices', [])
            weights = config.get('weights', [])

            if not choices:
                return {'value': ''}

            if weights and config.get('scoring_enabled'):
                # Select based on weights and pattern
                if pattern in ['high_performer', 'solid_performer']:
                    # Select higher weighted options (last 60%)
                    idx = random.randint(max(0, len(choices) * 2 // 5), len(choices) - 1)
                elif pattern == 'developing':
                    # Select lower weighted options (first 60%)
                    idx = random.randint(0, min(len(choices) - 1, len(choices) * 3 // 5))
                else:
                    idx = random.randint(0, len(choices) - 1)
            else:
                # Random selection
                idx = random.randint(0, len(choices) - 1)

            return {'value': choices[idx]}

        elif question.question_type == 'multiple_choice':
            # Handle multiple choice questions
            config = question.config or {}
            choices = config.get('choices', [])

            if not choices:
                return {'value': []}

            # Determine number of selections based on pattern
            if pattern in ['high_performer', 'solid_performer']:
                # Select more options (2-4)
                num_selections = random.randint(2, min(4, len(choices)))
            elif pattern == 'developing':
                # Select fewer options (1-2)
                num_selections = random.randint(1, min(2, len(choices)))
            else:
                # Select middle number (1-3)
                num_selections = random.randint(1, min(3, len(choices)))

            # Randomly select distinct options
            selected = random.sample(choices, num_selections)
            return {'value': selected}

        return {'value': ''}
