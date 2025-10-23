from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
from .models import ReviewerToken, Response
from questionnaires.models import Question


def feedback_form(request, token):
    """Token-based feedback form view"""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)

    # Check if already completed
    if reviewer_token.is_completed:
        return render(request, 'reviews/feedback_complete.html', {
            'token': reviewer_token,
            'cycle': reviewer_token.cycle,
        })

    cycle = reviewer_token.cycle
    questionnaire = cycle.questionnaire

    # Get all sections with questions
    sections = questionnaire.sections.prefetch_related('questions').all()

    # Get existing responses for this token
    existing_responses = {}
    if request.method == 'GET':
        responses = Response.objects.filter(token=reviewer_token).select_related('question')
        existing_responses = {str(r.question.id): r.answer_data.get('value') for r in responses}

    context = {
        'token': reviewer_token,
        'cycle': cycle,
        'questionnaire': questionnaire,
        'sections': sections,
        'reviewee': cycle.reviewee,
        'existing_responses': existing_responses,
    }

    return render(request, 'reviews/feedback_form.html', context)


@require_http_methods(["POST"])
def submit_feedback(request, token):
    """Handle feedback form submission"""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)

    # Check if already completed
    if reviewer_token.is_completed:
        return JsonResponse({'error': 'Feedback already submitted'}, status=400)

    cycle = reviewer_token.cycle
    questionnaire = cycle.questionnaire

    # Get all questions for validation
    questions = Question.objects.filter(section__questionnaire=questionnaire)

    errors = []
    responses_to_save = []

    # Validate and prepare responses
    for question in questions:
        field_name = f'question_{question.id}'
        answer_value = request.POST.get(field_name, '').strip()

        # Check required fields
        if question.required and not answer_value:
            errors.append(f'Question "{question.question_text[:50]}" is required')
            continue

        # Skip empty optional fields
        if not answer_value:
            continue

        # Validate based on question type
        if question.question_type == 'rating':
            try:
                rating = int(answer_value)
                min_val = question.config.get('min', 1)
                max_val = question.config.get('max', 5)
                if rating < min_val or rating > max_val:
                    errors.append(f'Rating must be between {min_val} and {max_val}')
                    continue
                answer_data = {'value': rating}
            except ValueError:
                errors.append(f'Invalid rating value')
                continue
        else:
            # text or multiple_choice
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

        return JsonResponse({'success': True, 'redirect': f'/feedback/{token}/complete/'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def feedback_complete(request, token):
    """Confirmation page after feedback submission"""
    reviewer_token = get_object_or_404(ReviewerToken, token=token)

    if not reviewer_token.is_completed:
        return redirect('feedback_form', token=token)

    return render(request, 'reviews/feedback_complete.html', {
        'token': reviewer_token,
        'cycle': reviewer_token.cycle,
    })
