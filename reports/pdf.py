"""The report as a PDF: the reviewee's web report, condensed onto A4 pages."""
from datetime import date

import weasyprint
from django.conf import settings
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.text import slugify
from django.utils.translation import gettext, gettext_lazy as _, ngettext
from weasyprint.urls import URLFetcher

from core.languages import recipient_language
from reviews.models import CATEGORY_ORDER
from reviews.templatetags.feedback_tags import distribution_key, likert_positive_count, others_average, percentage, \
    report_options

from .report_texts import RATING_RANGES, RATINGS
from .services import _hidden_groups, get_rating_key

from .context import build_report_context
from .dreyfus_service import AGENCY_STAGES, QUADRANTS
from .pdf_charts import radar_chart
from .pdf_summary import executive_summary

FONT_DIR = settings.BASE_DIR / 'static' / 'fonts' / 'roboto'
RADAR_MIN_SECTIONS = 3  # a radar of one or two axes is a line, the bars show those

# What it takes to reach an agency level: the same texts as the web report (_dreyfus_profile.html)
AGENCY_NEXT_STEPS = {
    2: {
        'requirements': [
            _('When reporting problems, investigate root causes'),
            _('Respond to guidance with thoughtful analysis'),
            _('Ask clarifying questions before escalating'),
        ],
        'actions': [
            _('Next time you spot an issue, spend 10 minutes investigating before reporting'),
            _('When given a task, propose at least one way to approach it'),
        ],
    },
    3: {
        'requirements': [
            _('Research multiple solution options before asking for help'),
            _('Take ownership of problems you discover'),
            _('Present tradeoffs of different approaches'),
        ],
        'actions': [
            _('When facing a problem, list 2-3 possible solutions before asking for help'),
            _('Volunteer to own a small problem end-to-end this sprint'),
        ],
    },
    4: {
        'requirements': [
            _('Make clear recommendations backed by reasoning'),
            _('Proactively identify improvements before issues arise'),
            _('Build confidence in decision-making through successful recommendations'),
        ],
        'actions': [
            _('Present your next problem-solution with a specific recommendation and why'),
            _('Identify one process improvement opportunity this week'),
        ],
    },
    5: {
        'requirements': [
            _('Execute solutions autonomously within your domain'),
            _('Inform stakeholders after implementing fixes'),
            _('Drive systemic improvements, not just point solutions'),
        ],
        'actions': [
            _('Fix the next issue you discover without asking permission (inform after)'),
            _('Document your decision-making process for others to learn from'),
        ],
    },
}

# Quadrant grid of the performance matrix: (key, column, row), row 0 is high agency
QUADRANT_CELLS = [
    ('hungry_learner', 0, 0), ('force_multiplier', 1, 0),
    ('developing_contributor', 0, 1), ('specialist', 1, 1),
]
QUADRANT_SPLIT = 2.5  # see calculate_dreyfus_quadrant()


def reviewee_language(report):
    reviewee = report.cycle.reviewee
    return recipient_language(reviewee.language, organization=reviewee.organization)


def pdf_filename(report):
    cycle = report.cycle
    name = slugify(cycle.reviewee.name) or f'report-{str(cycle.uuid)[:8]}'
    return f'{name}-360-feedback-{report.generated_at:%Y-%m-%d}.pdf'


def report_pdf_html(report, language):
    with translation.override(language):
        return render_to_string('reports/pdf/report.html', _pdf_context(report))


def report_pdf_document(report, language):
    html = report_pdf_html(report, language)
    # Fonts and everything else come from local files: a render never touches the network.
    fetcher = URLFetcher(allowed_protocols={'file', 'data'})
    return weasyprint.HTML(string=html, base_url=str(settings.BASE_DIR), url_fetcher=fetcher).render()


def render_report_pdf(report, language):
    return report_pdf_document(report, language).write_pdf()


def store_report_pdf(report):
    pdf = render_report_pdf(report, reviewee_language(report))
    old_name = report.pdf_file.name
    # Save first, so a failed save keeps the old file
    report.pdf_file.save(pdf_filename(report), ContentFile(pdf), save=False)
    report.pdf_generated_at = timezone.now()
    report.save(update_fields=['pdf_file', 'pdf_generated_at'])
    if old_name and old_name != report.pdf_file.name:
        report.pdf_file.storage.delete(old_name)


def drop_report_pdf(report):
    if report.pdf_file:
        report.pdf_file.delete(save=False)
    report.pdf_file = ''
    report.pdf_generated_at = None
    # A new or regenerated report gets all its build attempts again
    report.pdf_attempts = 0
    report.save(update_fields=['pdf_file', 'pdf_generated_at', 'pdf_attempts'])


