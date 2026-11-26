"""
Dreyfus Model of Skill Acquisition Service

This module provides functions to calculate and analyze skill levels based on the
Dreyfus model of skill acquisition. It supports both linear (5-stage) and 2D
(skill × agency) models.

References:
- Dreyfus, S. E., & Dreyfus, H. L. (1980). A Five-Stage Model of the Mental Activities
  Involved in Directed Skill Acquisition. Operations Research Center, UC Berkeley.
"""

from statistics import mean
from typing import Dict, List, Optional

from django.utils.translation import gettext, gettext_lazy as _

from .scoring import score_on_five


# Dreyfus stage definitions
DREYFUS_STAGES = {
    1: {
        'key': 'novice',
        'name': _('Novice'),
        'short_description': _('Rigid rule follower'),
        'description': _('Follows rules rigidly, needs detailed instructions and close guidance'),
        'traits': [
            _('Requires step-by-step instructions'),
            _('Follows rules without understanding context'),
            _('Needs close supervision'),
            _('Limited ability to recognize patterns'),
            _('Task-focused rather than goal-focused')
        ],
        'behaviors': [
            _('Asks for detailed procedures'),
            _('Struggles with unexpected situations'),
            _('Focuses on individual steps'),
            _('Needs explicit direction for each task')
        ]
    },
    2: {
        'key': 'advanced_beginner',
        'name': _('Advanced Beginner'),
        'short_description': _('Recognizes patterns, needs guidelines'),
        'description': _('Can handle simple tasks independently, recognizes recurring patterns'),
        'traits': [
            _('Recognizes situational patterns'),
            _('Handles routine tasks independently'),
            _('Needs guidelines for non-standard situations'),
            _('Starts to see similarities across problems'),
            _('Still struggles with complex decisions')
        ],
        'behaviors': [
            _('Can work independently on familiar tasks'),
            _('Asks for guidance on edge cases'),
            _('Identifies when something looks wrong'),
            _('Follows established patterns')
        ]
    },
    3: {
        'key': 'competent',
        'name': _('Competent'),
        'short_description': _('Develops mental models, takes responsibility'),
        'description': _('Plans deliberately, solves standard problems, takes ownership'),
        'traits': [
            _('Creates mental models of the domain'),
            _('Plans work deliberately'),
            _('Takes responsibility for outcomes'),
            _('Solves standard problems independently'),
            _('Makes conscious, reasoned decisions')
        ],
        'behaviors': [
            _('Troubleshoots problems systematically'),
            _('Prioritizes and plans work'),
            _('Takes ownership of results'),
            _('Follows through on commitments')
        ]
    },
    4: {
        'key': 'proficient',
        'name': _('Proficient'),
        'short_description': _('Sees the big picture, learns from others'),
        'description': _('Sees the big picture, recognizes patterns quickly, handles complexity'),
        'traits': [
            _('Sees the big picture and context'),
            _('Recognizes patterns and deviations quickly'),
            _('Learns from others experiences'),
            _('Handles complex situations effectively'),
            _('Knows when to break the rules')
        ],
        'behaviors': [
            _('Quickly identifies root causes'),
            _('Anticipates problems before they occur'),
            _('Adapts approaches to context'),
            _('Mentors less experienced team members')
        ]
    },
    5: {
        'key': 'expert',
        'name': _('Expert'),
        'short_description': _('Intuitive, creates new approaches'),
        'description': _('Works from intuition, creates novel solutions, recognized authority'),
        'traits': [
            _('Works from intuition and deep understanding'),
            _('Creates new approaches and solutions'),
            _('Recognized as domain authority'),
            _('Sees possibilities others miss'),
            _('Operates at a transcendent level')
        ],
        'behaviors': [
            _('Solves problems others cannot'),
            _('Innovates and creates best practices'),
            _('Trusted for most difficult challenges'),
            _('Shapes the direction of the field')
        ]
    }
}

# Agency/Initiative stage definitions
AGENCY_STAGES = {
    1: {
        'name': _('Directed'),
        'description': _('Waits for explicit instructions and direction')
    },
    2: {
        'name': _('Assisted'),
        'description': _('Takes initiative when prompted or guided')
    },
    3: {
        'name': _('Independent'),
        'description': _('Proactively identifies and addresses problems')
    },
    4: {
        'name': _('Proactive'),
        'description': _('Regularly proposes improvements and drives change')
    },
    5: {
        'name': _('Self-Driven'),
        'description': _('Self-directed achiever who consistently improves systems')
    }
}

