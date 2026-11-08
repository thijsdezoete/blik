from django.core import signing
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, Http404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone, translation
from django.db import transaction
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit
from core.languages import is_language, request_language
from core.models import Organization
from .models import ReviewerToken, Response, ReviewCycle
from .services import (
    OVERVIEW_LINK_MAX_AGE, self_assessment_token, reviewer_relation, estimated_minutes, send_overview_link_email,
)
from subscriptions.utils import ReviewerLimit
from questionnaires.answer_options import OPTION_TYPES, resolve_answer
from questionnaires.models import Question
import secrets
import logging

logger = logging.getLogger(__name__)


def activate_token_language(request, reviewer_token):
    """
    The reviewer's language: the token's (for the self-assessment, else the reviewee's), else the
    browser's, else the organization's default. Stored on the token the first time, so reminders
    go out in the language the form was shown in.
    """
    reviewee = reviewer_token.cycle.reviewee
    language = request_language(
        request,
        reviewer_token.language,
        reviewee.language if reviewer_token.category == 'self' else '',
        organization=reviewee.organization,
    )

    if not reviewer_token.language:
        reviewer_token.language = language
        reviewer_token.save(update_fields=['language'])

    translation.activate(language)
    request.LANGUAGE_CODE = language


def claim_token(request, invitation_token):
    """
    Claim an available token using a secure invitation token.
    First shows a page that checks localStorage, then randomly assigns if needed.
    """
    # Find the cycle and category by invitation token
    cycle = None
    category = None

    # Try each category token field
    for cat_code, cat_display in ReviewerToken.CATEGORY_CHOICES:
        field_name = f'invitation_token_{cat_code}'
        cycles = ReviewCycle.objects.filter(**{field_name: invitation_token, 'status': 'active'})
        if cycles.exists():
            cycle = cycles.first()
            category = cat_code
            break

    if not cycle or not category:
        return render(request, 'reviews/claim_error.html', {
            'error': _('Invalid or expired invitation link.')
        }, status=404)

    # The token exists for every category, but the cycle may not collect this
    # one — a link from an earlier mail must not reopen a category since
    # dropped, otherwise the report gains answers it does not report on.
    if not cycle.collects(category):
        return render(request, 'reviews/claim_error.html', {
            'error': _('This feedback cycle no longer collects this kind of review.')
        }, status=404)

    # If coming from redirect page (has force_claim param), skip localStorage check
    if request.GET.get('force_claim'):
        if category == 'self':
            # A cycle has one self-assessment; the link opens it instead of starting another.
            return redirect('reviews:feedback_form', token=self_assessment_token(cycle).token)

        # Get available tokens (not claimed, not completed, and NOT assigned to an email)
        # This prevents invite links from claiming tokens meant for specific email invitations
        available_tokens = list(
            ReviewerToken.objects.filter(
                cycle=cycle,
                category=category,
                claimed_at__isnull=True,
                completed_at__isnull=True,
                reviewer_email__isnull=True  # Only claim tokens without email assignments
            )
        )

        if not available_tokens:
            # No available tokens - create a new one dynamically
            try:
                token = ReviewerToken.objects.create(
                    cycle=cycle,
                    category=category,
                    claimed_at=timezone.now()
                )
            except ReviewerLimit:
                return render(request, 'reviews/claim_error.html', {
                    'error': _('This feedback round has reached its maximum number of reviewers. '
                               'Contact the person who sent you this link.')
                }, status=404)
        else:
            # Cryptographically randomly select a token from available ones
            token = secrets.choice(available_tokens)
            # Mark as claimed immediately
            token.claimed_at = timezone.now()
            token.save()

        # Redirect to feedback form
        return redirect('reviews:feedback_form', token=token.token)

    # Show redirect page that checks localStorage first
    return render(request, 'reviews/claim_redirect.html', {
        'invitation_token': str(invitation_token),
        'category': category,
    })


def feedback_form(request, token):
    """Token-based feedback form view"""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)
    activate_token_language(request, reviewer_token)

    # Check if already completed
    if reviewer_token.is_completed:
        return render(request, 'reviews/feedback_complete.html', {
            'token': reviewer_token,
            'cycle': reviewer_token.cycle,
        })

    cycle = reviewer_token.cycle

    # Check if the cycle is closed/completed
    if cycle.status == 'completed':
        return render(request, 'reviews/claim_error.html', {
            'error': _('This review cycle has been closed. Feedback can no longer be submitted.')
        }, status=410)

    # Mark token as claimed on first access (for email-invited users)
    if reviewer_token.claimed_at is None:
        reviewer_token.claimed_at = timezone.now()
        reviewer_token.save(update_fields=['claimed_at'])

    questionnaire = cycle.questionnaire.translated()

    # Get existing responses for this token
    existing_responses = {}
    if request.method == 'GET':
        responses = Response.objects.filter(token=reviewer_token).select_related('question')
        existing_responses = {
            str(r.question.id): (
                'did_not_observe'
                if r.answer_data.get('did_not_observe')
                else r.answer_data.get('value')
            )
            for r in responses
        }

    # Get invitation token for localStorage key
    invitation_token = cycle.get_invitation_token(reviewer_token.category)

    context = {
        'token': reviewer_token,
        'cycle': cycle,
        'questionnaire': questionnaire,
        'sections': questionnaire.sections.all(),
        'reviewee': cycle.reviewee,
        'existing_responses': existing_responses,
        'invitation_token': invitation_token,
    }

    return render(request, 'reviews/feedback_form.html', context)