def _pdf_context(report):
    context = build_report_context(report, is_admin_view=False)
    threshold = context['cycle'].organization.min_responses_for_anonymity
    data = context['report_data']
    insights = data.get('insights') or {}
    comparison = data.get('comparison') or {}
    section_scores = (data.get('charts') or {}).get('section_scores') or {}

    figures = executive_summary(context)
    if figures['overall'] and figures['overall']['trend']:
        figures['overall']['trend_class'] = _trend_class(figures['overall']['trend'])

    context.update({
        'reviewee_name': context['cycle'].reviewee.name,
        'summary_figures': figures,
        'feedback_groups': _feedback_groups(
            context['summary'], _hidden_groups(report.report_data, threshold, ['self', 'manager']),
            gettext('Insufficient responses (minimum %(count)s required)') % {'count': threshold},
        ),
        'show_trends': bool(comparison.get('show_trends')),
        'previous_date': _iso_date(comparison.get('previous_cycle_date')) if comparison.get('has_previous') else None,
        'radar': radar_chart(section_scores) if len(section_scores) >= RADAR_MIN_SECTIONS else None,
        'sections': _section_table(data, insights, comparison),
        'rating_ranges': list(RATING_RANGES.items()),
        'agency': _agency(insights.get('agency_profile')),
        'matrix': _matrix(insights.get('dreyfus_quadrant')),
        'detail_sections': _detail_sections(data),
        'font_dir': FONT_DIR.as_uri(),
    })
    return context


def _iso_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return value


def _feedback_groups(summary, hidden, message):
    """Who gave feedback, for the cover: a hidden group shows the insufficient message, never its count."""
    counts = summary.get('by_category') or {}
    groups = {
        'peer': lambda n: ngettext('%(count)s peer', '%(count)s peers', n),
        'manager': lambda n: ngettext('%(count)s manager', '%(count)s managers', n),
        'direct_report': lambda n: ngettext('%(count)s direct report', '%(count)s direct reports', n),
    }
    lines = []
    for category in [c for c in CATEGORY_ORDER if c != 'self'] + ['self']:
        if not counts.get(category):
            continue
        if category in hidden:
            lines.append({'category': category, 'hidden': True, 'text': message})
        elif category == 'self':
            lines.append({'category': category, 'text': gettext('Self-assessment')})
        else:
            lines.append({'category': category, 'text': groups[category](counts[category]) % {'count': counts[category]}})
    return lines


def _trend_class(trend):
    direction = (trend or {}).get('direction', '')
    return 'up' if direction.endswith('up') else 'down' if direction.endswith('down') else 'muted'


def _section_table(data, insights, comparison):
    """One row per section: the others' score, your own, and the score of each reviewer group."""
    summary = data.get('section_summary') or {}
    trends = (comparison.get('section_trends') or {}) if comparison.get('show_trends') else {}
    benchmarks = data.get('peer_benchmarks') or {}
    strengths = {item['area'] for item in insights.get('strengths') or []}
    growth = {item['area']: item for item in insights.get('development_areas') or []}
    groups = [c for c in CATEGORY_ORDER if c != 'self' and any(c in cats for cats in summary.values())]
    hidden = {}
    rows = []
    for name, categories in summary.items():
        score = others_average(categories) or None
        own = categories.get('self')
        own = own if isinstance(own, (int, float)) else None
        cells = []
        for category in groups:
            value = categories.get(category)
            hidden_group = isinstance(value, dict)
            if hidden_group:
                hidden.setdefault(category, value.get('message'))
            cells.append({'score': None if hidden_group else value, 'hidden': hidden_group})
        benchmark = benchmarks.get(name)
        rows.append({
            'name': name,
            'score': score,
            'rating': RATINGS[get_rating_key(score)] if score else None,
            'level': get_rating_key(score) if score else 'none',
            'bar': _percent(score),
            'self': own,
            'tick': _percent(own),
            'gap': round(own - score, 1) if own is not None and score else None,
            'cells': cells,
            'trend': trends.get(name),
            'trend_class': _trend_class(trends.get(name)),
            'strength': name in strengths,
            'growth': growth.get(name),
            # The reviewee sees a benchmark only when it is a good one, as on the web
            'benchmark': benchmark if benchmark and benchmark.get('show_percentile') else None,
        })
    if not rows:
        return None
    return {
        'groups': groups,
        'has_self': any(row['self'] is not None for row in rows),
        'rows': rows,
        'hidden': list(hidden.items()),
    }


def _percent(score, top=5):
    """A score as a share of the top score, as text for a CSS width."""
    return None if score is None else '%.1f' % (max(0, min(score, top)) / top * 100)


