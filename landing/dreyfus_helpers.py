"""
Helper functions for Dreyfus and Agency level calculations on landing app.

These calculations match the weights configured in the Developer Skills Assessment
questionnaire and provide instant preview results before full report generation.
"""


def calculate_skill_level(answers):
    """
    Calculate Dreyfus skill level from questionnaire answers.

    Matches dreyfus_mapping weights configured in the questionnaire:
    - Questions 1-8 contribute to skill dimension
    - Question 8 is dual-dimension (also contributes to agency)
    - Question 13 is dual-dimension (also contributes to skill)

    Args:
        answers: dict mapping question_id to answer value (1-5)
                Example: {1: 4, 2: 3, 3: 5, ...}

    Returns:
        float: Skill level from 1.0 to 5.0, rounded to 1 decimal place
    """
    # Question IDs mapped to their skill weights
    # Based on create_growth_questionnaire.py configuration
    skill_weights = {
        1: 2.0,    # Problem solving approach (highest weight)
        2: 1.5,    # Design patterns
        3: 1.5,    # Debugging
        4: 1.0,    # Learning
        5: 1.0,    # Code review
        6: 1.5,    # System understanding
        7: 1.0,    # Performance optimization
        8: 1.0,    # Decision making (also has agency weight)
        13: 0.5,   # Scope (dual-dimension from agency section)
    }

    weighted_sum = 0.0
    total_weight = 0.0

    for question_id, weight in skill_weights.items():
        if question_id in answers:
            answer_value = answers[question_id]
            weighted_sum += answer_value * weight
            total_weight += weight

    if total_weight == 0:
        return 3.0  # Default to middle if no skill questions answered

    skill_level = weighted_sum / total_weight
    return round(skill_level, 1)


def calculate_agency_level(answers):
    """
    Calculate agency level from questionnaire answers.

    Matches dreyfus_mapping weights configured in the questionnaire:
    - Questions 9-13 contribute to agency dimension
    - Question 8 is dual-dimension (also contributes to agency)
    - Question 13 is dual-dimension (also contributes to skill)

    Args:
        answers: dict mapping question_id to answer value (1-5)

    Returns:
        float: Agency level from 1.0 to 5.0, rounded to 1 decimal place
    """
    # Question IDs mapped to their agency weights
    agency_weights = {
        8: 0.5,    # Decision making (dual-dimension from skill section)
        9: 2.0,    # Problem ownership (highest weight)
        10: 1.5,   # Feedback & improvement
        11: 1.5,   # Professional development
        12: 1.5,   # Handling blockers
        13: 1.0,   # Scope of thinking
    }

    weighted_sum = 0.0
    total_weight = 0.0

    for question_id, weight in agency_weights.items():
        if question_id in answers:
            answer_value = answers[question_id]
            weighted_sum += answer_value * weight
            total_weight += weight

    if total_weight == 0:
        return 3.0  # Default to middle if no agency questions answered

    agency_level = weighted_sum / total_weight
    return round(agency_level, 1)


def get_skill_stage(level):
    """
    Map numeric skill level to Dreyfus stage name.

    Dreyfus Model stages:
    1. Novice (1.0-1.5)
    2. Advanced Beginner (1.5-2.5)
    3. Competent (2.5-3.5)
    4. Proficient (3.5-4.5)
    5. Expert (4.5-5.0)

    Args:
        level: Numeric skill level (1.0-5.0)

    Returns:
        str: Stage name
    """
    if level < 1.5:
        return "Novice"
    elif level < 2.5:
        return "Advanced Beginner"
    elif level < 3.5:
        return "Competent"
    elif level < 4.5:
        return "Proficient"
    else:
        return "Expert"


def get_agency_stage(level):
    """
    Map numeric agency level to stage name.

    Agency Levels:
    1. Directed (1.0-1.5) - Waits for explicit instructions
    2. Assisted (1.5-2.5) - Takes initiative when prompted
    3. Independent (2.5-3.5) - Proactively addresses problems
    4. Proactive (3.5-4.5) - Proposes improvements
    5. Self-Driven (4.5-5.0) - Consistently improves systems

    Args:
        level: Numeric agency level (1.0-5.0)

    Returns:
        str: Stage name
    """
    if level < 1.5:
        return "Directed"
    elif level < 2.5:
        return "Assisted"
    elif level < 3.5:
        return "Independent"
    elif level < 4.5:
        return "Proactive"
    else:
        return "Self-Driven"


def get_quadrant(skill_level, agency_level):
    """
    Determine performance quadrant based on skill and agency levels.

    4 Quadrants (Skill × Agency):
    - Force Multiplier: High skill (≥3.5) + High agency (≥3.5)
    - Specialist: High skill (≥3.5) + Lower agency (<3.5)
    - Hungry Learner: Lower skill (<3.5) + High agency (≥3.5)
    - Developing Contributor: Lower skill (<3.5) + Lower agency (<3.5)

    Args:
        skill_level: Numeric skill level (1.0-5.0)
        agency_level: Numeric agency level (1.0-5.0)

    Returns:
        dict: {
            'key': str,           # Machine-readable key
            'name': str,          # Display name
            'description': str    # Brief description
        }
    """
    high_skill = skill_level >= 3.5
    high_agency = agency_level >= 3.5

    if high_skill and high_agency:
        return {
            'key': 'force_multiplier',
            'name': 'Force Multiplier',
            'description': 'High skill and high initiative - you amplify team effectiveness'
        }
    elif high_skill and not high_agency:
        return {
            'key': 'specialist',
            'name': 'Specialist',
            'description': 'Strong technical skills - focus on expanding scope and initiative'
        }
    elif not high_skill and high_agency:
        return {
            'key': 'hungry_learner',
            'name': 'Hungry Learner',
            'description': 'Great initiative - keep building technical depth'
        }
    else:
        return {
            'key': 'developing_contributor',
            'name': 'Developing Contributor',
            'description': 'Growing in both skill and agency - lots of runway ahead'
        }


def calculate_preview_results(answers):
    """
    Calculate all preview results from questionnaire answers.

    This is a convenience function that calculates all metrics at once
    for displaying the preview page after questionnaire submission.

    Args:
        answers: dict mapping question_id to answer value (1-5)

    Returns:
        dict: {
            'skill_level': float,
            'skill_stage': str,
            'agency_level': float,
            'agency_stage': str,
            'quadrant': dict,
            'confidence': str  # 'high' or 'medium' based on completion
        }
    """
    skill_level = calculate_skill_level(answers)
    agency_level = calculate_agency_level(answers)

    skill_stage = get_skill_stage(skill_level)
    agency_stage = get_agency_stage(agency_level)

    quadrant = get_quadrant(skill_level, agency_level)

    # Determine confidence based on how many required questions were answered
    # We have 13 required questions (8 skill + 5 agency)
    required_questions = set(range(1, 14))  # Questions 1-13
    answered_required = len(required_questions & set(answers.keys()))
    confidence = 'high' if answered_required >= 11 else 'medium'

    return {
        'skill_level': skill_level,
        'skill_stage': skill_stage,
        'agency_level': agency_level,
        'agency_stage': agency_stage,
        'quadrant': quadrant,
        'confidence': confidence
    }
