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
            screenshot_configs = [
                # 1. Report page - Header/Summary section - Desktop Light
                {
                    'name': 'report_header_desktop_light',
                    'url': f'{base_url}/report/{config["completed_cycle_id"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'scroll_to': 0,  # Top of page - header and summary
                },
                # 2. Report page - Header/Summary section - Desktop Dark
                {
                    'name': 'report_header_desktop_dark',
                    'url': f'{base_url}/report/{config["completed_cycle_id"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'scroll_to': 0,  # Top of page - header and summary
                },
                # 3. Report page - Charts section - Desktop Light
                {
                    'name': 'report_charts_desktop_light',
                    'url': f'{base_url}/report/{config["completed_cycle_id"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'scroll_to': 1080,  # Scroll 1 full viewport down to show radar chart and competency breakdowns
                },
                # 4. Report page - Charts section - Desktop Dark
                {
                    'name': 'report_charts_desktop_dark',
                    'url': f'{base_url}/report/{config["completed_cycle_id"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'scroll_to': 1080,  # Scroll 1 full viewport down to show radar chart and competency breakdowns
                },
                # 5. Report page - Tablet Light
                {
                    'name': 'report_tablet_light',
                    'url': f'{base_url}/report/{config["completed_cycle_id"]}/',
                    'viewport': {'width': 1024, 'height': 768},
                    'theme': 'light',
                    'scroll_to': 400,
                },
                # 6. Report page - Tablet Dark
                {
                    'name': 'report_tablet_dark',
                    'url': f'{base_url}/report/{config["completed_cycle_id"]}/',
                    'viewport': {'width': 1024, 'height': 768},
                    'theme': 'dark',
                    'scroll_to': 400,
                },
                # 7. Admin Dashboard - Desktop Light
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
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_id"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'wait_for': '.stats-grid',
                },
                # 12. Review Cycle Detail - Desktop Dark
                {
                    'name': 'cycle_detail_desktop_dark',
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_id"]}/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'dark',
                    'wait_for': '.stats-grid',
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
                # 15. Manage Invitations - Desktop Light
                {
                    'name': 'invitations_desktop_light',
                    'url': f'{base_url}/dashboard/cycles/{config["partial_cycle_id"]}/invitations/',
                    'viewport': {'width': 1920, 'height': 1080},
                    'theme': 'light',
                    'wait_for': '.stats-grid',
                },
            ]

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

                # Set theme
                await page.add_init_script(f'''
                    localStorage.setItem('theme', '{screenshot_config['theme']}');
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

                # Scroll if needed
                if 'scroll_to' in screenshot_config:
                    await page.evaluate(f'window.scrollTo(0, {screenshot_config["scroll_to"]})')
                    await page.wait_for_timeout(500)

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
