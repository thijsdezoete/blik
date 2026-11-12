from django.shortcuts import render, redirect
from django.http import FileResponse, Http404, HttpResponse
from django.conf import settings
from django.urls import reverse
from django.contrib import messages
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django_ratelimit.decorators import ratelimit
import uuid
import logging
from .seo import generate_og_image
from .api_client import api_client, BlikAPIError
from .dreyfus_helpers import calculate_preview_results

logger = logging.getLogger(__name__)


def _get_view_name(view_name):
    """
    Get the correct view name for redirect/reverse based on context.

    In standalone landing container: 'index'
    In main app: 'landing:index'
    """
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'
    if is_standalone:
        return view_name
    else:
        return f'landing:{view_name}'


def index(request):
    """SEO-optimized landing page for Blik."""
    from .review_api import get_review_data_from_api

    # Fetch review data from main app API (works across containers)
    rating_data = get_review_data_from_api()

    context = {
        'site_description': settings.SITE_DESCRIPTION,
        'site_keywords': settings.SITE_KEYWORDS,
        'rating_data': rating_data,
    }
    return render(request, 'landing/index.html', context)


def og_image(request):
    """Generate Open Graph image dynamically with page-specific content."""
    # Get custom title and subtitle from query params, or use defaults
    title = request.GET.get('title', settings.SITE_NAME)
    subtitle = request.GET.get('subtitle', 'Open Source 360° Feedback Platform')

    image_buffer = generate_og_image(
        title=title,
        subtitle=subtitle
    )
    return HttpResponse(image_buffer.getvalue(), content_type='image/png')


def open_source(request):
    """Open source landing page for developer audience."""
    return render(request, 'landing/open_source.html')


def dreyfus_model(request):
    """Dreyfus Model and competency framework explanation page."""
    return render(request, 'landing/dreyfus_model.html')


def eu_tech(request):
    """EU/GDPR-focused landing page for European tech companies."""
    return render(request, 'landing/eu_tech.html')


def privacy(request):
    """Air-gapped/privacy-focused landing page for professional services."""
    from .review_api import get_review_data_from_api

    # Fetch review data from main app API (works across containers)
    rating_data = get_review_data_from_api()

    context = {
        'rating_data': rating_data,
    }
    return render(request, 'landing/privacy.html', context)


def privacy_policy(request):
    """Privacy policy page."""
    return render(request, 'landing/privacy_policy.html')


def terms(request):
    """Terms of service page."""
    return render(request, 'landing/terms.html')


def hr_managers(request):
    """HR manager focused landing page for growing teams (30-50 employees)."""
    return render(request, 'landing/hr_managers.html')


def agency_levels(request):
    """5 Levels of Agency framework page for high-agency workplace culture."""
    return render(request, 'landing/agency_levels.html')


def performance_matrix(request):
    """Performance Matrix page combining Dreyfus Model with Agency Levels."""
    return render(request, 'landing/performance_matrix.html')


def portfolio_strategy(request):
    """Portfolio Strategy page - matching employee archetypes to work type quadrants."""
    return render(request, 'landing/portfolio_strategy.html')


def signup(request):
    """Signup page. The main app creates the Stripe Checkout session."""
    context = {
        # Every €19 CTA links here with ?plan=single to highlight that card
        'selected_plan': request.GET.get('plan', '')
        if request.GET.get('plan') in ('single', 'enterprise') else '',
    }
    return render(request, 'landing/signup.html', context)


def vs_lattice(request):
    """Blik vs Lattice comparison page."""
    return render(request, 'landing/vs_lattice.html')


def vs_culture_amp(request):
    """Blik vs Culture Amp comparison page."""
    return render(request, 'landing/vs_culture_amp.html')


def vs_15five(request):
    """Blik vs 15Five comparison page."""
    return render(request, 'landing/vs_15five.html')


def vs_orangehrm(request):
    """Blik vs OrangeHRM comparison page."""
    return render(request, 'landing/vs_orangehrm.html')


