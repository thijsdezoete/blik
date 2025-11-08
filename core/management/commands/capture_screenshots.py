"""
Management command to capture screenshots using Playwright.
Reads configuration from generate_screenshot_data output and captures screenshots
for the landing page.
"""
from django.core.management.base import BaseCommand
from django.conf import settings
import json
import os
import asyncio
from pathlib import Path


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

    def handle(self, *args, **options):
        config_path = options['config']
        output_dir = options['output_dir']
        base_url = options['base_url']

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
            await page.fill('input[name="login"]', config['admin_username'])
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
            ])

            # Capture screenshots
            for i, screenshot_config in enumerate(screenshot_configs, 1):
                self.stdout.write(f'\n[{i}/{len(screenshot_configs)}] Capturing: {screenshot_config["name"]}')

                # Create new page with viewport
                page = await browser.new_page(
                    viewport=screenshot_config['viewport'],
                    device_scale_factor=1  # No scaling for crisp screenshots
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
                    type='png'
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

                feedback_start = len(screenshot_configs) + 1
                total_screenshots = len(screenshot_configs) + len(feedback_configs)

                for i, screenshot_config in enumerate(feedback_configs, feedback_start):
                    self.stdout.write(f'\n[{i}/{total_screenshots}] Capturing: {screenshot_config["name"]}')

                    page = await browser.new_page(
                        viewport=screenshot_config['viewport'],
                        device_scale_factor=1
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

            await browser.close()
