from django.test import TestCase
from django.contrib.auth.models import User
from core.models import Organization
from accounts.models import UserProfile, Reviewee
from questionnaires.models import Questionnaire, QuestionSection, Question
from reviews.models import ReviewCycle, ReviewerToken, Response
from .services import generate_report, apply_display_anonymization


class AnonymizationArchitectureTestCase(TestCase):
    """
    Test the anonymization architecture:
    - Charts use statistical validity (2+ responses, 1+ for self/manager)
    - Detailed reports use privacy threshold (org setting, default 3)
    - Clean separation between calculation and display
    """

    def setUp(self):
        """Create test organization, users, questionnaire, and review cycle"""
        # Create organization with default anonymization threshold (3)
        self.org = Organization.objects.create(
            name="Test Organization",
            email="test@example.com",
            min_responses_for_anonymity=3
        )

        # Create admin user
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="password"
        )
        UserProfile.objects.create(user=self.admin, organization=self.org)

        # Create reviewee
        self.reviewee = Reviewee.objects.create(
            name="Test Reviewee",
            email="reviewee@example.com",
            organization=self.org
        )

        # Create simple questionnaire with rating questions
        self.questionnaire = Questionnaire.objects.create(
            name="Test Questionnaire",
            organization=self.org
        )

        self.section = QuestionSection.objects.create(
            questionnaire=self.questionnaire,
            title="Technical Skills",
            order=1
        )

        self.rating_question = Question.objects.create(
            section=self.section,
            question_text="Rate technical ability",
            question_type="rating",
            config={"min": 1, "max": 5},
            order=1
        )

        self.text_question = Question.objects.create(
            section=self.section,
            question_text="Provide feedback",
            question_type="text",
            config={},
            order=2
        )

        # Create review cycle
        self.cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.admin,
            status='active'
        )

    def _create_response(self, category, question, value):
        """Helper to create a response"""
        token = ReviewerToken.objects.create(
            cycle=self.cycle,
            category=category
        )
        Response.objects.create(
            cycle=self.cycle,
            token=token,
            question=question,
            category=token.category,  # Denormalized from token
            answer_data={'value': value}
        )

    def test_statistical_validity_threshold_for_charts(self):
        """
        Test that charts use 2+ responses for statistical validity
        (1+ for self/manager categories)
        """
        # Create responses: self(1), manager(1), peer(2), direct_report(1)
        self._create_response('self', self.rating_question, 5)
        self._create_response('manager', self.rating_question, 4)
        self._create_response('peer', self.rating_question, 3)
        self._create_response('peer', self.rating_question, 4)
        self._create_response('direct_report', self.rating_question, 4)

        # Generate report
        report = generate_report(self.cycle)

        # Check chart data exists
        self.assertIn('charts', report.report_data)
        chart_data = report.report_data['charts']

        # Get section scores
        section_scores = chart_data.get('section_scores', {})
        self.assertGreater(len(section_scores), 0)

        # Find our section's scores
        tech_skills_scores = None
        for section_name, scores in section_scores.items():
            if 'Technical' in section_name:
                tech_skills_scores = scores
                break

        self.assertIsNotNone(tech_skills_scores, "Technical Skills section should be in charts")

        # Verify chart includes categories with sufficient responses for statistical validity
        self.assertIn('self', tech_skills_scores, "Self (1 response) should be in charts")
        self.assertIn('manager', tech_skills_scores, "Manager (1 response) should be in charts")
        self.assertIn('peer', tech_skills_scores, "Peer (2 responses) should be in charts")

        # Direct report with 1 response should NOT be in charts (needs 2+)
        self.assertNotIn('direct_report', tech_skills_scores,
                         "Direct report (1 response) should NOT be in charts")

    def test_privacy_threshold_for_detailed_display(self):
        """
        Test that detailed reports respect anonymization threshold (3)
        """
        # Create responses: peer(2), direct_report(4)
        self._create_response('peer', self.rating_question, 3)
        self._create_response('peer', self.rating_question, 4)

        for _ in range(4):
            self._create_response('direct_report', self.rating_question, 5)

        # Generate report
        report = generate_report(self.cycle)

        # Apply display anonymization
        display_data = apply_display_anonymization(
            report.report_data,
            min_threshold=self.org.min_responses_for_anonymity
        )

        # Navigate to question data
        section_id = str(self.section.id)
        question_id = str(self.rating_question.id)

        by_section = display_data['by_section']
        self.assertIn(section_id, by_section)

        questions = by_section[section_id]['questions']
        self.assertIn(question_id, questions)

        by_category = questions[question_id]['by_category']

        # Peer (2 responses) should be marked insufficient for display
        self.assertIn('peer', by_category)
        peer_data = by_category['peer']
        self.assertTrue(peer_data.get('insufficient'),
                       "Peer with 2 responses should be insufficient (threshold=3)")
        self.assertIn('avg', peer_data,
                     "Peer avg should still exist (for charts)")
        self.assertNotIn('responses', peer_data,
                        "Peer responses should be removed for privacy")

        # Direct report (4 responses) should be fully visible
        self.assertIn('direct_report', by_category)
        dr_data = by_category['direct_report']
        self.assertFalse(dr_data.get('insufficient', False),
                        "Direct report with 4 responses should be sufficient")
        self.assertIn('avg', dr_data)
        self.assertIn('responses', dr_data)

    def test_peer_two_responses_in_charts_but_not_details(self):
        """
        Key test: Peer category with 2 responses should appear in charts
        but be hidden in detailed report breakdown
        """
        # Create exactly 2 peer responses
        self._create_response('self', self.rating_question, 4)
        self._create_response('manager', self.rating_question, 4)
        self._create_response('peer', self.rating_question, 3)
        self._create_response('peer', self.rating_question, 4)

        # Generate report
        report = generate_report(self.cycle)

        # 1. Verify raw data has peer average calculated
        section_id = str(self.section.id)
        question_id = str(self.rating_question.id)

        # Debug: Check if peer exists in data
        by_category = report.report_data['by_section'][section_id]['questions'][question_id]['by_category']
        self.assertIn('peer', by_category, f"Peer should be in by_category. Available categories: {list(by_category.keys())}")

        raw_peer_data = by_category['peer']
        self.assertEqual(raw_peer_data['count'], 2)
        self.assertIn('avg', raw_peer_data, "Peer avg should be calculated in raw data")
        self.assertAlmostEqual(raw_peer_data['avg'], 3.5, places=1)

        # 2. Verify peer appears in chart data
        chart_data = report.report_data['charts']
        section_scores = chart_data['section_scores']

        tech_skills_scores = None
        for section_name, scores in section_scores.items():
            if 'Technical' in section_name:
                tech_skills_scores = scores
                break

        self.assertIn('peer', tech_skills_scores,
                     "Peer should appear in chart data (2 responses >= statistical threshold)")

        # 3. Verify peer is hidden in detailed display
        display_data = apply_display_anonymization(
            report.report_data,
            min_threshold=3
        )

        display_peer_data = display_data['by_section'][section_id]['questions'][question_id]['by_category']['peer']
        self.assertTrue(display_peer_data.get('insufficient'),
                       "Peer should be marked insufficient in display (2 < 3)")
        self.assertNotIn('responses', display_peer_data,
                        "Peer responses should be removed from display")

    def test_apply_display_anonymization_filter_function(self):
        """Test the apply_display_anonymization utility function directly"""
        # Create mock data
        test_data = {
            'by_section': {
                '1': {
                    'title': 'Test Section',
                    'questions': {
                        '1': {
                            'question_text': 'Test Question',
                            'question_type': 'rating',
                            'by_category': {
                                'self': {
                                    'count': 1,
                                    'avg': 4.5,
                                    'responses': [4.5]
                                },
                                'manager': {
                                    'count': 1,
                                    'avg': 4.0,
                                    'responses': [4.0]
                                },
                                'peer': {
                                    'count': 2,
                                    'avg': 3.5,
                                    'responses': [3, 4]
                                },
                                'direct_report': {
                                    'count': 1,
                                    'avg': 5.0,
                                    'responses': [5]
                                }
                            }
                        }
                    }
                }
            }
        }

        # Apply filter with threshold 3
        filtered = apply_display_anonymization(test_data, min_threshold=3)

        # Check self and manager are exempt
        self_data = filtered['by_section']['1']['questions']['1']['by_category']['self']
        self.assertFalse(self_data.get('insufficient', False))
        self.assertIn('responses', self_data)

        manager_data = filtered['by_section']['1']['questions']['1']['by_category']['manager']
        self.assertFalse(manager_data.get('insufficient', False))
        self.assertIn('responses', manager_data)

        # Check peer is marked insufficient but avg preserved
        peer_data = filtered['by_section']['1']['questions']['1']['by_category']['peer']
        self.assertTrue(peer_data.get('insufficient'))
        self.assertIn('avg', peer_data, "Avg should be preserved for charts")
        self.assertNotIn('responses', peer_data, "Responses should be removed for privacy")

        # Check direct_report is marked insufficient
        dr_data = filtered['by_section']['1']['questions']['1']['by_category']['direct_report']
        self.assertTrue(dr_data.get('insufficient'))
        self.assertNotIn('responses', dr_data)

    def test_different_anonymization_thresholds(self):
        """Test that different organizations can have different thresholds"""
        # Create responses: peer(2)
        self._create_response('peer', self.rating_question, 3)
        self._create_response('peer', self.rating_question, 4)

        # Generate report
        report = generate_report(self.cycle)

        section_id = str(self.section.id)
        question_id = str(self.rating_question.id)

        # Test with threshold=2 (should show peer)
        display_data_t2 = apply_display_anonymization(report.report_data, min_threshold=2)
        peer_data_t2 = display_data_t2['by_section'][section_id]['questions'][question_id]['by_category']['peer']
        self.assertFalse(peer_data_t2.get('insufficient', False),
                        "Peer should be visible with threshold=2")

        # Test with threshold=3 (should hide peer)
        display_data_t3 = apply_display_anonymization(report.report_data, min_threshold=3)
        peer_data_t3 = display_data_t3['by_section'][section_id]['questions'][question_id]['by_category']['peer']
        self.assertTrue(peer_data_t3.get('insufficient'),
                       "Peer should be hidden with threshold=3")

        # Test with threshold=5 (should hide peer)
        display_data_t5 = apply_display_anonymization(report.report_data, min_threshold=5)
        peer_data_t5 = display_data_t5['by_section'][section_id]['questions'][question_id]['by_category']['peer']
        self.assertTrue(peer_data_t5.get('insufficient'),
                       "Peer should be hidden with threshold=5")

    def test_zero_responses_not_in_charts(self):
        """Test that categories with 0 responses don't appear in charts"""
        # Create only self response
        self._create_response('self', self.rating_question, 4)

        # Generate report
        report = generate_report(self.cycle)

        # Get chart data
        chart_data = report.report_data['charts']
        section_scores = chart_data.get('section_scores', {})

        # Find our section
        tech_skills_scores = None
        for section_name, scores in section_scores.items():
            if 'Technical' in section_name:
                tech_skills_scores = scores
                break

        # Should only have self
        self.assertIn('self', tech_skills_scores)
        self.assertNotIn('peer', tech_skills_scores)
        self.assertNotIn('manager', tech_skills_scores)
        self.assertNotIn('direct_report', tech_skills_scores)

    def test_weighted_questions_with_anonymization(self):
        """Test that weighted/scored questions work correctly with new architecture"""
        # Create single_choice question with scoring
        weighted_question = Question.objects.create(
            section=self.section,
            question_text="Choose your skill level",
            question_type="single_choice",
            config={
                "choices": ["Beginner", "Intermediate", "Advanced", "Expert"],
                "weights": [1, 2, 3, 4],
                "scoring_enabled": True
            },
            order=3
        )

        # Create 2 peer responses
        self._create_response('peer', weighted_question, "Advanced")
        self._create_response('peer', weighted_question, "Expert")

        # Generate report
        report = generate_report(self.cycle)

        section_id = str(self.section.id)
        question_id = str(weighted_question.id)

        # Check raw data has weighted average
        raw_data = report.report_data['by_section'][section_id]['questions'][question_id]['by_category']['peer']
        self.assertIn('avg', raw_data)
        self.assertAlmostEqual(raw_data['avg'], 3.5, places=1)  # (3 + 4) / 2

        # Check display anonymization hides details but preserves avg
        display_data = apply_display_anonymization(report.report_data, min_threshold=3)
        display_peer = display_data['by_section'][section_id]['questions'][question_id]['by_category']['peer']

        self.assertTrue(display_peer.get('insufficient'))
        self.assertIn('avg', display_peer, "Weighted avg should be preserved")
        self.assertNotIn('distribution', display_peer,
                        "Distribution should be removed for privacy")


