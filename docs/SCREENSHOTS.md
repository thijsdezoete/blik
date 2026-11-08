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
# 1. Load the shipped questionnaire translations, then generate demo data
python manage.py upgrade
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
- An org chart of three stacked units (`ORG_CHART` in the command): "Leadership" with the
  CEO Rachel Whitfield as manager and the two heads as members; "Engineering" (Morgan Taylor,
  4 members) and "Product & Design" (Casey Johnson, 3 members). Rachel Whitfield, Priya
  Natarajan and Nathan Hughes exist only for the chart.
- One reviewer with four forms for the overview page: Priya Natarajan has her own
  self-assessment (started), a colleague she has finished (`completed_at` set, shows "Done"),
  one she has started and one she has not opened. The config holds her address
  (`overview_email`) and the path of her signed overview link (`overview_path`, from
  `reviews.services.feedback_overview_url`); the capture puts it on its `--base-url`.

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
- Report page - header/summary (desktop light/dark) - 2 screenshots
- Report page - charts section (desktop light/dark) - 2 screenshots
- Report page - tablet (tablet light/dark) - 2 screenshots
- Admin dashboard (desktop light/dark, mobile light/dark) - 4 screenshots
- Review cycle detail (desktop light/dark) - 2 screenshots
- Team management (desktop light/dark) - 2 screenshots
- Manage invitations (desktop light/dark) - 2 screenshots
- Feedback form (desktop light/dark, mobile light/dark) - 4 screenshots

**Total: 19 screenshots**

"How Blik works" flow (added on top of the set above):
- Sign up / plan picker: `signup_desktop_*` (the landing page has no dark theme, so both look the same)
- Questionnaires: `questionnaires_desktop_*`, `questionnaire_edit_desktop_*`
- Reviewees: `reviewees_desktop_*`; `reviewees_gap_desktop_*` is a slot for the
  self-vs-others gap column (sorted by gap, which shows the column); skipped if the column is hidden
- New review cycle form (filled in, invite section open): `cycle_create_desktop_*`
- Emails, rendered from `templates/emails/` with sample data in an inbox frame (nothing is sent):
  `email_welcome_desktop_*`, and desktop + mobile for `email_reviewee_self_assessment`,
  `email_reviewee_invitation_links`, `email_reviewer_invitation`, `email_reviewer_reminder`,
  `email_report_ready`
- Reviewee: `self_assessment_{desktop,mobile}_*`, `report_mobile_*`
- Reviewer thank-you page: `feedback_complete_{desktop,mobile}_*`
- Own language: `feedback_translated_{desktop,mobile}_*` opens a fresh reviewer link with a
  German browser (needs `upgrade` before the demo data, so the questionnaires are translated);
  `questionnaire_translate_desktop_*` is the translation editor
- Homepage "How it works" cards: `step_people_*`, `step_answer_*`, `step_report_*`. One element
  each (the cycle form's Basic Information card, the first questionnaire section, the radar
  chart), cut to 4:3 at 2x pixel density so the text stays readable at card size
- Homepage hero: `hero_report_*` (the report's Overall Performance card and development path,
  16:10) in a browser frame, with `hero_phone_*` (the first question at phone width) on top

Org chart and bulk flow (desktop, light theme only, no device or theme suffix; these steps
drive the page themselves, see `_capture_org_chart_flow()`):
- `org_chart.png`: `/dashboard/org-chart/` with the three units and their members open
- `org_chart_import.png`: the column-mapping step of the CSV import, after uploading a 6-row
  CSV (`IMPORT_CSV`) through the file input on the org chart page
- `feedback_overview.png`: the reviewer's personal overview at the signed link from the config,
  with one form marked done
- `report_pdf.png`: the cover of the PDF report, 794x1123 (A4 at 96 dpi). The PDF's HTML
  (`reports.pdf.report_pdf_html`) is rendered from the database into a temporary file and
  opened over `file://`; everything after the cover is hidden
- `bulk_preview.png`: the bulk send preview after creating cycles for everyone with reviewers
  from the org chart. The page reads the new cycle UUIDs from the admin session, so the script
  submits the cycle form (`creation_mode=bulk`, `bulk_source=chart`) and lands on
  `/dashboard/cycles/bulk/send-invitations/`. This creates cycles and tokens, so it runs last:
  rerun `generate_screenshot_data --clear` before capturing anything else again

**Note:** Report desktop screenshots are split into two parts (header/summary and charts) to capture all key information while keeping standard viewport sizes (1920x1080, 1024x768).

**Options:**
- `--config PATH`: Path to config JSON (default: `/tmp/blik_screenshot_config.json`)
- `--output-dir DIR`: Output directory (default: `static/img/screenshots`)
- `--base-url URL`: Application URL (default: `http://localhost:8000`)
- `--only PREFIXES`: Comma-separated name prefixes to capture, e.g. `--only email_,cycle_create`

**Example:**
```bash
# Default (localhost:8000)
python manage.py capture_screenshots

# Custom URL
python manage.py capture_screenshots --base-url http://localhost:9000
```

### Throwaway database

`generate_screenshot_data --clear` deletes every cycle, token and reviewee in the database it
runs against. When port 8000 serves a database you want to keep, point the commands at a
SQLite file and run your own dev server on another port:

```bash
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib   # macOS: WeasyPrint's libraries
export DATABASE_URL=sqlite:////tmp/blik-shots.sqlite3
python manage.py migrate
python manage.py upgrade                              # shipped questionnaires and translations
python manage.py generate_screenshot_data --clear
python manage.py runserver 8010 &                     # not through nohup: SIP drops DYLD_* there
python manage.py capture_screenshots --base-url http://localhost:8010 \
    --only org_chart,bulk_preview --output-dir /tmp/blik-shots
python manage.py optimize_screenshots --webp --input-dir /tmp/blik-shots
cp /tmp/blik-shots/org_chart.* static/img/screenshots/
```

`optimize_screenshots` rewrites every PNG in its directory, so run it on the scratch directory
and copy only the new files into `static/img/screenshots/`.

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
   - **Viewport strategy:** Two separate captures for desktop:
     - Header/summary section (scroll_to: 0) - shows title, overview stats
     - Charts section (scroll_to: 600) - shows radar chart and competency breakdowns
   - **Tablet:** Single capture at 1024x768 scrolled to show key content
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

7. **Org Chart** (`/dashboard/org-chart/`, `/dashboard/org-chart/import/columns/`)
   - Stacked units with managers and members
   - CSV import: the column-mapping step with the first rows of the file

8. **Bulk Send Preview** (`/dashboard/cycles/bulk/send-invitations/`)
   - Cycles created for everyone, reviewer counts per category from the org chart
   - Needs the admin session of the bulk creation that came before it

9. **Reviewer Overview** (`/feedback/overview/<signed>/`)
   - One reviewer's forms: own self-assessment and colleagues, with Start/Continue/Done

10. **Report PDF cover** (rendered HTML, not a URL)
    - `reports.pdf.report_pdf_html(report, 'en')` at A4 width

## File Naming Convention

Screenshots follow this pattern:
```
{page_name}_{device_type}_{theme}.{ext}
```

Examples:
- `report_desktop_light.png`
- `dashboard_mobile_dark.png`
- `feedback_tablet_light.webp`

The org chart and bulk flow shots exist in one variant only and carry a bare name:
`org_chart.png`, `org_chart_import.png`, `bulk_preview.png`, `feedback_overview.png`,
`report_pdf.png`.

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
