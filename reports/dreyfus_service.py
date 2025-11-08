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
from typing import Dict, List, Optional, Tuple


# Dreyfus stage definitions
DREYFUS_STAGES = {
    1: {
        'name': 'Novice',
        'short_description': 'Rigid rule follower',
        'description': 'Follows rules rigidly, needs detailed instructions and close guidance',
        'traits': [
            'Requires step-by-step instructions',
            'Follows rules without understanding context',
            'Needs close supervision',
            'Limited ability to recognize patterns',
            'Task-focused rather than goal-focused'
        ],
        'behaviors': [
            'Asks for detailed procedures',
            'Struggles with unexpected situations',
            'Focuses on individual steps',
            'Needs explicit direction for each task'
        ]
    },
    2: {
        'name': 'Advanced Beginner',
        'short_description': 'Recognizes patterns, needs guidelines',
        'description': 'Can handle simple tasks independently, recognizes recurring patterns',
        'traits': [
            'Recognizes situational patterns',
            'Handles routine tasks independently',
            'Needs guidelines for non-standard situations',
            'Starts to see similarities across problems',
            'Still struggles with complex decisions'
        ],
        'behaviors': [
            'Can work independently on familiar tasks',
            'Asks for guidance on edge cases',
            'Identifies when something looks wrong',
            'Follows established patterns'
        ]
    },
    3: {
        'name': 'Competent',
        'short_description': 'Develops mental models, takes responsibility',
        'description': 'Plans deliberately, solves standard problems, takes ownership',
        'traits': [
            'Creates mental models of the domain',
            'Plans work deliberately',
            'Takes responsibility for outcomes',
            'Solves standard problems independently',
            'Makes conscious, reasoned decisions'
        ],
        'behaviors': [
            'Troubleshoots problems systematically',
            'Prioritizes and plans work',
            'Takes ownership of results',
            'Follows through on commitments'
        ]
    },
    4: {
        'name': 'Proficient',
        'short_description': 'Sees the big picture, learns from others',
        'description': 'Sees the big picture, recognizes patterns quickly, handles complexity',
        'traits': [
            'Sees the big picture and context',
            'Recognizes patterns and deviations quickly',
            'Learns from others experiences',
            'Handles complex situations effectively',
            'Knows when to break the rules'
        ],
        'behaviors': [
            'Quickly identifies root causes',
            'Anticipates problems before they occur',
            'Adapts approaches to context',
            'Mentors less experienced team members'
        ]
    },
    5: {
        'name': 'Expert',
        'short_description': 'Intuitive, creates new approaches',
        'description': 'Works from intuition, creates novel solutions, recognized authority',
        'traits': [
            'Works from intuition and deep understanding',
            'Creates new approaches and solutions',
            'Recognized as domain authority',
            'Sees possibilities others miss',
            'Operates at a transcendent level'
        ],
        'behaviors': [
            'Solves problems others cannot',
            'Innovates and creates best practices',
            'Trusted for most difficult challenges',
            'Shapes the direction of the field'
        ]
    }
}

# Agency/Initiative stage definitions
AGENCY_STAGES = {
    1: {
        'name': 'Directed',
        'description': 'Waits for explicit instructions and direction'
    },
    2: {
        'name': 'Assisted',
        'description': 'Takes initiative when prompted or guided'
    },
    3: {
        'name': 'Independent',
        'description': 'Proactively identifies and addresses problems'
    },
    4: {
        'name': 'Proactive',
        'description': 'Regularly proposes improvements and drives change'
    },
    5: {
        'name': 'Self-Driven',
        'description': 'Self-directed achiever who consistently improves systems'
    }
}