def vs_odoo(request):
    """Blik vs Odoo HR comparison page."""
    return render(request, 'landing/vs_odoo.html')


def vs_engagedly(request):
    """Blik vs Engagedly comparison page."""
    return render(request, 'landing/vs_engagedly.html')


def vs_small_improvements(request):
    """Blik vs Small Improvements comparison page."""
    return render(request, 'landing/vs_small_improvements.html')


def why_blik(request):
    """Why Blik exists - comprehensive differentiation page."""
    return render(request, 'landing/why_blik.html')


def developers(request):
    """Developer-focused landing page with API documentation and quickstart."""
    # main_app_url, API URLs, site_name, site_domain, site_protocol now provided by context processor
    return render(request, 'landing/developers.html')


def people_analytics(request):
    """People analytics landing page showcasing role-specific questionnaires."""
    return render(request, 'landing/people_analytics.html')


def about(request):
    """About page - who built Blik and why."""
    return render(request, 'landing/about.html')


def how_it_works(request, audience):
    """Start-to-finish walkthrough; same content, one layout per audience (hr, developers)."""
    from .how_it_works import context
    return render(request, f'landing/how_it_works_{audience}.html', context())


def pricing(request):
    """Pricing page - transparent, indexed pricing information."""
    return render(request, 'landing/pricing.html')


def one_time_360_review(request):
    """Single Round page: one hosted review round, paid once."""
    return render(request, 'landing/one_time_360_review.html')


def faq(request):
    """FAQ hub page - comprehensive frequently asked questions."""
    return render(request, 'landing/faq.html')


def alternatives(request):
    """Alternatives comparison hub - compare Blik to all competitors."""
    return render(request, 'landing/alternatives.html')


def _compare_tools():
    """Every tool in the tables, Blik included, A–Z, each with the URL of its page."""
    from .competitors import VENDORS, BLIK
    tools = [{**v, 'url': reverse(_get_view_name('compare_tool'), args=[v['slug']])} for v in VENDORS]
    tools.append({**BLIK, 'url': reverse(_get_view_name('pricing'))})
    return sorted(tools, key=lambda t: t['name'].lower())


def _and_list(names):
    """['A', 'B', 'C'] -> 'A, B and C'."""
    return ' and '.join([', '.join(names[:-1]), names[-1]]) if len(names) > 1 else ''.join(names)


