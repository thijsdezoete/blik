"""
Management command to generate optimized demo data specifically for screenshots.
Creates a single organization with carefully crafted data for visual appeal.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounts.models import Reviewee, UserProfile
from accounts.permissions import assign_organization_admin, assign_organization_member
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
        admin = User.objects.create_user(
            username='admin_acme',
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
        self.stdout.write(self.style.SUCCESS(f'Created admin user: {admin.username} (password: demo123)'))

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
            user = User.objects.create_user(
                username=email.split('@')[0],
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
            'admin_username': 'admin_acme',
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

        # Create tokens: 1 self, 1 manager, 4 peers, 2 direct reports = 8 total
        token_configs = [
            ('self', 1),
            ('manager', 1),
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

        # Create responses with "imposter syndrome" pattern for visual gap in charts
        for token in tokens:
            for question in questions:
                if question.question_type in ['rating', 'likert']:
                    # Self rates lower (2-3), others rate higher (4-5)
                    if token.category == 'self':
                        rating = 2 if hash(question.id) % 3 == 0 else 3
                    else:
                        rating = 4 if hash(question.id) % 2 == 0 else 5

                    answer_data = {'value': rating}
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

        total_tokens = 8
        completed_tokens = int(total_tokens * completion_pct / 100)

        # Create tokens
        categories = ['self', 'manager'] + ['peer'] * 4 + ['direct_report'] * 2

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

        total_tokens = 8
        claimed_tokens = int(total_tokens * claim_pct / 100)

        categories = ['self', 'manager'] + ['peer'] * 4 + ['direct_report'] * 2

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