# Quadrant definitions (Skill × Agency)
QUADRANTS = {
    'developing_contributor': {
        'name': 'Developing Contributor',
        'skill_range': (1, 2.5),
        'agency_range': (1, 2.5),
        'description': 'Building foundational skills and learning to work independently',
        'characteristics': [
            'Early in career or role',
            'Requires guidance and support',
            'Building fundamental capabilities',
            'Needs structured development'
        ],
        'development_path': 'Focus on building core skills through deliberate practice and seeking guidance. Work on taking more initiative on familiar tasks.'
    },
    'hungry_learner': {
        'name': 'Hungry Learner',
        'skill_range': (1, 2.5),
        'agency_range': (2.5, 5),
        'description': 'High initiative but developing expertise - eager to learn and contribute',
        'characteristics': [
            'Strong drive and motivation',
            'Seeks opportunities to grow',
            'May overcommit without experience',
            'Benefits from mentorship'
        ],
        'development_path': 'Channel your energy into deliberate skill development. Seek mentorship from experts. Balance enthusiasm with building depth.'
    },
    'specialist': {
        'name': 'Specialist',
        'skill_range': (2.5, 5),
        'agency_range': (1, 2.5),
        'description': 'Deep expertise but waits for direction - valuable contributor when engaged',
        'characteristics': [
            'Strong technical capabilities',
            'Reliable when given clear objectives',
            'Prefers depth over breadth',
            'May need encouragement to lead'
        ],
        'development_path': 'Build confidence in taking initiative. Start with small ownership opportunities. Share your expertise proactively.'
    },
    'force_multiplier': {
        'name': 'Force Multiplier',
        'skill_range': (2.5, 5),
        'agency_range': (2.5, 5),
        'description': 'High skill and high initiative - drives team success and innovation',
        'characteristics': [
            'Combines expertise with initiative',
            'Mentors and elevates others',
            'Drives meaningful improvements',
            'Trusted for complex challenges'
        ],
        'development_path': 'Continue expanding your impact. Focus on strategic initiatives and developing others. Consider broader leadership roles.'
    }
}