def _agency(profile):
    if not profile:
        return None
    stage = profile['stage']
    next_stage = stage + 1 if stage < 5 else None
    return {
        'steps': [
            {'name': AGENCY_STAGES[n]['name'], 'on': n <= stage, 'current': n == stage} for n in range(1, 6)
        ],
        'next_name': AGENCY_STAGES[next_stage]['name'] if next_stage else None,
        'next_steps': AGENCY_NEXT_STEPS.get(next_stage),
    }


def _matrix(quadrant):
    """The performance matrix as cells of a 2x2 grid of 100x100, with the reviewee's dot."""
    if not quadrant:
        return None

    def position(level):
        # Each half covers its own range, so the dot always sits in its quadrant
        if level < QUADRANT_SPLIT:
            return (level - 1) / (QUADRANT_SPLIT - 1) * 50
        return 50 + (level - QUADRANT_SPLIT) / (5 - QUADRANT_SPLIT) * 50

    def clamp(value):
        return max(6, min(94, value))

    dot_x = round(clamp(position(quadrant['skill_level'])), 1)
    dot_y = round(clamp(100 - position(quadrant['agency_level'])), 1)
    cells = []
    for key, column, row in QUADRANT_CELLS:
        x, y = column * 50, row * 50
        current = key == quadrant['quadrant_key']
        # In the reviewee's cell, the name moves to the half without the dot
        middle = y + (25 if not current else 37 if dot_y - y < 25 else 14)
        lines = _two_lines(str(QUADRANTS[key]['name']))
        cells.append({
            'x': x, 'y': y, 'current': current, 'lines': lines,
            'text_x': x + 25, 'text_y': round(middle - (len(lines) - 1) * 3.6 + 2, 1),
        })
    return {'cells': cells, 'dot_x': dot_x, 'dot_y': dot_y}


def _two_lines(name):
    """A name split at the space nearest its middle."""
    spaces = [i for i, char in enumerate(name) if char == ' ']
    if not spaces:
        return [name]
    split = min(spaces, key=lambda i: abs(i - len(name) / 2))
    return [name[:split], name[split + 1:]]


def _detail_sections(data):
    sections = []
    for section in (data.get('by_section') or {}).values():
        questions = [_detail_question(question) for question in (section.get('questions') or {}).values()]
        sections.append({'title': section.get('title'), 'questions': questions})
    return sections


def _detail_question(question):
    """A question with one row per reviewer group; a column per answer holds how many gave it."""
    by_category = question.get('by_category') or {}
    order = [c for c in (question.get('category_order') or list(by_category)) if c in by_category]
    qtype = question.get('question_type')
    options = report_options(question)
    if qtype == 'rating':
        columns = [(str(rating), str(rating)) for rating in range(1, 6)]
    elif qtype in ('likert', 'single_choice', 'multiple_choice'):
        columns = [(distribution_key(option), option['label']) for option in options]
    else:
        columns = []
    has_avg = qtype in ('rating', 'scale') or (
        qtype in ('single_choice', 'multiple_choice') and (question.get('question_config') or {}).get('scoring_enabled')
    )

    rows = []
    for category in order:
        group = by_category[category]
        count = group.get('count') or 0
        row = {'category': category, 'group': group, 'count': count, 'avg': group.get('avg') if has_avg else None}
        if not group.get('insufficient'):
            distribution = group.get('distribution') or {}
            row['cells'] = [_cell(distribution.get(key, 0), count) for key, _label in columns]
            if qtype == 'likert':
                # The share in the two highest options, which the web report calls positive
                row['positive'] = percentage(likert_positive_count(distribution, options), count)
        rows.append(row)

    # As on the web, the self-assessment is compared with the others: it is not one more reviewer group
    own = next((row for row in rows if row['category'] == 'self'), None)
    others = [row for row in rows if row['category'] != 'self']
    others_avg = _others_avg(others) if has_avg else None
    if own and own['avg'] is not None and others_avg is not None:
        own['gap'] = round(own['avg'] - others_avg, 2)
    return {
        'data': question, 'type': qtype, 'columns': [label for _key, label in columns],
        'has_avg': has_avg, 'has_positive': qtype == 'likert', 'rows': others, 'self': own,
        'others_avg': others_avg, 'span': len(columns) + bool(has_avg) + (qtype == 'likert'),
        'answer_span': len(columns) + (qtype == 'likert'),
    }


def _others_avg(rows):
    """The mean of the shown reviewer groups' averages, as the section scores; never the self-assessment."""
    scores = [
        row['avg'] for row in rows
        if row['category'] != 'self' and not row['group'].get('insufficient') and row['avg'] is not None
    ]
    return round(sum(scores) / len(scores), 2) if scores else None


def _cell(count, total):
    """How many gave an answer, shaded by their share of the group."""
    if not count:
        return {'count': None}
    share = count / total if total else 0
    return {'count': count, 'shade': '%.2f' % (0.08 + 0.72 * share), 'dark': share >= 0.5}
