from .report_texts import with_texts
from .services import (
    _get_previous_cycle_report,
    _hidden_groups,
    apply_display_anonymization,
    get_report_summary,
)


def build_report_context(report, *, is_admin_view):
    """
    Template context for the report, shared by the web views and the PDF.

    Anonymize the stored data first: with_texts() adds the texts to insights that
    were calculated without the hidden groups.
    """
    cycle = report.cycle
    threshold = cycle.organization.min_responses_for_anonymity
    anonymized = apply_display_anonymization(report.report_data, min_threshold=threshold)
    _leave_out_trends_from_hidden_previous(anonymized, cycle, threshold)
    display_data = with_texts(anonymized, cycle.questionnaire, cycle.reviewee.name)

    return {
        'cycle': cycle,
        'report': report,
        'report_data': display_data,
        'display_data': display_data,
        'summary': get_report_summary(report),
        'questionnaire': cycle.questionnaire.translated(),
        'is_admin_view': is_admin_view,
    }


def _leave_out_trends_from_hidden_previous(display_data, cycle, threshold):
    """
    The trends compare with the previous report's stored combined values. When that report
    hides a group, its values include the group's answers, and the change gives them away.
    """
    comparison = display_data.get('comparison') or {}
    if 'overall_trend' not in comparison and 'section_trends' not in comparison:
        return
    previous = _get_previous_cycle_report(cycle)
    if previous and _hidden_groups(previous.report_data, threshold, ['self', 'manager']):
        comparison.pop('overall_trend', None)
        comparison.pop('section_trends', None)