# Quadrant definitions (Skill × Agency)
QUADRANTS = {
    'developing_contributor': {
        'name': _('Developing Contributor'),
        'skill_range': (1, 2.5),
        'agency_range': (1, 2.5),
        'description': _('Building foundational skills and learning to work independently'),
        'characteristics': [
            _('Early in career or role'),
            _('Requires guidance and support'),
            _('Building fundamental capabilities'),
            _('Needs structured development')
        ],
        'development_path': _(
            'Focus on building core skills through deliberate practice and seeking guidance. '
            'Work on taking more initiative on familiar tasks.'
        ),
    },
    'hungry_learner': {
        'name': _('Hungry Learner'),
        'skill_range': (1, 2.5),
        'agency_range': (2.5, 5),
        'description': _('High initiative but developing expertise - eager to learn and contribute'),
        'characteristics': [
            _('Strong drive and motivation'),
            _('Seeks opportunities to grow'),
            _('May overcommit without experience'),
            _('Benefits from mentorship')
        ],
        'development_path': _(
            'Channel your energy into deliberate skill development. Seek mentorship from experts. '
            'Balance enthusiasm with building depth.'
        ),
    },
    'specialist': {
        'name': _('Specialist'),
        'skill_range': (2.5, 5),
        'agency_range': (1, 2.5),
        'description': _('Deep expertise but waits for direction - valuable contributor when engaged'),
        'characteristics': [
            _('Strong technical capabilities'),
            _('Reliable when given clear objectives'),
            _('Prefers depth over breadth'),
            _('May need encouragement to lead')
        ],
        'development_path': _(
            'Build confidence in taking initiative. Start with small ownership opportunities. '
            'Share your expertise proactively.'
        ),
    },
    'force_multiplier': {
        'name': _('Force Multiplier'),
        'skill_range': (2.5, 5),
        'agency_range': (2.5, 5),
        'description': _('High skill and high initiative - drives team success and innovation'),
        'characteristics': [
            _('Combines expertise with initiative'),
            _('Mentors and elevates others'),
            _('Drives meaningful improvements'),
            _('Trusted for complex challenges')
        ],
        'development_path': _(
            'Continue expanding your impact. Focus on strategic initiatives and developing others. '
            'Consider broader leadership roles.'
        ),
    }
}


# Development recommendations by skill stage
PRIMARY_FOCUS = {
    1: _('Build foundational skills through deliberate practice and close guidance from experienced mentors.'),
    2: _('Develop deeper pattern recognition and start building mental models of your domain.'),
    3: _('Expand your perspective to see the bigger picture and learn from diverse experiences.'),
    4: _('Deepen intuition through extensive practice and begin creating novel approaches.'),
    5: _('Continue innovating and sharing your expertise to advance the field.'),
}

EARLY_QUICK_WINS = [
    _('Seek feedback on your work early and often'),
    _('Study examples of good work in your domain'),
    _('Practice deliberate problem-solving with guidance'),
]

COMPETENT_QUICK_WINS = [
    _('Take ownership of a complete project or feature'),
    _('Learn from colleagues at different skill levels'),
    _('Document your decision-making process'),
]

ADVANCED_QUICK_WINS = [
    _('Mentor someone less experienced'),
    _('Share your knowledge through documentation or talks'),
    _('Tackle a novel problem in your domain'),
]

EARLY_RESOURCES = [
    _('Structured learning programs or courses'),
    _('Regular mentorship sessions'),
    _('Code reviews and pair programming'),
]

COMPETENT_RESOURCES = [
    _('Cross-functional projects'),
    _('Technical leadership opportunities'),
    _('Industry conferences and communities'),
]

ADVANCED_RESOURCES = [
    _('Research and innovation projects'),
    _('Teaching and mentoring opportunities'),
    _('Speaking at conferences or writing articles'),
]

AGENCY_HINTS = {
    'take_initiative': _('Take more initiative on projects - your skills are ready for more ownership'),
    'deepen_expertise': _('Focus on deepening your technical expertise to match your initiative'),
}