def compare(request):
    """Reference table of 360 feedback tools: key facts, cost for 50 people, FAQ."""
    from .competitors import GROUPS, SCENARIO, VENDORS, CHECKED, CHECKED_ISO
    tools = _compare_tools()
    n = len(tools)
    url_by_name = {t['name']: t['url'] for t in tools}

    def names(test):
        return [t['name'] for t in tools if test(t['flags'])]

    priced = names(lambda f: f['published_price'])
    standalone = names(lambda f: f['standalone_360'])
    eu_default = names(lambda f: f['eu_hosting'] == 'default')
    eu_option = names(lambda f: f['eu_hosting'] == 'option')
    ai_yes = names(lambda f: f['ai_on_feedback'] in ('yes', 'opt-in'))
    ai_no = names(lambda f: f['ai_on_feedback'] == 'no')
    certified = names(lambda f: f['certified'] == 'yes')
    quote_only = sorted(v['name'] for v in VENDORS if v['pricing']['sort_eur_50'] is None)
    hosted = [row for row in SCENARIO if row['sort'] > 0]  # leaves out the €0 self-hosted licence
    cheapest, dearest = hosted[0], hosted[-1]
    price_range = (f"For 50 reviewed employees, published list prices go from {cheapest['cost']} ({cheapest['name']}) "
                   f"to {dearest['cost']} ({dearest['name']}) a year, licence only.")

    facts = [
        f"{len(priced)} of the {n} tools publish a full price. The others sell on quote, or publish only part of the price.",
        price_range,
        f"{len(standalone)} of the {n} tools sell 360 feedback on its own. The others sell it inside a larger suite or plan.",
        f"{len(eu_default)} tools store data in the EU by default. {len(eu_option)} more offer an EU region.",
        f"{len(ai_yes)} tools use AI on feedback, for summaries, drafting or analysis. For {len(ai_no)} we found none."
        + (f" {n - len(ai_yes) - len(ai_no)} do not say." if n - len(ai_yes) - len(ai_no) else ""),
        f"{len(certified)} tools hold ISO 27001 or a SOC 2 report of their own.",
    ]
    faq = [
        ("How much does 360 feedback software cost for 50 employees?",
         f"{price_range} {len(quote_only)} tools sell on quote only: {_and_list(quote_only)}."),
        ("Which 360 feedback tools store data in the EU by default?",
         f"{_and_list(eu_default)}." + (f" {_and_list(eu_option)} offer an EU region as an option." if eu_option else "")),
        ("Which 360 feedback tools do not use AI on feedback?",
         f"We found no AI on feedback for {_and_list(ai_no)}. {len(ai_yes)} of the {n} tools use AI on feedback, "
         "for example for summaries or drafted reviews."),
        ("Which 360 feedback tools have ISO 27001 or SOC 2?",
         f"{_and_list(certified)} hold ISO 27001 or a SOC 2 report of their own."),
        ("Can I buy 360 feedback without a full HR or performance suite?",
         f"Yes. {_and_list(standalone)} sell 360 feedback on its own."),
    ]
    return render(request, 'landing/compare.html', {
        'groups': [
            {'key': key, 'title': title, 'intro': intro, 'tools': [t for t in tools if t['group'] == key]}
            for key, title, intro in GROUPS
        ],
        'scenario': [{**row, 'url': reverse(_get_view_name(row['page'])) if 'page' in row else url_by_name.get(row['name'])}
                     for row in SCENARIO],
        'tool_count': n, 'facts': facts, 'faq': faq,
        'quote_only': quote_only, 'ai_no': ai_no, 'certified': certified,
        'checked': CHECKED, 'checked_iso': CHECKED_ISO,
    })


_FEATURE_LABELS = [
    ('Raters', 'raters'), ('Choosing raters', 'nomination'), ('Anonymity', 'anonymity'),
    ('Questions', 'questions'), ('Reports', 'reports'), ('Languages', 'languages'),
    ('Integrations', 'integrations'), ('AI', 'ai'),
]
_SECURITY_LABELS = [
    ('Hosting', 'hosting'), ('Certificates', 'certificates'),
    ('AI providers', 'ai_subprocessors'), ('GDPR', 'gdpr'),
]


def compare_tool(request, slug):
    """One tool: summary, pricing, how its 360 works, data and security, FAQ, sources."""
    from django.http import Http404
    from .competitors import BY_SLUG, GROUPS, CHECKED, CHECKED_ISO
    v = BY_SLUG.get(slug)
    if v is None:
        raise Http404
    group = next(g for g in GROUPS if g[0] == v['group'])
    cost_50 = v['pricing']['cost']['50']['cost']
    lead = (f"{v['name']} 360 feedback for 50 employees: {cost_50} a year." if cost_50
            else f"{v['name']} 360 feedback: price on quote only.")
    return render(request, 'landing/compare_tool.html', {
        'v': v,
        'costs': [(size, v['pricing']['cost'][size]) for size in ('10', '50', '200')],
        'features': [(label, v['features'][key]) for label, key in _FEATURE_LABELS],
        'security': [(label, v['security'][key]) for label, key in _SECURITY_LABELS],
        'others': [t for t in _compare_tools() if t['group'] == v['group'] and t['slug'] != slug],
        'group_title': group[1], 'group_intro': group[2],
        'meta_description': f"{lead} How it is sold, anonymity, AI, EU hosting and certificates, with sources. Checked {CHECKED}.",
        'checked': CHECKED, 'checked_iso': CHECKED_ISO, 'checked_year': CHECKED_ISO[:4],
    })


def free_360_tools(request):
    """Free 360 feedback tools comparison page."""
    return render(request, 'landing/free_360_tools.html')