def calculate_dreyfus_level(report_data: Dict, questionnaire_id: Optional[int] = None) -> Optional[Dict]:
    """
    Calculate Dreyfus skill level from weighted question responses.

    This function looks for questions tagged with 'dreyfus_mapping' metadata
    in their config. If no metadata exists, falls back to section-based detection.

    Args:
        report_data: The complete report data structure with responses
        questionnaire_id: Optional questionnaire ID for logging

    Returns:
        Dictionary with:
        - skill_level: Float 1-5 representing overall skill level
        - skill_stage: String name of Dreyfus stage
        - confidence: Float 0-1 indicating calculation confidence
        - contributing_questions: List of question IDs that contributed
        - stage_info: Full stage information (traits, behaviors, etc.)
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
                # Get average score across all categories (exclude self-assessment and insufficient data)
                category_scores = []
                for category, cat_data in question_data.get('by_category', {}).items():
                    # Skip self-assessment in skill calculation (use only others' ratings)
                    if category == 'self':
                        continue
                    # Check for avg (report_data format) or average (alternative format)
                    avg_score = cat_data.get('avg') or cat_data.get('average')
                    if avg_score and not cat_data.get('insufficient', False):
                        category_scores.append(avg_score)

                if category_scores:
                    avg_score = mean(category_scores)
                    weighted_scores.append((avg_score, weight))
                    contributing_questions.append(question_id)

    # If we found metadata-based scores, use them
    if weighted_scores:
        # Calculate weighted average
        total_weight = sum(w for _, w in weighted_scores)
        if total_weight > 0:
            skill_level = sum(score * weight for score, weight in weighted_scores) / total_weight
        else:
            skill_level = mean(score for score, _ in weighted_scores)

        # Confidence based on number of contributing questions and total weight
        confidence = min(1.0, (len(contributing_questions) / 5.0) * (total_weight / 3.0))

    else:
        # Fallback: section-based detection (legacy behavior)
        skill_level, confidence = _fallback_section_based_detection(report_data)
        if skill_level is None:
            return None

    # Map to stage
    stage_num = _level_to_stage(skill_level)
    stage_info = DREYFUS_STAGES[stage_num].copy()

    # Add development focus (what's needed for next level)
    next_stage_num = min(5, stage_num + 1)
    if next_stage_num > stage_num:
        stage_info['next_stage'] = DREYFUS_STAGES[next_stage_num]['name']
        stage_info['development_focus'] = _get_development_focus(stage_num, next_stage_num)
    else:
        stage_info['next_stage'] = None
        stage_info['development_focus'] = ['Continue deepening expertise and innovating']

    return {
        'skill_level': round(skill_level, 2),
        'skill_stage': stage_info['name'],
        'confidence': round(confidence, 2),
        'contributing_questions': contributing_questions,
        'stage_info': stage_info
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
        - agency_stage: String name of agency stage
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
                # Get average score across all categories (exclude self-assessment)
                category_scores = []
                for category, cat_data in question_data.get('by_category', {}).items():
                    # Skip self-assessment in agency calculation (use only others' ratings)
                    if category == 'self':
                        continue
                    # Check for avg (report_data format) or average (alternative format)
                    avg_score = cat_data.get('avg') or cat_data.get('average')
                    if avg_score and not cat_data.get('insufficient', False):
                        category_scores.append(avg_score)

                if category_scores:
                    avg_score = mean(category_scores)
                    weighted_scores.append((avg_score, weight))
                    contributing_questions.append(question_id)

    if not weighted_scores:
        return None

    # Calculate weighted average
    total_weight = sum(w for _, w in weighted_scores)
    if total_weight > 0:
        agency_level = sum(score * weight for score, weight in weighted_scores) / total_weight
    else:
        agency_level = mean(score for score, _ in weighted_scores)

    # Confidence based on number of questions and weight
    confidence = min(1.0, (len(contributing_questions) / 3.0) * (total_weight / 2.0))

    # Map to stage
    stage_num = _level_to_stage(agency_level)
    stage_info = AGENCY_STAGES[stage_num].copy()

    return {
        'agency_level': round(agency_level, 2),
        'agency_stage': stage_info['name'],
        'confidence': round(confidence, 2),
        'contributing_questions': contributing_questions,
        'description': stage_info['description']
    }


def calculate_dreyfus_quadrant(skill_level: float, agency_level: float) -> Dict:
    """
    Map skill and agency levels to organizational quadrant.

    Args:
        skill_level: Skill level (1-5)
        agency_level: Agency level (1-5)

    Returns:
        Dictionary with quadrant information
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

    quadrant_info = QUADRANTS[quadrant_key].copy()
    quadrant_info['quadrant_key'] = quadrant_key
    quadrant_info['skill_level'] = round(skill_level, 2)
    quadrant_info['agency_level'] = round(agency_level, 2)

    return quadrant_info


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
    - Gap to next level
    - Specific feedback from reviewers
    - Weakest sub-dimensions

    Args:
        skill_profile: Output from calculate_dreyfus_level()
        agency_profile: Output from calculate_agency_level()
        report_data: Full report data for context

    Returns:
        Dictionary with personalized recommendations
    """
    recommendations = {
        'primary_focus': '',
        'quick_wins': [],
        'long_term_goals': [],
        'resources': [],
        'next_level_requirements': []
    }

    if not skill_profile:
        return recommendations

    current_stage = _level_to_stage(skill_profile['skill_level'])
    next_stage = min(5, current_stage + 1)

    # Primary focus based on current stage
    if current_stage == 1:
        recommendations['primary_focus'] = 'Build foundational skills through deliberate practice and close guidance from experienced mentors.'
    elif current_stage == 2:
        recommendations['primary_focus'] = 'Develop deeper pattern recognition and start building mental models of your domain.'
    elif current_stage == 3:
        recommendations['primary_focus'] = 'Expand your perspective to see the bigger picture and learn from diverse experiences.'
    elif current_stage == 4:
        recommendations['primary_focus'] = 'Deepen intuition through extensive practice and begin creating novel approaches.'
    else:
        recommendations['primary_focus'] = 'Continue innovating and sharing your expertise to advance the field.'

    # Get specific feedback from development_areas in insights
    development_areas = _extract_development_areas(report_data)

    # Quick wins - actionable items based on feedback
    if current_stage < 3:
        recommendations['quick_wins'] = [
            'Seek feedback on your work early and often',
            'Study examples of good work in your domain',
            'Practice deliberate problem-solving with guidance'
        ]
    elif current_stage == 3:
        recommendations['quick_wins'] = [
            'Take ownership of a complete project or feature',
            'Learn from colleagues at different skill levels',
            'Document your decision-making process'
        ]
    else:
        recommendations['quick_wins'] = [
            'Mentor someone less experienced',
            'Share your knowledge through documentation or talks',
            'Tackle a novel problem in your domain'
        ]

    # Add specific recommendations from weak areas
    if development_areas:
        for area in development_areas[:3]:  # Top 3 areas
            recommendations['quick_wins'].append(
                f"Focus on improving: {area['area'].lower()}"
            )

    # Long-term goals
    if next_stage <= 5:
        stage_info = DREYFUS_STAGES[next_stage]
        recommendations['long_term_goals'] = [
            f'Develop capabilities of a {stage_info["name"]}: {stage_info["short_description"]}',
            'Build experience across diverse situations',
            'Continuously reflect on your practice and learning'
        ]

    # Resources
    if current_stage <= 2:
        recommendations['resources'] = [
            'Structured learning programs or courses',
            'Regular mentorship sessions',
            'Code reviews and pair programming'
        ]
    elif current_stage == 3:
        recommendations['resources'] = [
            'Cross-functional projects',
            'Technical leadership opportunities',
            'Industry conferences and communities'
        ]
    else:
        recommendations['resources'] = [
            'Research and innovation projects',
            'Teaching and mentoring opportunities',
            'Speaking at conferences or writing articles'
        ]

    # Requirements for next level
    if next_stage <= 5:
        recommendations['next_level_requirements'] = skill_profile['stage_info'].get('development_focus', [])

    # Factor in agency if available
    if agency_profile:
        agency_level = agency_profile['agency_level']
        skill_level = skill_profile['skill_level']

        # If agency is lagging behind skill
        if agency_level < skill_level - 0.5:
            recommendations['quick_wins'].insert(0, 'Take more initiative on projects - your skills are ready for more ownership')

        # If skill is lagging behind agency
        elif skill_level < agency_level - 0.5:
            recommendations['quick_wins'].insert(0, 'Focus on deepening your technical expertise to match your initiative')

    return recommendations


# Helper functions

def _level_to_stage(level: float) -> int:
    """Convert continuous level (1.0-5.0) to discrete stage (1-5)."""
    if level >= 4.5:
        return 5
    elif level >= 3.5:
        return 4
    elif level >= 2.5:
        return 3
    elif level >= 1.5:
        return 2
    else:
        return 1


def _get_development_focus(current_stage: int, next_stage: int) -> List[str]:
    """Get what's needed to progress from current to next stage."""
    focus_areas = {
        (1, 2): [
            'Recognize recurring patterns in your work',
            'Handle routine tasks independently',
            'Build situational awareness beyond just following rules'
        ],
        (2, 3): [
            'Develop mental models of how things work',
            'Take responsibility for outcomes, not just tasks',
            'Plan and prioritize work deliberately'
        ],
        (3, 4): [
            'See the big picture and system context',
            'Learn from others\' experiences, not just your own',
            'Recognize patterns and deviations quickly'
        ],
        (4, 5): [
            'Trust your intuition based on deep experience',
            'Create novel approaches and solutions',
            'Become a recognized authority in your domain'
        ]
    }
    return focus_areas.get((current_stage, next_stage), ['Continue developing expertise'])


def _fallback_section_based_detection(report_data: Dict) -> Tuple[Optional[float], float]:
    """
    Legacy fallback: detect skill level from 'Technical Expertise & Skill Level' section.
    Returns (skill_level, confidence) or (None, 0.0) if not found.
    """
    # Look for technical expertise section (Software Engineering questionnaire)
    tech_section_names = ['Technical Expertise & Skill Level', 'Problem Solving & Decision Making']

    for section_data in report_data.get('by_section', {}).values():
        section_title = section_data.get('title', '')

        if section_title in tech_section_names:
            # Collect all question averages from this section
            section_scores = []
            for question_data in section_data.get('questions', {}).values():
                for cat_data in question_data.get('by_category', {}).values():
                    if not cat_data.get('insufficient', False) and cat_data.get('average'):
                        section_scores.append(cat_data['average'])

            if section_scores:
                skill_level = mean(section_scores)
                confidence = 0.6  # Lower confidence for fallback method
                return skill_level, confidence

    return None, 0.0


def _extract_development_areas(report_data: Dict) -> List[Dict]:
    """Extract development areas from report data insights."""
    # This would typically come from the insights section
    # For now, return empty list - will be populated by main report generation
    return []