def calculate_dreyfus_level(report_data: Dict, questionnaire_id: Optional[int] = None) -> Optional[Dict]:
    """
    Calculate Dreyfus skill level from weighted question responses.

    This function looks for questions tagged with 'dreyfus_mapping' metadata
    in their config. Without such questions there is no skill level.

    Args:
        report_data: The complete report data structure with responses
        questionnaire_id: Optional questionnaire ID for logging

    Returns:
        Dictionary with:
        - skill_level: Float 1-5 representing overall skill level
        - stage: Number of the Dreyfus stage (1-5), see skill_profile_with_texts() for its texts
        - confidence: Float 0-1 indicating calculation confidence
        - contributing_questions: List of question IDs that contributed
        or None if insufficient data
    """
    weighted_scores = []
    contributing_questions = []

    # Try metadata-based calculation first
    for section_data in report_data.get('by_section', {}).values():
        for question_id, question_data in section_data.get('questions', {}).items():
            # Look for Dreyfus mapping in question metadata
            # Note: report_data stores config as 'question_config'
            config = question_data.get('question_config') or question_data.get('config', {})
            dreyfus_mapping = config.get('dreyfus_mapping', {}) if config else {}

            # Support both old format: {"dimension": "skill", "weight": 1.0}
            # and new format: {"skill": 1.5} or {"skill": 1.0, "agency": 0.5}
            weight = None
            if dreyfus_mapping:
                # Check new format first
                if 'skill' in dreyfus_mapping:
                    weight = dreyfus_mapping['skill']
                # Fall back to old format for backward compatibility
                elif dreyfus_mapping.get('dimension') == 'skill':
                    weight = dreyfus_mapping.get('weight', 1.0)

            if weight:
                # Get average score across all categories (prefer non-self, but allow self if only option)
                category_scores = []
                self_score = None

                for category, cat_data in question_data.get('by_category', {}).items():
                    # Check for avg (report_data format) or average (alternative format)
                    # An average of 0 is a real score (the lowest of a slider from 0), so only a missing one falls back
                    avg_score = cat_data.get('avg')
                    if avg_score is None:
                        avg_score = cat_data.get('average')
                    if avg_score is not None and not cat_data.get('insufficient', False):
                        avg_score = score_on_five(question_data, avg_score)
                        # The 1 to 5 scale has no 0: a 0 here comes from a question without a range, such as a Pick
                        # question whose every score is 0, which counts toward no level (see Scoring.nonzero)
                        if not avg_score:
                            continue
                        if category == 'self':
                            # Store self score separately as fallback
                            self_score = avg_score
                        else:
                            # Use non-self scores preferentially
                            category_scores.append(avg_score)

                # If no non-self scores but we have self-assessment, use it
                if not category_scores and self_score is not None:
                    category_scores.append(self_score)

                if category_scores:
                    avg_score = mean(category_scores)
                    weighted_scores.append((avg_score, weight))
                    contributing_questions.append(question_id)

    # If we found metadata-based scores, use them
    if weighted_scores:
        # Calculate weighted average
        total_weight = sum(weight for score, weight in weighted_scores)
        if total_weight > 0:
            skill_level = sum(score * weight for score, weight in weighted_scores) / total_weight
        else:
            skill_level = mean(score for score, weight in weighted_scores)

        # Confidence based on number of contributing questions and total weight
        confidence = min(1.0, (len(contributing_questions) / 5.0) * (total_weight / 3.0))

    else:
        return None

    return {
        'skill_level': round(skill_level, 2),
        'stage': _level_to_stage(skill_level),
        'confidence': round(confidence, 2),
        'contributing_questions': contributing_questions,
    }


