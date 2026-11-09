from statistics import mean

MAX_STRENGTHS = 3
MAX_GROWTH = 2
MAX_NEXT_STEPS = 2


def executive_summary(context):
    """
    What page 1 of the report PDF shows, from build_report_context() output.

    Every value is None or empty when its data is missing: a hidden reviewer group leaves combined values out.
    """
    data = context['report_data']
    insights = data.get('insights') or {}
    sentiment = insights.get('overall_sentiment')
    skill = insights.get('skill_profile')
    agency = insights.get('agency_profile')
    quadrant = insights.get('dreyfus_quadrant')
    plan = insights.get('development_plan') or {}
    trend = (data.get('comparison') or {}).get('overall_trend')

    self_gap = None
    if sentiment and sentiment.get('self_avg') is not None:
        self_gap = {
            'self_avg': sentiment['self_avg'],
            'gap': round(sentiment['self_avg'] - sentiment['score'], 2),
        }

    return {
        'overall': {'score': sentiment['score'], 'rating': sentiment['rating'], 'trend': trend} if sentiment else None,
        'self_gap': self_gap,
        # .get(): a report stored by an older Blik may lack the stage texts
        'skill': {'stage': skill.get('skill_stage'), 'level': skill.get('skill_level')} if skill else None,
        'agency': {'stage': agency.get('agency_stage'), 'level': agency.get('agency_level')} if agency else None,
        'quadrant': {'name': quadrant['name'], 'description': quadrant['description']} if quadrant else None,
        'strengths': (insights.get('strengths') or [])[:MAX_STRENGTHS],
        'growth': (insights.get('development_areas') or [])[:MAX_GROWTH],
        'next_steps': list(plan.get('next_level_requirements') or plan.get('quick_wins') or [])[:MAX_NEXT_STEPS],
        'sections_below_self_count': _sections_below_self(data.get('section_summary') or {}),
    }


def _sections_below_self(section_summary):
    """Sections where the visible others score lower than self, or None when no section has both."""
    count = None
    for categories in section_summary.values():
        scores = {c: v for c, v in categories.items() if not isinstance(v, dict)}
        self_score = scores.pop('self', None)
        if self_score is None or not scores:
            continue
        count = (count or 0) + (mean(scores.values()) < self_score)
    return count