@require_http_methods(["POST"])
@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def submit_feedback(request, token):
    """Handle feedback form submission"""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)
    activate_token_language(request, reviewer_token)

    # Check if already completed
    if reviewer_token.is_completed:
        return JsonResponse({'error': _('Feedback already submitted')}, status=400)

    cycle = reviewer_token.cycle

    # Check if the cycle is closed/completed
    if cycle.status == 'completed':
        return JsonResponse({'error': _('This review cycle has been closed. Feedback can no longer be submitted.')}, status=410)

    questionnaire = cycle.questionnaire

    # Get all questions for validation, translated because the error messages quote them
    queryset = Question.objects.filter(section__questionnaire=questionnaire).prefetch_related(
        *Question.translation_lookups()
    )
    questions = [question.translated() for question in queryset]

    errors = []
    responses_to_save = []

    # Validate and prepare responses
    for question in questions:
        field_name = f'question_{question.id}'

        # Handle multiple_choice differently (get list of values)
        if question.question_type == 'multiple_choice':
            answer_values = request.POST.getlist(field_name)
            # Filter out empty strings
            answer_values = [v.strip() for v in answer_values if v.strip()]

            # Check required fields
            if question.required and not answer_values:
                errors.append(_('Question "%(question)s" is required') % {'question': question.short_text})
                continue

            # Skip empty optional fields
            if not answer_values:
                continue

            options = list(question.options.all())
            resolved = [resolve_answer(options, answer) for answer in answer_values]

            if None in resolved:
                errors.append(_('Invalid option for question "%(question)s"') % {'question': question.short_text})
                continue

            answer_data = {'value': resolved}
        else:
            # For all other question types (single value)
            answer_value = request.POST.get(field_name, '').strip()

            # Check required fields
            if question.required and not answer_value:
                errors.append(_('Question "%(question)s" is required') % {'question': question.short_text})
                continue

            # Skip empty optional fields
            if not answer_value:
                continue

            # Validate based on question type
            if question.question_type == 'rating':
                # Accept an explicit non-numeric response when the behaviour
                # was not observed; otherwise validate the numeric rating.
                if answer_value == 'did_not_observe':
                    answer_data = {
                        'value': None,
                        'did_not_observe': True,
                    }
                else:
                    try:
                        rating = int(answer_value)
                        min_val = int((question.config or {}).get('min', 1))
                        max_val = int((question.config or {}).get('max', 5))
                        if rating < min_val or rating > max_val:
                            errors.append(_('Rating must be between %(min)s and %(max)s') % {'min': min_val, 'max': max_val})
                            continue
                        answer_data = {'value': rating}
                    except (TypeError, ValueError):
                        errors.append(_('Invalid rating value'))
                        continue
            elif question.question_type == 'scale':
                try:
                    scale_value = int(answer_value)
                    min_val = question.config.get('min', 1)
                    max_val = question.config.get('max', 100)
                    if scale_value < min_val or scale_value > max_val:
                        errors.append(_('Scale value must be between %(min)s and %(max)s') % {'min': min_val, 'max': max_val})
                        continue
                    answer_data = {'value': scale_value}
                except ValueError:
                    errors.append(_('Invalid scale value'))
                    continue
            elif question.question_type in OPTION_TYPES:
                option_id = resolve_answer(list(question.options.all()), answer_value)

                if option_id is None:
                    errors.append(_('Invalid option for question "%(question)s"') % {'question': question.short_text})
                    continue

                answer_data = {'value': option_id}
            else:
                answer_data = {'value': answer_value}

        responses_to_save.append({
            'cycle': cycle,
            'question': question,
            'token': reviewer_token,
            'category': reviewer_token.category,
            'answer_data': answer_data,
        })

    if errors:
        return JsonResponse({'errors': errors}, status=400)

    # Save all responses in a transaction
    try:
        with transaction.atomic():
            # Delete existing responses for this token
            Response.objects.filter(token=reviewer_token).delete()

            # Create new responses
            for response_data in responses_to_save:
                Response.objects.create(**response_data)

            # Mark token as completed
            reviewer_token.completed_at = timezone.now()
            reviewer_token.save()

            # Send feedback.submitted webhook
            from api.webhooks import send_webhook
            send_webhook(
                organization=cycle.reviewee.organization,
                event_type="feedback.submitted",
                payload={
                    "cycle_id": str(cycle.uuid),
                    "category": reviewer_token.category,
                    "submitted_at": reviewer_token.completed_at.isoformat(),
                },
            )

            # Check if all tokens are completed
            # Only auto-close when every token has a reviewer_email (email-assigned cycle).
            # Invite-link cycles (tokens without emails) stay open for new reviewers.
            all_tokens = cycle.tokens.all()
            has_open_invite = all_tokens.filter(reviewer_email__isnull=True).exists()
            all_tokens_completed = (
                not has_open_invite
                and not all_tokens.filter(completed_at__isnull=True).exists()
            )

            if all_tokens_completed and cycle.status == 'active':
                # Auto-close the cycle. The finalize_reports cron makes the report and emails it,
                # so the last submit is as fast as the first.
                cycle.status = 'completed'
                cycle.save()

                from notifications.lifecycle import send_cycle_summary
                send_cycle_summary(cycle)

        return JsonResponse({'success': True, 'redirect': f'/feedback/{token}/complete/'})

    except Exception as e:
        logger.exception('Error submitting feedback')
        return JsonResponse({'error': _('Something went wrong. Please try again.')}, status=500)