def calculate_agency_level(report_data: Dict, questionnaire_id: Optional[int] = None) -> Optional[Dict]:
    """
    Calculate agency/initiative level from weighted question responses.

    Args:
        report_data: The complete report data structure with responses
        questionnaire_id: Optional questionnaire ID for logging

    Returns:
        Dictionary with:
        - agency_level: Float 1-5 representing initiative/autonomy level
        - stage: Number of the agency stage (1-5), see agency_profile_with_texts() for its texts
        - confidence: Float 0-1 indicating calculation confidence
        - contributing_questions: List of question IDs that contributed
        or None if insufficient data
    """
    weighted_scores = []
    contributing_questions = []

    # Look for questions with agency dimension
    for section_data in report_data.get('by_section', {}).values():
        for question_id, question_data in section_data.get('questions', {}).items():
            # Note: report_data stores config as 'question_config'
            config = question_data.get('question_config') or question_data.get('config', {})
            dreyfus_mapping = config.get('dreyfus_mapping', {}) if config else {}

            # Support both old format: {"dimension": "agency", "weight": 1.0}
            # and new format: {"agency": 1.5} or {"skill": 1.0, "agency": 0.5}
            weight = None
            if dreyfus_mapping:
                # Check new format first
                if 'agency' in dreyfus_mapping:
                    weight = dreyfus_mapping['agency']
                # Fall back to old format for backward compatibility
                elif dreyfus_mapping.get('dimension') == 'agency':
                    weight = dreyfus_mapping.get('weight', 1.0)

            if weight:
                # Get average score across all categories (prefer non-self, but allow self if only option)
                category_scores = []
                self_score = None

                for category, cat_data in question_data.get('by_category', {}).items():
                    # Check for avg (report_data format) or average (alternative format)
                    # An average of 0 is a real score (the lowest of a slider from 0), so only a missing one falls back
                    avg_score = cat_data.get('avg')
                    if avg_score is None:
                        avg_score = cat_data.get('average')
                    if avg_score is not None and not cat_data.get('insufficient', False):
                        avg_score = score_on_five(question_data, avg_score)
                        # The 1 to 5 scale has no 0: a 0 here comes from a question without a range, such as a Pick
                        # question whose every score is 0, which counts toward no level (see Scoring.nonzero)
                        if not avg_score:
                            continue
                        if category == 'self':
                            # Store self score separately as fallback
                            self_score = avg_score
                        else:
                            # Use non-self scores preferentially
                            category_scores.append(avg_score)

                # If no non-self scores but we have self-assessment, use it
                if not category_scores and self_score is not None:
                    category_scores.append(self_score)

                if category_scores:
                    avg_score = mean(category_scores)
                    weighted_scores.append((avg_score, weight))
                    contributing_questions.append(question_id)

    if not weighted_scores:
        return None

    # Calculate weighted average
    total_weight = sum(weight for score, weight in weighted_scores)
    if total_weight > 0:
        agency_level = sum(score * weight for score, weight in weighted_scores) / total_weight
    else:
        agency_level = mean(score for score, weight in weighted_scores)

    # Confidence based on number of questions and weight
    confidence = min(1.0, (len(contributing_questions) / 3.0) * (total_weight / 2.0))

    return {
        'agency_level': round(agency_level, 2),
        'stage': _level_to_stage(agency_level),
        'confidence': round(confidence, 2),
        'contributing_questions': contributing_questions,
    }


def calculate_dreyfus_quadrant(skill_level: float, agency_level: float) -> Dict:
    """
    Map skill and agency levels to organizational quadrant.

    Args:
        skill_level: Skill level (1-5)
        agency_level: Agency level (1-5)

    Returns:
        Dictionary with the quadrant's key and both levels, see quadrant_with_texts() for its texts
    """
    # Determine quadrant based on threshold (2.5)
    if skill_level < 2.5 and agency_level < 2.5:
        quadrant_key = 'developing_contributor'
    elif skill_level < 2.5 and agency_level >= 2.5:
        quadrant_key = 'hungry_learner'
    elif skill_level >= 2.5 and agency_level < 2.5:
        quadrant_key = 'specialist'
    else:
        quadrant_key = 'force_multiplier'

    return {
        'quadrant_key': quadrant_key,
        'skill_level': round(skill_level, 2),
        'agency_level': round(agency_level, 2),
    }


def get_dreyfus_traits(stage_num: int, detailed: bool = True) -> Dict:
    """
    Get traits and characteristics for a Dreyfus stage.

    Args:
        stage_num: Stage number (1-5)
        detailed: If True, include behaviors and full descriptions

    Returns:
        Dictionary with stage information
    """
    if stage_num not in DREYFUS_STAGES:
        raise ValueError(f"Invalid stage number: {stage_num}. Must be 1-5.")

    stage_info = DREYFUS_STAGES[stage_num].copy()

    if not detailed:
        # Return minimal info
        return {
            'stage': stage_info['name'],
            'description': stage_info['short_description']
        }

    return stage_info


