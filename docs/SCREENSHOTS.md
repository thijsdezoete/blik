# Screenshot Generation Guide

This guide explains how to generate and update screenshots for the Blik landing page.

## Overview

The screenshot system consists of three Django management commands that work together to create professional, branded screenshots showcasing Blik's features.

## Prerequisites

1. **Install screenshot dependencies:**
   ```bash
   pip install -r requirements-screenshots.txt
   playwright install chromium
   ```

2. **Ensure the application is running:**
   ```bash
   docker compose up -d
   # OR
   python manage.py runserver
   ```

3. **Load default questionnaires (if not already done):**
   ```bash
   python manage.py clone_default_questionnaires
   ```

## Quick Start

Generate all screenshots with one command sequence:

```bash
# 1. Generate demo data
python manage.py generate_screenshot_data --clear

# 2. Capture screenshots (ensure app is running on localhost:8000)
python manage.py capture_screenshots

# 3. Optimize images
python manage.py optimize_screenshots --webp

# 4. Commit to repository
git add static/img/screenshots/
git commit -m "Update landing page screenshots"
```

## Command Details

### 1. `generate_screenshot_data`

Creates optimized demo data specifically for screenshots.

**What it creates:**
- Organization: "Acme Corporation"
- Admin user: `admin` / `demo123`
- 8 team members (2 admins, 6 members)
- 5 review cycles:
  - 2 completed with reports (including one with perception gap for visual interest)
  - 2 partially completed (60% and 20%)
  - 1 newly created (90% claimed)

**Options:**
- `--clear`: Delete existing data before generating (recommended)

**Output:**
- Prints configuration JSON
- Saves config to `/tmp/blik_screenshot_config.json`

**Example:**
```bash
python manage.py generate_screenshot_data --clear
```

### 2. `capture_screenshots`

Uses Playwright to capture screenshots of key pages.

**What it captures:**
- Report page with charts (desktop light/dark, tablet light/dark) - 4 screenshots
- Admin dashboard (desktop light/dark, mobile light/dark) - 4 screenshots
- Review cycle detail (desktop light/dark) - 2 screenshots
- Team management (desktop light/dark) - 2 screenshots
- Manage invitations (desktop light) - 1 screenshot
- Feedback form (desktop light/dark, mobile light/dark) - 4 screenshots

**Total: 17 screenshots**

**Options:**
- `--config PATH`: Path to config JSON (default: `/tmp/blik_screenshot_config.json`)
- `--output-dir DIR`: Output directory (default: `static/img/screenshots`)
- `--base-url URL`: Application URL (default: `http://localhost:8000`)

**Example:**
```bash
# Default (localhost:8000)
python manage.py capture_screenshots

# Custom URL
python manage.py capture_screenshots --base-url http://localhost:9000
```

### 3. `optimize_screenshots`

Optimizes PNG files and optionally generates WebP versions.

**What it does:**
- Compresses PNGs with maximum compression
- Optionally resizes to max width
- Optionally generates WebP versions

**Options:**
- `--input-dir DIR`: Input directory (default: `static/img/screenshots`)
- `--quality N`: WebP/JPEG quality 1-100 (default: 85)
- `--webp`: Generate WebP versions
- `--max-width N`: Resize to max width

**Example:**
```bash
# Optimize PNGs only
python manage.py optimize_screenshots

# Generate WebP versions
python manage.py optimize_screenshots --webp

# Resize large screenshots
python manage.py optimize_screenshots --webp --max-width 1600
```

## Screenshot Specifications

### Sizes

| Device Type | Viewport Size | Use Case |
|-------------|---------------|----------|
| Desktop     | 1920x1080     | Primary showcase images |
| Tablet      | 1024x768      | Responsive design demo |
| Mobile      | 375x812       | Mobile experience |

### Themes

All screenshots are captured in both light and dark themes (where applicable) to:
- Showcase theme toggle feature
- Provide options for different landing page sections
- Demonstrate professional UI in both modes

### Pages Captured

1. **Report Page** (`/report/<cycle_id>/`)
   - Primary visual showcase
   - Shows radar charts, bar charts, data visualization
   - Demonstrates rich reporting capabilities
   - **Special data:** "Imposter syndrome" pattern creates visible perception gap

2. **Admin Dashboard** (`/dashboard/`)
   - Shows management overview
   - Stat cards, progress bars, cycle management
   - Both desktop and mobile views

