"""
Management command to capture screenshots using Playwright.
Reads configuration from generate_screenshot_data output and captures screenshots
for the landing page.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import escape
from types import SimpleNamespace
import json
import os
import asyncio
from pathlib import Path


# Sample context for email previews. Names match generate_screenshot_data.
SAMPLE_URL = 'https://app.blik360.com'
SAMPLE_REVIEWEE = SimpleNamespace(name='Emma Davis', email='emma.davis@acme.example.com')
SAMPLE_CYCLE = SimpleNamespace(
    questionnaire=SimpleNamespace(name='Software Engineering 360 Review'),
)
SAMPLE_INVITE = f'{SAMPLE_URL}/feedback/invite/3f9c2a7e-5b1d-4e8a-9c6f-2d7b8e1a4c90/'
SAMPLE_FEEDBACK = f'{SAMPLE_URL}/feedback/8a1d4f6b-2c3e-4b7a-9d5f-6e0c1b2a3d4e/'

# (name, template, subject, recipient, context). Subjects match the senders in
# reviews/services.py, reports/services.py and core/email.py.
EMAIL_PREVIEWS = [
    ('email_welcome', 'emails/welcome',
     f'Welcome to {settings.SITE_NAME} - Your Account is Ready', 'admin@acme.example.com',
     {'user': SimpleNamespace(email='admin@acme.example.com', username='admin@acme.example.com'),
      'password': 'kT7#mQ2v', 'login_url': f'{SAMPLE_URL}/accounts/login/',
      'site_name': settings.SITE_NAME}),
    ('email_reviewee_self_assessment', 'emails/reviewee_self_assessment',
     'Your self-assessment: Software Engineering 360 Review', SAMPLE_REVIEWEE.email,
     {'reviewee': SAMPLE_REVIEWEE, 'cycle': SAMPLE_CYCLE, 'self_assessment_url': SAMPLE_INVITE}),
    ('email_reviewee_invitation_links', 'emails/reviewee_invitation_links',
     'Your links to share with reviewers: Software Engineering 360 Review', SAMPLE_REVIEWEE.email,
     {'reviewee': SAMPLE_REVIEWEE, 'cycle': SAMPLE_CYCLE,
      'peer_url': f'{SAMPLE_URL}/feedback/invite/b72e9d14-6a3c-4f58-8e21-c9d0a5f3b7e6/',
      'manager_url': f'{SAMPLE_URL}/feedback/invite/5d0f3a8c-91e7-4b2d-a6c4-e83f17b92d05/',
      'direct_report_url': f'{SAMPLE_URL}/feedback/invite/e4a19c7b-2f60-4d8e-b3a5-07c6d9f12e84/'}),
    ('email_reviewer_invitation', 'emails/reviewer_invitation',
     'Your feedback for Emma Davis', 'michael.chen@acme.example.com',
     {'reviewee_name': SAMPLE_REVIEWEE.name, 'category': 'Peer Review', 'feedback_url': SAMPLE_FEEDBACK,
      'questionnaire_name': SAMPLE_CYCLE.questionnaire.name, 'organization_name': 'Acme',
      'estimated_minutes': 15}),
    ('email_reviewer_reminder', 'emails/reviewer_reminder',
     'Your feedback for Emma Davis is still open', 'michael.chen@acme.example.com',
     {'reviewee_name': SAMPLE_REVIEWEE.name, 'category': 'Peer Review', 'feedback_url': SAMPLE_FEEDBACK,
      'questionnaire_name': SAMPLE_CYCLE.questionnaire.name, 'organization_name': 'Acme',
      'estimated_minutes': 15}),
    ('email_report_ready', 'emails/report_ready',
     'Your 360 feedback report is ready', SAMPLE_REVIEWEE.email,
     {'reviewee': SAMPLE_REVIEWEE, 'cycle': SAMPLE_CYCLE, 'response_count': 9,
      'report_url': f'{SAMPLE_URL}/my-report/c4e8b2a1-7d3f-4a6e-9b5c-1f2d3e4a5b6c/'}),
]

# Fill the cycle form so the shot shows a ready-to-submit round
CYCLE_FORM_JS = '''() => {
    const pick = (id, label) => {
        const sel = document.getElementById(id);
        const opt = Array.from(sel.options).find(o => o.text.includes(label)) || sel.options[1];
        sel.value = opt.value;
        sel.dispatchEvent(new Event('change'));
    };
    pick('reviewee', 'Emma Davis');
    pick('questionnaire', 'Software Engineering');
    toggleInviteForm();
    document.querySelector('[name="manager_emails"]').value = 'sarah.johnson@acme.example.com';
    document.querySelector('[name="peer_emails"]').value =
        ['michael.chen', 'emily.rodriguez', 'david.kim'].map(n => n + '@acme.example.com').join(', ');
}'''

# Width the email templates are laid out for (600px table plus 20px padding).
EMAIL_WIDTH = 640


def render_email_preview(template, subject, recipient, context, theme):
    """Render an email template inside a simple inbox frame (sender, subject, body)."""
    body = render_to_string(f'{template}.html', context)
    dark = theme == 'dark'
    bg, fg, muted, line = ('#111827', '#f9fafb', '#9ca3af', '#374151') if dark else \
        ('#ffffff', '#111827', '#6b7280', '#e5e7eb')
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html, body {{ margin: 0; height: 100%; background: {bg}; color: {fg};
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; }}
  body {{ display: flex; flex-direction: column; }}
  .head {{ max-width: 960px; width: 100%; margin: 0 auto; box-sizing: border-box; padding: 20px 16px 12px; }}
  .subject {{ font-size: 22px; font-weight: 600; margin: 0 0 16px; }}
  .from {{ display: flex; gap: 12px; align-items: center; }}
  .avatar {{ width: 40px; height: 40px; border-radius: 50%; flex: none; color: #fff; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
  .meta {{ font-size: 14px; color: {muted}; line-height: 1.5; min-width: 0; }}
  .meta strong {{ color: {fg}; }}
  .wrap {{ flex: 1; border-top: 1px solid {line}; overflow: hidden; }}
  iframe {{ display: block; border: 0; width: 100%; height: 100%; margin: 0 auto; transform-origin: 0 0; }}
</style></head><body>
<div class="head">
  <h1 class="subject">{escape(subject)}</h1>
  <div class="from">
    <div class="avatar">B</div>
    <div class="meta"><strong>{escape(settings.SITE_NAME)}</strong> &lt;noreply@blik360.com&gt;<br>
      to {escape(recipient)} &middot; 09:14</div>
  </div>
</div>
<div class="wrap"><iframe id="mail" srcdoc="{escape(body)}"></iframe></div>
<script>
  // Shrink to fit on narrow screens, like mobile mail apps do with fixed-width emails
  const f = document.getElementById('mail'), w = innerWidth;
  if (w < {EMAIL_WIDTH}) {{
    const s = w / {EMAIL_WIDTH};
    f.style.width = '{EMAIL_WIDTH}px';
    f.style.height = (f.parentElement.clientHeight / s) + 'px';
    f.style.transform = 'scale(' + s + ')';
  }}
</script>
</body></html>'''


class Command(BaseCommand):
    help = 'Capture screenshots using Playwright for landing page'

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            type=str,
            default='/tmp/blik_screenshot_config.json',
            help='Path to screenshot configuration JSON'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            default='static/img/screenshots',
            help='Output directory for screenshots'
        )
        parser.add_argument(
            '--base-url',
            type=str,
            default='http://localhost:8000',
            help='Base URL of the running application'
        )
        parser.add_argument(
            '--only',
            type=str,
            default='',
            help='Comma-separated name prefixes to capture (e.g. email_,cycle_create); default all'
        )

    def handle(self, *args, **options):
        config_path = options['config']
        output_dir = options['output_dir']
        base_url = options['base_url']
        self.only = [p for p in options['only'].split(',') if p]

        # Check if config exists
        if not os.path.exists(config_path):
            self.stdout.write(self.style.ERROR(
                f'Configuration file not found: {config_path}\n'
                f'Run: python manage.py generate_screenshot_data first'
            ))
            return

        # Load configuration
        with open(config_path, 'r') as f:
            config = json.load(f)

        self.stdout.write(f'Loaded configuration from: {config_path}')
        self.stdout.write(f'Organization: {config["organization_name"]}')
        self.stdout.write(f'Base URL: {base_url}')

        # Create output directory
        output_path = Path(settings.BASE_DIR) / output_dir
        output_path.mkdir(parents=True, exist_ok=True)
        self.stdout.write(f'Output directory: {output_path}')

        # Run async screenshot capture
        asyncio.run(self._capture_screenshots(config, base_url, output_path))

        self.stdout.write(self.style.SUCCESS('\nScreenshot capture complete!'))

    async def _capture_screenshots(self, config, base_url, output_path):
        """Async function to capture all screenshots"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.stdout.write(self.style.ERROR(
                'Playwright not installed. Run: pip install playwright && playwright install chromium'
            ))
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            # Login and get cookies
            self.stdout.write('Logging in as admin...')
            page = await browser.new_page()
            await page.goto(f'{base_url}/accounts/login/')
            await page.fill('input[name="username"]', config['admin_username'])
            await page.fill('input[name="password"]', config['admin_password'])
            await page.click('button[type="submit"]')
            await page.wait_for_load_state('networkidle')

            # Get cookies for reuse
            cookies = await page.context.cookies()

            # Define screenshot configurations
            screenshot_configs = []

            # Generate report screenshots for each questionnaire type
            questionnaire_cycles = config.get('questionnaire_cycles', {})
            report_tokens = config.get('report_tokens', {})

            for q_key, cycle_data in questionnaire_cycles.items():
                report_token = report_tokens.get(q_key)
                if not report_token:
                    self.stdout.write(self.style.WARNING(f'No report token for {q_key}, skipping'))
                    continue

                # Report overview - Desktop Light (top insights section)
                screenshot_configs.append({
                    'name': f'report_{q_key}_overview_light',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'scroll_to_element': '#overall-performance',
                    'scroll_element_position': 'start',
                })

                # Report overview - Desktop Dark
                screenshot_configs.append({
                    'name': f'report_{q_key}_overview_dark',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'scroll_to_element': '#overall-performance',
                    'scroll_element_position': 'start',
                })

                # Report charts - Desktop Light (radar chart section)
                screenshot_configs.append({
                    'name': f'report_{q_key}_charts_light',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'scroll_to_element': '#sectionRadarChart',
                    'scroll_element_position': 'center',
                })

                # Report charts - Desktop Dark
                screenshot_configs.append({
                    'name': f'report_{q_key}_charts_dark',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'scroll_to_element': '#sectionRadarChart',
                    'scroll_element_position': 'center',
                })

                # Report sections - Desktop Light (section-level performance with peer benchmarks)
                screenshot_configs.append({
                    'name': f'report_{q_key}_sections_light',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'scroll_to_element': '#section-level-performance',
                    'scroll_element_position': 'start',
                })

                # Report sections - Desktop Dark
                screenshot_configs.append({
                    'name': f'report_{q_key}_sections_dark',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'scroll_to_element': '#section-level-performance',
                    'scroll_element_position': 'start',
                })

                # Report details - Desktop Light (detailed feedback with questions/answers)
                screenshot_configs.append({
                    'name': f'report_{q_key}_details_light',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1200},
                    'theme': 'light',
                    'scroll_to_element': '#detailed-feedback',
                    'scroll_element_position': 'start',
                })

                # Report details - Desktop Dark
                screenshot_configs.append({
                    'name': f'report_{q_key}_details_dark',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1200},
                    'theme': 'dark',
                    'scroll_to_element': '#detailed-feedback',
                    'scroll_element_position': 'start',
                })

                # Dreyfus Profile - Desktop Light (skill level visualization)
                screenshot_configs.append({
                    'name': f'report_{q_key}_dreyfus_light',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1400},
                    'theme': 'light',
                    'scroll_to_element': '#skill-development-path',
                    'scroll_element_position': 'start',
                })

                # Dreyfus Profile - Desktop Dark
                screenshot_configs.append({
                    'name': f'report_{q_key}_dreyfus_dark',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1400},
                    'theme': 'dark',
                    'scroll_to_element': '#skill-development-path',
                    'scroll_element_position': 'start',
                })

                # Agency Profile - Desktop Light (agency level visualization)
                screenshot_configs.append({
                    'name': f'report_{q_key}_agency_light',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1400},
                    'theme': 'light',
                    'scroll_to_element': '#skill-development-path',
                    'scroll_element_position': 'start',
                    'click_element': 'button[data-tab="agency"]',
                })

                # Agency Profile - Desktop Dark
                screenshot_configs.append({
                    'name': f'report_{q_key}_agency_dark',
                    'url': f'{base_url}/my-report/{report_token}/',
                    'viewport': {'width': 1920, 'height': 1400},
                    'theme': 'dark',
                    'scroll_to_element': '#skill-development-path',
                    'scroll_element_position': 'start',
                    'click_element': 'button[data-tab="agency"]',
                })

            # Additional legacy screenshots using first completed cycle (for backward compatibility)
            if config.get('report_tokens'):
                first_token = list(config['report_tokens'].values())[0]

                # Legacy report screenshots
                screenshot_configs.extend([
                    # Report header - Desktop Light
                    {
                        'name': 'report_header_desktop_light',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': 'light',
                        'scroll_to': 0,
                    },
                    # Report header - Desktop Dark
                    {
                        'name': 'report_header_desktop_dark',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': 'dark',
                        'scroll_to': 0,
                    },
                    # Report charts - Desktop Light
                    {
                        'name': 'report_charts_desktop_light',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': 'light',
                        'scroll_to_element': '#sectionRadarChart',
                        'scroll_element_position': 'center',
                    },
                    # Report charts - Desktop Dark
                    {
                        'name': 'report_charts_desktop_dark',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': 'dark',
                        'scroll_to_element': '#sectionRadarChart',
                        'scroll_element_position': 'center',
                    },
                    # Report - Tablet Light
                    {
                        'name': 'report_tablet_light',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 1024, 'height': 768},
                        'theme': 'light',
                        'scroll_to_element': '#sectionRadarChart',
                        'scroll_element_position': 'start',
                    },
                    # Report - Tablet Dark
                    {
                        'name': 'report_tablet_dark',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 1024, 'height': 768},
                        'theme': 'dark',
                        'scroll_to_element': '#sectionRadarChart',
                        'scroll_element_position': 'start',
                    },
                ])
            # Dashboard and other admin screenshots
            screenshot_configs.extend([
                # Admin Dashboard - Desktop Light
                {
                    'name': 'dashboard_desktop_light',
                    'url': f'{base_url}/dashboard/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'wait_for': '.stats-grid',
                },
                # 8. Admin Dashboard - Desktop Dark
                {
                    'name': 'dashboard_desktop_dark',
                    'url': f'{base_url}/dashboard/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'wait_for': '.stats-grid',
                },
                # 9. Admin Dashboard - Mobile Light
                {
                    'name': 'dashboard_mobile_light',
                    'url': f'{base_url}/dashboard/',
                    'viewport': {'width': 375, 'height': 812},
                    'theme': 'light',
                    'wait_for': '.stats-grid',
                },
                # 10. Admin Dashboard - Mobile Dark
                {
                    'name': 'dashboard_mobile_dark',
                    'url': f'{base_url}/dashboard/',
                    'viewport': {'width': 375, 'height': 812},
                    'theme': 'dark',
                    'wait_for': '.stats-grid',
                },
                # 11. Review Cycle Detail - Desktop Light
                {
                    'name': 'cycle_detail_desktop_light',
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_uuid"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'wait_for': '.card',  # Wait for any card to appear (more reliable)
                },
                # 12. Review Cycle Detail - Desktop Dark
                {
                    'name': 'cycle_detail_desktop_dark',
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_uuid"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'wait_for': '.card',  # Wait for any card to appear (more reliable)
                },
                # 13. Team Management - Desktop Light
                {
                    'name': 'team_desktop_light',
                    'url': f'{base_url}/dashboard/team/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'wait_for': 'table',
                },
                # 14. Team Management - Desktop Dark
                {
                    'name': 'team_desktop_dark',
                    'url': f'{base_url}/dashboard/team/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'wait_for': 'table',
                },
                # Manage Invitations - Desktop Light
                {
                    'name': 'invitations_desktop_light',
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_uuid"]}/invitations/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'wait_for': '#inviteForm',
                },
                {
                    'name': 'invitations_desktop_dark',
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_uuid"]}/invitations/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'wait_for': '#inviteForm',
                },
            ])

            # "How Blik works" flow: sign up, configure, add reviewees, start a cycle
            flow_pages = [
                ('signup_desktop', '/landing/signup/', '.plans-grid', {}),
                ('questionnaires_desktop', '/dashboard/questionnaires/', 'table', {}),
                ('questionnaire_edit_desktop',
                 f'/dashboard/questionnaires/{config.get("questionnaire_id")}/edit/', '.container form', {}),
                ('questionnaire_translate_desktop',
                 f'/dashboard/questionnaires/{config.get("questionnaire_uuid")}/translate/de/', '.container form', {}),
                ('reviewees_desktop', '/dashboard/reviewees/', 'table', {}),
                # Sorting by gap switches on the self-vs-others column; skipped if
                # the column is not shown.
                ('reviewees_gap_desktop', '/dashboard/reviewees/?sort=gap', 'table',
                 {'skip_unless': '[data-reviewee-column="gap"]:not([hidden])'}),
                ('cycle_create_desktop', '/dashboard/cycles/create/', '#cycleForm',
                 {'prepare_js': CYCLE_FORM_JS, 'viewport': {'width': 1920, 'height': 1600}}),
            ]
            # Homepage "How it works" cards: one element per step, see _focus_clip()
            report_tokens = list(config.get('report_tokens', {}).values())
            step_cards = [
                ('step_people', '/dashboard/cycles/create/', '.card:has(#reviewee)',
                 {'prepare_js': CYCLE_FORM_JS}),
                ('step_answer', f'/feedback/{config.get("feedback_token")}/', '.section',
                 {}),
                ('step_report', f'/my-report/{report_tokens[0]}/' if report_tokens else None,
                 '.report-section:has(#sectionRadarChart)', {}),
            ]
            # Homepage hero: the report summary in a browser frame, and a phone
            # answering a question on top of it
            step_cards += [
                ('hero_report', step_cards[2][1], '#overall-performance',
                 {'focus_options': {'aspect': 16 / 10}}),
                ('hero_phone', step_cards[1][1], '.section',
                 {'viewport': {'width': 390, 'height': 844},
                  'focus_options': {'padding': 16, 'aspect': 390 / 720}}),
            ]
            for name, path, focus, extra in step_cards:
                if not path:
                    continue
                for theme in ('light', 'dark'):
                    screenshot_configs.append({
                        'name': f'{name}_{theme}',
                        'url': f'{base_url}{path}',
                        'viewport': {'width': 1000, 'height': 1000},
                        'scale': 2,
                        'theme': theme,
                        'wait_for': focus,
                        'focus': focus,
                        **extra,
                    })

            for name, path, wait_for, extra in flow_pages:
                for theme in ('light', 'dark'):
                    screenshot_configs.append({
                        'name': f'{name}_{theme}',
                        'url': f'{base_url}{path}',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': theme,
                        'wait_for': wait_for,
                        **extra,
                    })

            # Reviewee report on a phone (what the reviewee opens from the email)
            if config.get('report_tokens'):
                for theme in ('light', 'dark'):
                    screenshot_configs.append({
                        'name': f'report_mobile_{theme}',
                        'url': f'{base_url}/my-report/{first_token}/',
                        'viewport': {'width': 375, 'height': 812},
                        'theme': theme,
                        'wait_for': '#overall-performance',
                    })

            screenshot_configs = self._filter(screenshot_configs)

            # Capture screenshots
            for i, screenshot_config in enumerate(screenshot_configs, 1):
                self.stdout.write(f'\n[{i}/{len(screenshot_configs)}] Capturing: {screenshot_config["name"]}')

                # Create new page with viewport
                page = await browser.new_page(
                    viewport=screenshot_config['viewport'],
                    device_scale_factor=screenshot_config.get('scale', 1),
                )

                # Add cookies
                await page.context.add_cookies(cookies)

                # Set theme and dismiss welcome modal
                await page.add_init_script(f'''
                    localStorage.setItem('theme', '{screenshot_config['theme']}');
                    localStorage.setItem('blik_welcome_seen', 'true');
                ''')

                # Navigate to page
                await page.goto(screenshot_config['url'])

                # Wait for specific element
                if 'wait_for' in screenshot_config:
                    try:
                        await page.wait_for_selector(screenshot_config['wait_for'], timeout=15000)
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(
                            f'  Warning: Could not find selector {screenshot_config["wait_for"]}: {e}'
                        ))

                # Additional wait for charts/animations to fully render
                await page.wait_for_timeout(3000)

                # For report pages with charts, wait for Chart.js to finish rendering
                if 'report' in screenshot_config['name']:
                    try:
                        # Wait for canvas elements to be present and rendered
                        await page.wait_for_function(
                            """() => {
                                const canvases = document.querySelectorAll('canvas');
                                return canvases.length > 0 &&
                                       Array.from(canvases).every(c => c.getContext('2d') !== null);
                            }""",
                            timeout=5000
                        )
                    except:
                        pass  # Continue even if charts don't load

                # Optional slot: skip when the page lacks the element (feature not merged yet)
                if 'skip_unless' in screenshot_config:
                    if not await page.query_selector(screenshot_config['skip_unless']):
                        self.stdout.write(self.style.WARNING(
                            f'  Skipped: {screenshot_config["skip_unless"]} not on page'
                        ))
                        await page.close()
                        continue

                # Run page setup (fill a form, open a section) before the shot
                if 'prepare_js' in screenshot_config:
                    await page.evaluate(screenshot_config['prepare_js'])
                    await page.wait_for_timeout(500)

                # Click element if needed (e.g., for tab switching)
                if 'click_element' in screenshot_config:
                    try:
                        click_selector = screenshot_config['click_element']
                        await page.wait_for_selector(click_selector, timeout=5000)
                        await page.click(click_selector)
                        await page.wait_for_timeout(1000)  # Wait for tab transition
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(
                            f'  Warning: Could not click element {screenshot_config["click_element"]}: {e}'
                        ))

                # Scroll if needed
                if 'scroll_to' in screenshot_config:
                    # Legacy pixel-based scrolling
                    await page.evaluate(f'window.scrollTo(0, {screenshot_config["scroll_to"]})')
                    await page.wait_for_timeout(500)
                elif 'scroll_to_element' in screenshot_config:
                    # Element-based scrolling
                    try:
                        element_selector = screenshot_config['scroll_to_element']
                        position = screenshot_config.get('scroll_element_position', 'start')

                        # Wait for element to exist
                        await page.wait_for_selector(element_selector, timeout=5000)

                        # Scroll element into view with specified position
                        # 'start' = top of element aligned to top of viewport
                        # 'center' = element centered in viewport
                        # 'end' = bottom of element aligned to bottom of viewport
                        await page.locator(element_selector).scroll_into_view_if_needed()

                        if position == 'center':
                            # Center the element in viewport
                            await page.evaluate(f'''
                                {{
                                    const element = document.querySelector("{element_selector}");
                                    const elementRect = element.getBoundingClientRect();
                                    const absoluteElementTop = elementRect.top + window.pageYOffset;
                                    const middle = absoluteElementTop - (window.innerHeight / 2) + (elementRect.height / 2);
                                    window.scrollTo(0, middle);
                                }}
                            ''')
                        elif position == 'end':
                            # Align bottom of element with bottom of viewport
                            await page.evaluate(f'''
                                {{
                                    const element = document.querySelector("{element_selector}");
                                    const elementRect = element.getBoundingClientRect();
                                    const absoluteElementTop = elementRect.top + window.pageYOffset;
                                    const bottom = absoluteElementTop + elementRect.height - window.innerHeight;
                                    window.scrollTo(0, bottom);
                                }}
                            ''')
                        # 'start' is already handled by scroll_into_view_if_needed

                        await page.wait_for_timeout(500)
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(
                            f'  Warning: Could not scroll to element {screenshot_config["scroll_to_element"]}: {e}'
                        ))

                # Take screenshot
                output_file = output_path / f'{screenshot_config["name"]}.png'
                await page.screenshot(
                    path=str(output_file),
                    full_page=False,  # Viewport only
                    type='png',
                    clip=await self._focus_clip(page, screenshot_config.get('focus'),
                                                **screenshot_config.get('focus_options', {})),
                )

                self.stdout.write(self.style.SUCCESS(f'  ✓ Saved: {output_file}'))

                await page.close()

            # Now capture feedback form screenshots (public, no auth needed)
            # Get token from config (generated during data creation)
            feedback_token_str = config.get('feedback_token')

            if feedback_token_str:
                feedback_configs = [
                    # 16. Feedback Form - Desktop Light
                    {
                        'name': 'feedback_desktop_light',
                        'url': f'{base_url}/feedback/{feedback_token_str}/',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': 'light',
                        'wait_for': 'form',
                    },
                    # 17. Feedback Form - Desktop Dark
                    {
                        'name': 'feedback_desktop_dark',
                        'url': f'{base_url}/feedback/{feedback_token_str}/',
                        'viewport': {'width': 1920, 'height': 1080},
                        'theme': 'dark',
                        'wait_for': 'form',
                    },
                    # 18. Feedback Form - Mobile Light
                    {
                        'name': 'feedback_mobile_light',
                        'url': f'{base_url}/feedback/{feedback_token_str}/',
                        'viewport': {'width': 375, 'height': 812},
                        'theme': 'light',
                        'wait_for': 'form',
                    },
                    # 19. Feedback Form - Mobile Dark
                    {
                        'name': 'feedback_mobile_dark',
                        'url': f'{base_url}/feedback/{feedback_token_str}/',
                        'viewport': {'width': 375, 'height': 812},
                        'theme': 'dark',
                        'wait_for': 'form',
                    },
                ]

                # Reviewee self-assessment, the reviewer thank-you page, and the form
                # opened by a German browser (the questionnaire is translated)
                public_pages = [
                    ('self_assessment', config.get('self_feedback_token'), 'form', None),
                    ('feedback_complete', config.get('completed_feedback_token'), 'body', None),
                    ('feedback_translated', config.get('translated_feedback_token'), 'form', 'de-DE'),
                ]
                for name, token, wait_for, locale in public_pages:
                    if not token:
                        continue
                    for device, viewport in (('desktop', {'width': 1920, 'height': 1080}),
                                             ('mobile', {'width': 375, 'height': 812})):
                        for theme in ('light', 'dark'):
                            feedback_configs.append({
                                'name': f'{name}_{device}_{theme}',
                                'url': f'{base_url}/feedback/{token}/',
                                'viewport': viewport,
                                'theme': theme,
                                'wait_for': wait_for,
                                'locale': locale,
                            })
                feedback_configs = self._filter(feedback_configs)

                feedback_start = len(screenshot_configs) + 1
                total_screenshots = len(screenshot_configs) + len(feedback_configs)

                for i, screenshot_config in enumerate(feedback_configs, feedback_start):
                    self.stdout.write(f'\n[{i}/{total_screenshots}] Capturing: {screenshot_config["name"]}')

                    page = await browser.new_page(
                        viewport=screenshot_config['viewport'],
                        device_scale_factor=1,
                        locale=screenshot_config.get('locale'),
                    )

                    await page.add_init_script(f'''
                        localStorage.setItem('theme', '{screenshot_config['theme']}');
                        localStorage.setItem('blik_welcome_seen', 'true');
                    ''')

                    await page.goto(screenshot_config['url'])

                    if 'wait_for' in screenshot_config:
                        try:
                            await page.wait_for_selector(screenshot_config['wait_for'], timeout=10000)
                        except Exception as e:
                            self.stdout.write(self.style.WARNING(
                                f'  Warning: Could not find selector {screenshot_config["wait_for"]}: {e}'
                            ))

                    await page.wait_for_timeout(1000)

                    output_file = output_path / f'{screenshot_config["name"]}.png'
                    await page.screenshot(
                        path=str(output_file),
                        full_page=False,
                        type='png'
                    )

                    self.stdout.write(self.style.SUCCESS(f'  ✓ Saved: {output_file}'))

                    await page.close()

            await self._capture_emails(browser, output_path)

            await browser.close()

    async def _focus_clip(self, page, selector, padding=32, top=16, aspect=4 / 3):
        """
        A clip around one element: padded at the sides, cut to aspect, with the
        element's top near the top. Floating controls (fixed elements) are hidden.
        None (the whole viewport) without a selector. top stays below the usual
        1.5rem gap between cards, so the card above does not show.
        """
        if not selector:
            return None
        element = page.locator(selector).first
        await page.evaluate("""() => document.querySelectorAll('body *').forEach(el => {
            if (getComputedStyle(el).position === 'fixed') el.style.visibility = 'hidden';
        })""")
        await element.evaluate(f'el => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - {top})')
        await page.wait_for_timeout(300)
        box = await element.bounding_box()
        width = box['width'] + 2 * padding
        return {'x': max(box['x'] - padding, 0), 'y': max(box['y'] - top, 0), 'width': width, 'height': width / aspect}

    def _filter(self, configs):
        if not self.only:
            return configs
        return [c for c in configs if c['name'].startswith(tuple(self.only))]

    async def _capture_emails(self, browser, output_path):
        """Render email templates locally in an inbox frame; nothing is sent."""
        # Admin email: desktop only. Reviewee/reviewer emails: desktop and mobile.
        configs = []
        for name, template, subject, recipient, context in EMAIL_PREVIEWS:
            devices = [('desktop', {'width': 1920, 'height': 1080})]
            if name != 'email_welcome':
                devices.append(('mobile', {'width': 375, 'height': 812}))
            for device, viewport in devices:
                for theme in ('light', 'dark'):
                    configs.append({
                        'name': f'{name}_{device}_{theme}',
                        'html': render_email_preview(template, subject, recipient, context, theme),
                        'viewport': viewport,
                    })

        for screenshot_config in self._filter(configs):
            self.stdout.write(f'\nCapturing: {screenshot_config["name"]}')
            page = await browser.new_page(viewport=screenshot_config['viewport'], device_scale_factor=1)
            await page.set_content(screenshot_config['html'], wait_until='load')
            await page.wait_for_timeout(500)
            output_file = output_path / f'{screenshot_config["name"]}.png'
            await page.screenshot(path=str(output_file), full_page=False, type='png')
            self.stdout.write(self.style.SUCCESS(f'  ✓ Saved: {output_file}'))
            await page.close()