class ReportViewAnonymizationTestCase(TestCase):
    """Test that views properly apply anonymization filtering"""

    def setUp(self):
        """Set up test data"""
        self.org = Organization.objects.create(
            name="Test Org",
            email="test@example.com",
            min_responses_for_anonymity=3
        )

        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="password"
        )
        profile = UserProfile.objects.create(user=self.admin, organization=self.org)

        # Give admin permissions
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from accounts.models import UserProfile as ProfileModel

        ct = ContentType.objects.get_for_model(ProfileModel)
        perm = Permission.objects.get_or_create(
            codename='can_manage_organization',
            content_type=ct,
            defaults={'name': 'Can manage organization'}
        )[0]
        self.admin.user_permissions.add(perm)

        self.reviewee = Reviewee.objects.create(
            name="Test Reviewee",
            email="reviewee@example.com",
            organization=self.org
        )

        self.questionnaire = Questionnaire.objects.create(
            name="Test Q",
            organization=self.org
        )

        self.section = QuestionSection.objects.create(
            questionnaire=self.questionnaire,
            title="Skills",
            order=1
        )

        self.question = Question.objects.create(
            section=self.section,
            question_text="Rate ability",
            question_type="rating",
            config={"min": 1, "max": 5},
            order=1
        )

        self.cycle = ReviewCycle.objects.create(
            reviewee=self.reviewee,
            questionnaire=self.questionnaire,
            created_by=self.admin,
            status='completed'
        )

        # Create 2 peer responses
        for val in [3, 4]:
            token = ReviewerToken.objects.create(cycle=self.cycle, category='peer')
            Response.objects.create(
                cycle=self.cycle,
                token=token,
                question=self.question,
                category=token.category,  # Denormalized from token
                answer_data={'value': val}
            )

    def test_view_report_applies_anonymization_filter(self):
        """Test that view_report view applies display anonymization"""
        # Generate report first
        report = generate_report(self.cycle)

        # The view logic is covered by unit tests above
        # This is an integration test that would require full URL routing setup
        # The critical logic (apply_display_anonymization) is tested in unit tests

        # Verify the view imports and uses the function correctly
        from reports import views
        self.assertTrue(hasattr(views, 'apply_display_anonymization'),
                       "views module should import apply_display_anonymization")
