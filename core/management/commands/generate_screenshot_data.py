"""
Management command to generate optimized demo data specifically for screenshots.
Creates a single organization with carefully crafted data for visual appeal.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, assign_organization_member
from accounts.services import create_user_with_email_as_username
from questionnaires.models import Questionnaire, Question
from reviews.models import ReviewCycle, ReviewerToken, Response
from reports.services import generate_report
from reports.models import Report
from core.models import Organization
import uuid
import json
from datetime import timedelta

User = get_user_model()


class Command(BaseCommand):
    help = 'Generate optimized demo data for screenshots'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing demo data before generating new data'
        )

    def handle(self, *args, **options):
        clear_existing = options['clear']

        if clear_existing:
            self.stdout.write('Clearing existing screenshot demo data...')
            Response.objects.all().delete()
            ReviewerToken.objects.all().delete()
            ReviewCycle.objects.all().delete()
            Reviewee.objects.all().delete()

            # Delete Acme Corporation organization and its users
            acme_org = Organization.objects.filter(name='Acme Corporation').first()
            if acme_org:
                # Delete user profiles and users for this org
                user_profiles = UserProfile.objects.filter(organization=acme_org)
                user_ids = list(user_profiles.values_list('user_id', flat=True))
                user_profiles.delete()
                User.objects.filter(id__in=user_ids).delete()
                acme_org.delete()

            self.stdout.write(self.style.SUCCESS('Cleared existing data'))

        # Create organization
        org = Organization.objects.create(
            name='Acme Corporation',
            email='admin@acme.example.com',
            min_responses_for_anonymity=3,
            allow_registration=True,
            default_users_can_create_cycles=False
        )
        self.stdout.write(self.style.SUCCESS(f'Created organization: {org.name}'))

        # Create admin user with proper org admin permissions
        admin, _ = create_user_with_email_as_username(
            email='admin@acme.example.com',
            password='demo123',
            first_name='Admin',
            last_name='User'
        )
        UserProfile.objects.create(
            user=admin,
            organization=org,
            can_create_cycles_for_others=True
        )
        # Assign organization admin permissions
        assign_organization_admin(admin)
        self.stdout.write(self.style.SUCCESS(f'Created admin user: {admin.email} (password: demo123)'))

        # Create additional team members for team page
        team_members = [
            ('Sarah', 'Johnson', 'sarah.johnson@acme.example.com', True),  # Org Admin
            ('Michael', 'Chen', 'michael.chen@acme.example.com', False),  # Member
            ('Emily', 'Rodriguez', 'emily.rodriguez@acme.example.com', False),
            ('David', 'Kim', 'david.kim@acme.example.com', False),
            ('Lisa', 'Anderson', 'lisa.anderson@acme.example.com', False),
            ('James', 'Wilson', 'james.wilson@acme.example.com', False),
            ('Jessica', 'Martinez', 'jessica.martinez@acme.example.com', False),
            ('Daniel', 'Taylor', 'daniel.taylor@acme.example.com', True),  # Org Admin
        ]

        for first, last, email, is_admin in team_members:
            user, _ = create_user_with_email_as_username(
                email=email,
                password='demo123',
                first_name=first,
                last_name=last
            )
            UserProfile.objects.create(
                user=user,
                organization=org,
                can_create_cycles_for_others=is_admin
            )
            # Assign proper permissions
            if is_admin:
                assign_organization_admin(user)
            else:
                assign_organization_member(user, can_create_cycles_for_others=False)

        self.stdout.write(self.style.SUCCESS(f'Created {len(team_members)} team members'))

        # Get default questionnaire
        questionnaire = Questionnaire.objects.filter(is_active=True).first()
        if not questionnaire:
            self.stdout.write(self.style.ERROR('No questionnaire found. Run clone_default_questionnaires first.'))
            return

        # Create reviewees for different cycle states
        reviewees_data = [
            ('John Smith', 'john.smith@acme.example.com', 'Engineering', 'completed'),
            ('Emma Davis', 'emma.davis@acme.example.com', 'Product', 'partial_60'),
            ('Robert Brown', 'robert.brown@acme.example.com', 'Design', 'partial_20'),
            ('Sophia Garcia', 'sophia.garcia@acme.example.com', 'Engineering', 'new_90'),
            ('William Lee', 'william.lee@acme.example.com', 'Sales', 'completed'),
        ]

        cycles_output = []
        feedback_token_for_screenshots = None

        for name, email, dept, cycle_type in reviewees_data:
            reviewee = Reviewee.objects.create(
                name=name,
                email=email,
                department=dept,
                organization=org
            )

            if cycle_type == 'completed':
                cycle = self._create_completed_cycle(reviewee, questionnaire, admin)
                cycles_output.append({
                    'reviewee': name,
                    'status': 'completed',
                    'cycle_id': cycle.id,
                    'has_report': True
                })
            elif cycle_type.startswith('partial_'):
                completion_pct = int(cycle_type.split('_')[1])
                cycle = self._create_partial_cycle(reviewee, questionnaire, admin, completion_pct)
                cycles_output.append({
                    'reviewee': name,
                    'status': 'active',
                    'cycle_id': cycle.id,
                    'completion': f'{completion_pct}%'
                })

                # Get an uncompleted token for feedback form screenshots
                if not feedback_token_for_screenshots:
                    uncompleted_token = ReviewerToken.objects.filter(
                        cycle=cycle,
                        completed_at__isnull=True
                    ).first()
                    if uncompleted_token:
                        feedback_token_for_screenshots = str(uncompleted_token.token)

            elif cycle_type.startswith('new_'):
                claim_pct = int(cycle_type.split('_')[1])
                cycle = self._create_new_cycle(reviewee, questionnaire, admin, claim_pct)
                cycles_output.append({
                    'reviewee': name,
                    'status': 'active',
                    'cycle_id': cycle.id,
                    'claimed': f'{claim_pct}%'
                })

        self.stdout.write(self.style.SUCCESS(f'Created {len(reviewees_data)} review cycles'))

        # Get report access token for completed cycle
        report_access_token = None
        completed_report = Report.objects.filter(cycle_id=cycles_output[0]['cycle_id']).first()
        if completed_report and completed_report.access_token:
            report_access_token = str(completed_report.access_token)

        # Output JSON for screenshot script
        output_data = {
            'organization_id': org.id,
            'organization_name': org.name,
            'admin_username': admin.email,
            'admin_password': 'demo123',
            'cycles': cycles_output,
            'completed_cycle_id': cycles_output[0]['cycle_id'],
            'partial_cycle_id': cycles_output[1]['cycle_id'],
            'feedback_token': feedback_token_for_screenshots,
            'report_access_token': report_access_token,
            'team_count': len(team_members) + 1,
            'base_url': 'http://localhost:8000'
        }

        print('\n' + '='*80)
        print('SCREENSHOT DATA CONFIGURATION')
        print('='*80)
        print(json.dumps(output_data, indent=2))
        print('='*80)

        # Save to file for screenshot script
        with open('/tmp/blik_screenshot_config.json', 'w') as f:
            json.dump(output_data, f, indent=2)

        self.stdout.write(self.style.SUCCESS('\nConfiguration saved to: /tmp/blik_screenshot_config.json'))

    def _create_completed_cycle(self, reviewee, questionnaire, admin_user):
        """Create a completed cycle with visually interesting data"""
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=admin_user,
            status='completed'
        )

        # Create tokens: 1 self, 3 managers, 4 peers, 2 direct reports = 10 total
        token_configs = [
            ('self', 1),
            ('manager', 3),
            ('peer', 4),
            ('direct_report', 2),
        ]

        tokens = []
        for category, count in token_configs:
            for _ in range(count):
                completed_time = timezone.now() - timedelta(days=7)
                token = ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=completed_time - timedelta(hours=24),
                    completed_at=completed_time
                )
                tokens.append(token)

        # Get questions
        questions = list(Question.objects.filter(
            section__questionnaire=questionnaire
        ).order_by('section__order', 'order'))

        # Create responses with differentiated patterns by category
        for token in tokens:
            for question in questions:
                question_seed = hash(question.id) % 10

                if question.question_type in ['rating', 'likert']:
                    # Create realistic differentiation between categories
                    if token.category == 'self':
                        # Self rates lower (imposter syndrome pattern: 2-3)
                        rating = 2 if question_seed < 4 else 3
                    elif token.category == 'manager':
                        # Managers rate slightly lower but fair (3-4, occasional 5)
                        if question_seed < 2:
                            rating = 3
                        elif question_seed < 8:
                            rating = 4
                        else:
                            rating = 5
                    elif token.category == 'peer':
                        # Peers rate high (4-5, mostly 4s)
                        rating = 4 if question_seed < 7 else 5
                    elif token.category == 'direct_report':
                        # Direct reports rate highest (4-5, mostly 5s)
                        rating = 5 if question_seed < 7 else 4
                    else:
                        rating = 4

                    answer_data = {'value': rating}

                elif question.question_type == 'scale':
                    # Scale questions (e.g., 1-100)
                    config = question.config or {}
                    min_val = config.get('min', 1)
                    max_val = config.get('max', 100)
                    scale_range = max_val - min_val

                    if token.category == 'self':
                        # Self rates lower (40-60% of range)
                        scale_value = min_val + int(scale_range * (0.4 + (question_seed / 50)))
                    elif token.category == 'manager':
                        # Managers rate 60-80% of range
                        scale_value = min_val + int(scale_range * (0.6 + (question_seed / 50)))
                    elif token.category == 'peer':
                        # Peers rate 70-90% of range
                        scale_value = min_val + int(scale_range * (0.7 + (question_seed / 50)))
                    elif token.category == 'direct_report':
                        # Direct reports rate highest (75-95% of range)
                        scale_value = min_val + int(scale_range * (0.75 + (question_seed / 50)))
                    else:
                        scale_value = min_val + int(scale_range * 0.7)

                    answer_data = {'value': scale_value}

                elif question.question_type == 'single_choice':
                    # Single choice questions - select based on weights if available
                    config = question.config or {}
                    choices = config.get('choices', [])
                    weights = config.get('weights', [])

                    if choices:
                        if weights and config.get('scoring_enabled'):
                            # Select higher weighted options based on category
                            if token.category == 'self':
                                # Self selects lower weighted options
                                idx = min(len(choices) - 1, max(0, question_seed % max(1, len(choices) // 2)))
                            elif token.category in ['peer', 'direct_report']:
                                # Peers/reports select higher weighted options
                                idx = max(0, len(choices) - 1 - (question_seed % max(1, len(choices) // 2)))
                            else:
                                # Managers select middle to high
                                idx = max(0, len(choices) // 2 + (question_seed % max(1, len(choices) // 2)))
                        else:
                            # Random selection
                            idx = question_seed % len(choices)
                        answer_data = {'value': choices[idx]}
                    else:
                        answer_data = {'value': ''}

                elif question.question_type == 'multiple_choice':
                    # Multiple choice questions - select multiple options
                    config = question.config or {}
                    choices = config.get('choices', [])

                    if choices:
                        # Select 1-3 options based on category
                        num_selections = 1 + (question_seed % 3)
                        if token.category == 'self':
                            # Self selects fewer options
                            num_selections = max(1, num_selections - 1)
                        elif token.category in ['peer', 'direct_report']:
                            # Peers/reports select more options
                            num_selections = min(len(choices), num_selections + 1)

                        # Select distinct options
                        selected = []
                        for i in range(min(num_selections, len(choices))):
                            idx = (question_seed + i * 7) % len(choices)
                            if choices[idx] not in selected:
                                selected.append(choices[idx])
                        answer_data = {'value': selected}
                    else:
                        answer_data = {'value': []}

                elif question.question_type == 'text':
                    # Add some text comments
                    if token.category != 'self' and hash(question.id) % 3 == 0:
                        comments = [
                            'Consistently delivers high-quality work and exceeds expectations.',
                            'Excellent communication skills and great team collaboration.',
                            'Shows strong technical expertise and helps others grow.',
                            'Could be more confident in presenting ideas to leadership.',
                        ]
                        answer_data = {'value': comments[hash(str(token.id) + str(question.id)) % len(comments)]}
                    else:
                        answer_data = {'value': ''}
                else:
                    answer_data = {'value': ''}

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
            self.stdout.write(self.style.SUCCESS(f'Generated report for {reviewee.name}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Could not generate report: {e}'))

        return cycle

    def _create_partial_cycle(self, reviewee, questionnaire, admin_user, completion_pct):
        """Create a partially completed cycle"""
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=admin_user,
            status='active'
        )

        total_tokens = 10
        completed_tokens = int(total_tokens * completion_pct / 100)

        # Create tokens
        categories = ['self'] + ['manager'] * 3 + ['peer'] * 4 + ['direct_report'] * 2

        for i, category in enumerate(categories):
            if i < completed_tokens:
                # Completed
                token = ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=timezone.now() - timedelta(days=10),
                    completed_at=timezone.now() - timedelta(days=5)
                )
                # Add responses
                questions = list(Question.objects.filter(
                    section__questionnaire=questionnaire
                ).order_by('section__order', 'order'))

                for question in questions:
                    if question.question_type in ['rating', 'likert']:
                        answer_data = {'value': 4}
                    elif question.question_type == 'scale':
                        config = question.config or {}
                        min_val = config.get('min', 1)
                        max_val = config.get('max', 100)
                        scale_range = max_val - min_val
                        answer_data = {'value': min_val + int(scale_range * 0.7)}
                    elif question.question_type == 'single_choice':
                        config = question.config or {}
                        choices = config.get('choices', [])
                        if choices:
                            answer_data = {'value': choices[len(choices) // 2]}
                        else:
                            answer_data = {'value': ''}
                    elif question.question_type == 'multiple_choice':
                        config = question.config or {}
                        choices = config.get('choices', [])
                        if choices:
                            # Select 2 options from middle
                            selected = [choices[i] for i in range(min(2, len(choices)))]
                            answer_data = {'value': selected}
                        else:
                            answer_data = {'value': []}
                    else:
                        answer_data = {'value': ''}

                    Response.objects.create(
                        cycle=cycle,
                        question=question,
                        token=token,
                        category=category,
                        answer_data=answer_data
                    )
            elif i < completed_tokens + 2:
                # Claimed but not completed
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=timezone.now() - timedelta(days=3)
                )
            else:
                # Not claimed
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4()
                )

        return cycle

    def _create_new_cycle(self, reviewee, questionnaire, admin_user, claim_pct):
        """Create a newly created cycle with high claim rate but low completion"""
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=admin_user,
            status='active'
        )

        total_tokens = 10
        claimed_tokens = int(total_tokens * claim_pct / 100)

        categories = ['self'] + ['manager'] * 3 + ['peer'] * 4 + ['direct_report'] * 2

        for i, category in enumerate(categories):
            if i < claimed_tokens:
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4(),
                    claimed_at=timezone.now() - timedelta(days=1)
                )
            else:
                ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    token=uuid.uuid4()
                )

        return cycle