def roi_calculator(request):
    """ROI calculator - interactive savings calculator vs competitors."""
    return render(request, 'landing/roi_calculator.html')


# =============================================================================
# GROWTH HACK: Developer Skills Assessment
# =============================================================================

def dreyfus_assessment_start(request):
    """
    Landing page for Developer Skills Assessment.

    Fetches the questionnaire from main app API and renders it as an
    interactive form on the landing page (blik360.com).

    GET /dreyfus-assessment/
    """
    try:
        # Get questionnaire UUID from settings
        questionnaire_uuid = getattr(settings, 'GROWTH_QUESTIONNAIRE_UUID', None)

        if not questionnaire_uuid:
            logger.error("GROWTH_QUESTIONNAIRE_UUID not configured")
            return render(request, 'landing/dreyfus_assessment_unavailable.html', {
                'error_message': 'The assessment is currently being configured. Please check back soon.'
            })

        # Fetch questionnaire from main app API
        questionnaire_data = api_client.get_questionnaire(questionnaire_uuid)

        context = {
            'questionnaire': questionnaire_data,
            'total_questions': sum(
                len([q for q in section.get('questions', []) if q.get('required')])
                for section in questionnaire_data.get('sections', [])
            ),
        }

        return render(request, 'landing/dreyfus_assessment.html', context)

    except BlikAPIError as e:
        logger.error(f"API error fetching questionnaire: {str(e)}")
        return render(request, 'landing/dreyfus_assessment_unavailable.html', {
            'error_message': 'Unable to connect to our assessment service. Please try again in a few minutes.'
        })
    except Exception as e:
        logger.exception(f"Unexpected error in dreyfus_assessment_start: {str(e)}")
        return render(request, 'landing/dreyfus_assessment_unavailable.html', {
            'error_message': 'An unexpected error occurred while loading the assessment.'
        })


@ratelimit(key='ip', rate='10/h', method='POST', block=True)
def dreyfus_assessment_submit(request):
    """
    Process questionnaire submission and show preview results.

    Backend workflow:
    1. Collect answers from POST data
    2. Create reviewee (with temp email) via API
    3. Create review cycle via API
    4. Submit responses via API
    5. Calculate preview results (client-side)
    6. Store cycle UUID in session
    7. Render results preview with email capture form

    POST /dreyfus-assessment/submit/
    """
    if request.method != 'POST':
        return redirect(_get_view_name('dreyfus_assessment_start'))

    try:
        # Extract answers from POST data
        # Format: question_{uuid}=4, question_{uuid}=3, etc.
        answers = {}
        for key, value in request.POST.items():
            if key.startswith('question_'):
                try:
                    question_uuid = key.replace('question_', '')
                    # Handle both rating (int) and text (string) responses
                    if value.isdigit():
                        answers[question_uuid] = int(value)
                    else:
                        answers[question_uuid] = value
                except (ValueError, AttributeError):
                    continue

        # Validate we have enough required answers (at least 10 rating answers)
        required_count = sum(1 for ans in answers.values() if isinstance(ans, int))
        if required_count < 10:
            messages.error(request, "Please answer all required questions.")
            return redirect(_get_view_name('dreyfus_assessment_start'))

        # Get configuration
        growth_questionnaire_uuid = getattr(settings, 'GROWTH_QUESTIONNAIRE_UUID', None)

        if not growth_questionnaire_uuid:
            messages.error(request, "Assessment is not properly configured.")
            return redirect(_get_view_name('index'))

        # Create temporary reviewee (email will be updated later)
        # Organization is auto-set from API token
        temp_id = str(uuid.uuid4())[:8]
        reviewee_data = api_client.create_reviewee(
            name=f"Assessment User #{temp_id}",
            email=f"pending+{temp_id}@blik360.com",
        )
        reviewee_uuid = reviewee_data['uuid']

        # Create self-assessment cycle
        cycle_data = api_client.create_cycle(
            reviewee_uuid=reviewee_uuid,
            questionnaire_uuid=growth_questionnaire_uuid,
            send_invitations=False
        )
        cycle_uuid = cycle_data['uuid']

        # Extract self-assessment token from creation response
        logger.debug(f"Cycle creation response keys: {list(cycle_data.keys())}")
        logger.debug(f"Tokens in cycle: {cycle_data.get('tokens', [])}")

        self_token = None
        for token in cycle_data.get('tokens', []):
            if token.get('category') == 'self':
                self_token = token.get('uuid')
                logger.debug(f"Found self-assessment token: {self_token}")
                break

        if not self_token:
            logger.error(f"No self-assessment token found in cycle creation response!")

        # Calculate preview results
        rating_answers = {qid: val for qid, val in answers.items() if isinstance(val, int)}
        preview = calculate_preview_results(rating_answers)

        # Store data in session for email capture step
        # We'll submit responses when email is captured to ensure we have real user info
        request.session['assessment_cycle_uuid'] = cycle_uuid
        request.session['assessment_reviewee_uuid'] = reviewee_uuid
        request.session['assessment_preview'] = preview
        request.session['assessment_answers'] = answers  # Store answers for later submission
        request.session['assessment_self_token'] = self_token  # Store token for response submission
        logger.debug(f"Stored in session - cycle: {cycle_uuid}, reviewee: {reviewee_uuid}, self_token: {self_token}, session_key: {request.session.session_key}")

        context = {
            'preview': preview,
            'cycle_uuid': cycle_uuid,
        }

        return render(request, 'landing/dreyfus_results_preview.html', context)

    except BlikAPIError as e:
        logger.error(f"API error during assessment submission: {str(e)}")
        messages.error(request, f"Error submitting assessment: {str(e)}")
        return redirect(_get_view_name('dreyfus_assessment_start'))
    except Exception as e:
        logger.exception(f"Unexpected error in dreyfus_assessment_submit: {str(e)}")
        messages.error(request, "An error occurred processing your assessment. Please try again.")
        return redirect(_get_view_name('dreyfus_assessment_start'))