3. **Review Cycle Detail** (`/dashboard/cycles/<id>/`)
   - Progress tracking
   - Token management stats
   - Partial completion for visual interest

4. **Team Management** (`/dashboard/team/`)
   - Collaboration features
   - Role/permission badges
   - Team member listing

5. **Manage Invitations** (`/dashboard/cycles/<id>/invitations/`)
   - Token distribution interface
   - Category organization
   - Status tracking

6. **Feedback Form** (`/feedback/<token>/`)
   - Anonymous feedback interface
   - Rating scales, progress bar
   - Mobile-optimized view

## File Naming Convention

Screenshots follow this pattern:
```
{page_name}_{device_type}_{theme}.{ext}
```

Examples:
- `report_desktop_light.png`
- `dashboard_mobile_dark.png`
- `feedback_tablet_light.webp`

## Troubleshooting

### Playwright not installed
```bash
pip install playwright
playwright install chromium
```

### No questionnaires found
```bash
python manage.py clone_default_questionnaires
```

### Connection refused
Ensure the Django app is running:
```bash
python manage.py runserver
# OR
docker compose up
```

### Charts not rendering
The script waits for `<canvas>` elements and adds a 2-second delay. If charts still don't render:
- Increase timeout in `capture_screenshots.py`
- Check browser console for JavaScript errors
- Verify Chart.js is loading correctly

### Images too large
```bash
# Resize to 1600px width
python manage.py optimize_screenshots --max-width 1600 --webp
```

## Updating Screenshots

When the UI changes or new features are added:

1. **Update the data generation** if needed:
   - Edit `core/management/commands/generate_screenshot_data.py`
   - Adjust reviewee data, cycle states, or patterns

2. **Update screenshot configs** if needed:
   - Edit `core/management/commands/capture_screenshots.py`
   - Add new pages, adjust scroll positions, change viewports

3. **Run the full process:**
   ```bash
   python manage.py generate_screenshot_data --clear
   python manage.py capture_screenshots
   python manage.py optimize_screenshots --webp
   ```

4. **Review and commit:**
   ```bash
   # View screenshots
   open static/img/screenshots/

   # Commit if satisfied
   git add static/img/screenshots/ docs/SCREENSHOTS.md
   git commit -m "Update screenshots for v2.1"
   ```

## Integration with Landing Page

Screenshots are referenced in `templates/landing/index.html`:

```html
<!-- Example: Feature showcase -->
<picture>
  <source srcset="{% static 'img/screenshots/report_desktop_dark.webp' %}" type="image/webp">
  <img src="{% static 'img/screenshots/report_desktop_dark.png' %}"
       alt="360 Feedback Report with Charts"
       loading="lazy">
</picture>
```

WebP is used when available with PNG fallback for browser compatibility.

## CI/CD Integration

To automate screenshot updates in CI:

```yaml
# Example GitHub Actions workflow
- name: Generate screenshots
  run: |
    python manage.py generate_screenshot_data --clear
    python manage.py runserver &
    sleep 5
    python manage.py capture_screenshots
    python manage.py optimize_screenshots --webp
```

## Tips for Great Screenshots

1. **Use realistic data:** The "Acme Corporation" data is designed to look professional
2. **Show visual interest:** Partial completion bars and varied ratings create dynamic visuals
3. **Capture at the right scroll position:** Charts and key features should be visible
4. **Use both themes:** Dark mode screenshots often look more striking on landing pages
5. **Mobile matters:** Mobile screenshots demonstrate responsive design
6. **Update regularly:** Keep screenshots in sync with UI changes

## Advanced Customization

### Custom organization name
Edit the organization name in `generate_screenshot_data.py`:
```python
org = Organization.objects.create(
    name='Your Company Name',
    email='admin@yourcompany.com',
    # ...
)
```

### Different data patterns
Modify the `_create_completed_cycle` method to change rating patterns:
- `high_performer`: Consistently high ratings
- `solid_performer`: Good ratings with some variation
- `developing`: Lower ratings for growth opportunities
- `imposter_syndrome`: Self rates lower than others (creates visual gap)
- `overconfident`: Self rates higher than others

### Add new pages
Add new configurations to the `screenshot_configs` list in `capture_screenshots.py`:
```python
{
    'name': 'new_page_desktop_light',
    'url': f'{base_url}/new-page/',
    'viewport': {'width': 1920, 'height': 1080},
    'theme': 'light',
    'wait_for': '.some-element',
    'scroll_to': 200,
}
```