def generate_development_recommendations(
    skill_profile: Optional[Dict],
    agency_profile: Optional[Dict],
    report_data: Dict
) -> Dict:
    """
    Generate personalized development recommendations based on:
    - Current skill/agency levels
    - Question-specific action items (hybrid approach)

    Args:
        skill_profile: Output from calculate_dreyfus_level()
        agency_profile: Output from calculate_agency_level()
        report_data: Full report data for context

    Returns:
        Dictionary with:
        - agency_hint: 'take_initiative' or 'deepen_expertise' when skill and agency lie more than half a level apart
        - action_items: Action items of low-scoring questions as {'question_id', 'key', 'text'}
        The stage-based recommendations follow from the skill stage, see development_plan_with_texts().
    """
    recommendations = {
        'agency_hint': None,
        'action_items': [],
    }

    if not skill_profile:
        return recommendations

    # HYBRID APPROACH: Add personalized action items based on question scores
    recommendations['action_items'] = _get_personalized_action_items(report_data, skill_profile['stage'])

    # Factor in agency if available
    if agency_profile:
        agency_level = agency_profile['agency_level']
        skill_level = skill_profile['skill_level']

        # If agency is lagging behind skill
        if agency_level < skill_level - 0.5:
            recommendations['agency_hint'] = 'take_initiative'

        # If skill is lagging behind agency
        elif skill_level < agency_level - 0.5:
            recommendations['agency_hint'] = 'deepen_expertise'

    return recommendations


def stage_texts(stage: int) -> Dict:
    """The texts of a Dreyfus stage and of what the next stage takes, in the active language."""

    info = DREYFUS_STAGES[stage]
    texts = {
        'name': str(info['name']),
        'short_description': str(info['short_description']),
        'description': str(info['description']),
        'traits': [str(trait) for trait in info['traits']],
        'behaviors': [str(behavior) for behavior in info['behaviors']],
    }
    next_stage = min(5, stage + 1)

    if next_stage > stage:
        texts['next_stage'] = str(DREYFUS_STAGES[next_stage]['name'])
        texts['development_focus'] = [str(focus) for focus in _get_development_focus(stage, next_stage)]
    else:
        texts['next_stage'] = None
        texts['development_focus'] = [gettext('Continue deepening expertise and innovating')]

    return texts


def skill_profile_with_texts(profile: Dict) -> Dict:
    """A skill profile from calculate_dreyfus_level() with the texts of its stage."""

    stage_info = stage_texts(profile['stage'])

    return {
        **profile,
        'skill_stage': stage_info['name'],
        'stage_key': DREYFUS_STAGES[profile['stage']]['key'],
        'stage_info': stage_info,
    }


def agency_profile_with_texts(profile: Dict) -> Dict:
    """An agency profile from calculate_agency_level() with the texts of its stage."""

    info = AGENCY_STAGES[profile['stage']]

    return {
        **profile,
        'agency_stage': str(info['name']),
        'description': str(info['description']),
    }


def quadrant_with_texts(quadrant: Dict) -> Dict:
    """A quadrant from calculate_dreyfus_quadrant() with its texts."""

    info = QUADRANTS[quadrant['quadrant_key']]

    return {
        **quadrant,
        'name': str(info['name']),
        'description': str(info['description']),
        'characteristics': [str(characteristic) for characteristic in info['characteristics']],
        'development_path': str(info['development_path']),
        'skill_range': info['skill_range'],
        'agency_range': info['agency_range'],
    }


def development_plan_with_texts(plan: Dict, skill_profile: Dict) -> Dict:
    """A plan from generate_development_recommendations() with its recommendations in the active language."""

    stage = skill_profile['stage']
    next_stage = min(5, stage + 1)
    next_stage_info = DREYFUS_STAGES[next_stage]

    if stage < 3:
        quick_wins, resources = EARLY_QUICK_WINS, EARLY_RESOURCES
    elif stage == 3:
        quick_wins, resources = COMPETENT_QUICK_WINS, COMPETENT_RESOURCES
    else:
        quick_wins, resources = ADVANCED_QUICK_WINS, ADVANCED_RESOURCES

    actions = [action['text'] for action in plan['action_items']]
    quick_wins = actions + [str(quick_win) for quick_win in quick_wins]

    if hint := plan.get('agency_hint'):
        quick_wins.insert(0, str(AGENCY_HINTS[hint]))

    next_capabilities = gettext('Develop capabilities of a %(stage)s: %(description)s') % {
        'stage': next_stage_info['name'],
        'description': next_stage_info['short_description'],
    }

    return {
        **plan,
        'primary_focus': str(PRIMARY_FOCUS[stage]),
        'quick_wins': quick_wins,
        'long_term_goals': [
            next_capabilities,
            gettext('Build experience across diverse situations'),
            gettext('Continuously reflect on your practice and learning'),
        ],
        'resources': [str(resource) for resource in resources],
        'next_level_requirements': stage_texts(stage)['development_focus'],
    }