@ratelimit(key='ip', rate='5/h', method='POST', block=True)
def dreyfus_capture_email(request):
    """
    Capture email, update reviewee, complete cycle, and send report.

    Backend workflow:
    1. Get email from POST data
    2. Retrieve cycle/reviewee UUIDs from session
    3. Update reviewee email via API
    4. Complete cycle (triggers report generation) via API
    5. Show success confirmation

    POST /dreyfus-assessment/capture-email/
    """
    if request.method != 'POST':
        return redirect(_get_view_name('dreyfus_assessment_start'))

    try:
        # Get email from form
        email = request.POST.get('email', '').strip()
        subscribe_newsletter = request.POST.get('subscribe_newsletter') == 'on'

        # Validate email
        if not email or '@' not in email:
            messages.error(request, "Please provide a valid email address.")
            return redirect(_get_view_name('dreyfus_assessment_start'))

        # Get cycle/reviewee from session
        cycle_uuid = request.session.get('assessment_cycle_uuid')
        reviewee_uuid = request.session.get('assessment_reviewee_uuid')
        preview = request.session.get('assessment_preview', {})
        answers = request.session.get('assessment_answers', {})
        self_token = request.session.get('assessment_self_token')

        logger.debug(f"Email capture - cycle_uuid: {cycle_uuid}, reviewee_uuid: {reviewee_uuid}, self_token: {self_token}, session_key: {request.session.session_key}")

        if not cycle_uuid or not reviewee_uuid:
            logger.error(f"Session data missing - cycle: {cycle_uuid}, reviewee: {reviewee_uuid}")
            messages.error(request, "Session expired. Please take the assessment again.")
            return redirect(_get_view_name('dreyfus_assessment_start'))

        # Update reviewee with real email
        name = email.split('@')[0].replace('.', ' ').replace('_', ' ').title()

        try:
            api_client.update_reviewee(
                reviewee_uuid=reviewee_uuid,
                email=email,
                name=name
            )
        except BlikAPIError as e:
            # If email already exists, that's okay - user is retaking the assessment
            # Just continue with the existing temp reviewee
            if 'already exists' in str(e).lower():
                logger.debug(f"Email {email} already has a reviewee, continuing with temp reviewee {reviewee_uuid}")
            else:
                raise

        # Submit responses before completing cycle
        if answers and self_token:
            responses = []
            for question_uuid, value in answers.items():
                # Submit all responses (rating and text)
                responses.append({
                    'question_uuid': question_uuid,
                    'value': value
                })

            if responses:
                logger.debug(f"Submitting {len(responses)} responses with token {self_token}")
                logger.debug(f"Response data: {responses[:3]}...")  # Log first 3
                try:
                    result = api_client.submit_responses(cycle_uuid, responses, token_uuid=self_token)
                    logger.debug(f"Response submission result: {result}")
                except Exception as e:
                    logger.exception(f"Error submitting responses: {str(e)}")
                    # Continue even if response submission fails
        else:
            logger.warning(f"Skipping response submission - answers: {bool(answers)}, token: {bool(self_token)}")

        # Complete cycle - this triggers report generation
        report_data = api_client.complete_cycle(cycle_uuid)
        logger.debug(f"Complete cycle response keys: {list(report_data.keys())}")

        # Get report URL from response
        report_url = report_data.get('report_url')

        # If report_url is relative, make it absolute
        if report_url and not report_url.startswith('http'):
            report_url = f"{settings.MAIN_APP_URL}{report_url}"

        logger.debug(f"Report URL: {report_url}")

        # Send custom assessment report email with preview results
        if report_url:
            try:
                email_context = {
                    'name': name,
                    'preview': preview,
                    'report_url': report_url,
                }

                html_message = render_to_string('emails/assessment_report.html', email_context)
                text_message = render_to_string('emails/assessment_report.txt', email_context)

                logger.debug(f"Attempting to send email to: {email}")
                send_mail(
                    subject='Your Developer Skills Assessment Results',
                    message=text_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    html_message=html_message,
                    fail_silently=False,
                )

                logger.debug(f"Assessment report email sent successfully to: {email}")
            except Exception as e:
                logger.exception(f"Error sending assessment email: {str(e)}")
                # Don't fail the request if email sending fails
        else:
            logger.warning(f"No report URL available, skipping email send")

        # Clear session data
        request.session.pop('assessment_cycle_uuid', None)
        request.session.pop('assessment_reviewee_uuid', None)
        request.session.pop('assessment_preview', None)
        request.session.pop('assessment_answers', None)
        request.session.pop('assessment_self_token', None)

        # Optional: Handle newsletter subscription
        if subscribe_newsletter:
            # TODO: Integrate with email marketing service (Mailchimp, etc.)
            logger.info(f"Newsletter subscription requested for: {email}")

        context = {
            'email': email,
            'report_url': report_url,
            'preview': preview,
        }

        return render(request, 'landing/dreyfus_email_captured.html', context)

    except BlikAPIError as e:
        logger.error(f"API error during email capture: {str(e)}")
        messages.error(request, f"Error sending report: {str(e)}")
        # Don't redirect - show error on current page
        return render(request, 'landing/dreyfus_results_preview.html', {
            'preview': request.session.get('assessment_preview', {}),
            'cycle_uuid': request.session.get('assessment_cycle_uuid'),
            'error': str(e)
        })
    except Exception as e:
        logger.exception(f"Unexpected error in dreyfus_capture_email: {str(e)}")
        messages.error(request, "An error occurred. Please try again.")
        return redirect(_get_view_name('dreyfus_assessment_start'))


def sample_report(request):
    """The sample report PDF, rendered into the image when the landing container is built."""
    path = settings.BASE_DIR / 'landing' / 'sample-report.pdf'
    if not path.exists():
        raise Http404
    return FileResponse(path.open('rb'), content_type='application/pdf', filename='blik-sample-report.pdf')