def feedback_complete(request, token):
    """Confirmation page after feedback submission"""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)
    activate_token_language(request, reviewer_token)

    if not reviewer_token.is_completed:
        return redirect('feedback_form', token=token)

    return render(request, 'reviews/feedback_complete.html', {
        'token': reviewer_token,
        'cycle': reviewer_token.cycle,
    })


@require_http_methods(["POST"])
def feedback_language(request, token):
    """The language switcher on the form: the reviewer's choice is stored on the token."""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)
    language = request.POST.get('language')

    if is_language(language):
        reviewer_token.language = language
        reviewer_token.save(update_fields=['language'])

    return redirect('reviews:feedback_form', token=token)


@ratelimit(key='ip', rate='5/h', method='POST', block=True)
def feedback_overview(request, signed):
    """Every form one reviewer has to fill in, from the link in the bundled invitation.

    The link carries the address and the organization, signed. It shows only this person's own
    forms: no other reviewers, no results. An expired link offers to mail a new one; a POST sends
    it, but only says that it did when the address has forms, so the page does not tell who is a
    reviewer.
    """
    try:
        data = signing.loads(signed, salt='feedback-overview', max_age=OVERVIEW_LINK_MAX_AGE)
        expired = False
    except signing.SignatureExpired:
        data = signing.loads(signed, salt='feedback-overview')
        expired = True
    except signing.BadSignature:
        raise Http404

    organization = get_object_or_404(Organization, pk=data['o'])
    tokens = list(
        ReviewerToken.objects
        .filter(reviewer_email__iexact=data['e'], cycle__reviewee__organization=organization)
        .select_related('cycle__reviewee', 'cycle__questionnaire')
        .order_by('cycle__reviewee__name', 'cycle__questionnaire__name')
    )

    language = request_language(request, *(t.language for t in tokens[:1]), organization=organization)
    translation.activate(language)
    request.LANGUAGE_CODE = language

    if expired:
        sent = request.method == 'POST'
        if sent and tokens:
            send_overview_link_email(data['e'], organization, language)
        return render(request, 'reviews/feedback_overview_expired.html', {
            'sent': sent,
            'days': OVERVIEW_LINK_MAX_AGE.days,
        })

    items = []
    for token in tokens:
        if token.is_completed:
            state = 'done'
        elif token.cycle.status != 'active':
            state = 'closed'
        elif token.claimed_at:
            state = 'continue'
        else:
            state = 'start'
        items.append({
            'token': token,
            'questionnaire_name': token.cycle.questionnaire.translated().name,
            'relation': reviewer_relation(token.category),
            'minutes': estimated_minutes(token.cycle.questionnaire),
            'state': state,
        })
    items.sort(key=lambda item: item['state'] in ('done', 'closed'))

    open_items = [item for item in items if item['state'] in ('start', 'continue')]
    return render(request, 'reviews/feedback_overview.html', {
        'items': items,
        'self_items': [item for item in items if item['token'].category == 'self'],
        'other_items': [item for item in items if item['token'].category != 'self'],
        'done_count': sum(1 for item in items if item['state'] == 'done'),
        'total_count': sum(1 for item in items if item['state'] != 'closed'),
        'open_minutes': sum(item['minutes'] or 0 for item in open_items),
    })