# Helper functions

def _get_personalized_action_items(report_data: Dict, current_stage: int) -> List[Dict]:
    """
    Extract personalized action items based on question scores and current Dreyfus stage.

    This implements the hybrid approach:
    - Generic stage-based recommendations (already in quick_wins)
    - Question-specific action items for low-scoring areas

    Args:
        report_data: Full report data with question scores
        current_stage: Current Dreyfus stage (1-5)

    Returns:
        List of personalized action items as {'question_id', 'key', 'text'}
    """
    from questionnaires.models import Question
    from statistics import mean

    personalized_actions = []
    question_scores = {}  # question_id -> avg_score

    # Extract question scores from report_data (exclude self-assessment)
    for section_data in report_data.get('by_section', {}).values():
        for question_id, question_data in section_data.get('questions', {}).items():
            category_scores = []
            for category, cat_data in question_data.get('by_category', {}).items():
                # Skip self-assessment
                if category == 'self':
                    continue
                # An average of 0 is a real score (the lowest of a slider from 0), so only a missing one falls back
                avg_score = cat_data.get('avg')
                if avg_score is None:
                    avg_score = cat_data.get('average')
                if avg_score is not None and not cat_data.get('insufficient', False):
                    # A 0 on the 1 to 5 scale is a question without a range, as in the level functions above
                    if score := score_on_five(question_data, avg_score):
                        category_scores.append(score)

            if category_scores:
                question_scores[str(question_id)] = mean(category_scores)

    if not question_scores:
        return personalized_actions

    # Load questions with action items from database
    question_ids = [int(qid) for qid in question_scores.keys()]
    questions = Question.objects.filter(id__in=question_ids).only('id', 'action_items')

    # Process each question's action items
    for question in questions:
        qid = str(question.id)
        score = question_scores.get(qid)

        if not score or not question.action_items:
            continue

        # Check each action item
        for action_item in question.action_items:
            if not isinstance(action_item, dict):
                continue

            text = action_item.get('text')
            threshold = action_item.get('threshold', 3.0)  # Default threshold
            stages = action_item.get('stages')  # Optional: [1, 2, 3]

            if not text:
                continue

            # Check if action item applies
            # 1. Score is below threshold
            if score >= threshold:
                continue

            # 2. If stages specified, check if current stage is in list
            if stages and current_stage not in stages:
                continue

            # Add the action item
            personalized_actions.append({'question_id': question.id, 'key': action_item.get('key'), 'text': text})

    # Limit to top 5 most relevant action items
    return personalized_actions[:5]


def _level_to_stage(level: float) -> int:
    """Convert continuous level (1.0-5.0) to discrete stage (1-5)."""
    return max(1, min(5, int(level + 0.5)))


def _get_development_focus(current_stage: int, next_stage: int) -> List[str]:
    """Get what's needed to progress from current to next stage."""
    focus_areas = {
        (1, 2): [
            _('Recognize recurring patterns in your work'),
            _('Handle routine tasks independently'),
            _('Build situational awareness beyond just following rules')
        ],
        (2, 3): [
            _('Develop mental models of how things work'),
            _('Take responsibility for outcomes, not just tasks'),
            _('Plan and prioritize work deliberately')
        ],
        (3, 4): [
            _('See the big picture and system context'),
            _('Learn from others\' experiences, not just your own'),
            _('Recognize patterns and deviations quickly')
        ],
        (4, 5): [
            _('Trust your intuition based on deep experience'),
            _('Create novel approaches and solutions'),
            _('Become a recognized authority in your domain')
        ]
    }
    return focus_areas.get((current_stage, next_stage), [_('Continue developing expertise')])
