from .report_texts import with_texts
from .services import apply_display_anonymization, get_report_summary


def build_report_context(report, *, is_admin_view):
    """
    Template context for the report, shared by the web views and the PDF.

    Anonymize the stored data first: with_texts() adds the texts to insights that
    were calculated without the hidden groups.
    """
    cycle = report.cycle
    display_data = with_texts(
        apply_display_anonymization(
            report.report_data, min_threshold=cycle.organization.min_responses_for_anonymity,
        ),
        cycle.questionnaire,
        cycle.reviewee.name,
    )

    return {
        'cycle': cycle,
        'report': report,
        'report_data': display_data,
        'display_data': display_data,
        'summary': get_report_summary(report),
        'questionnaire': cycle.questionnaire.translated(),
        'is_admin_view': is_admin_view,
    }
