# Screenshot System Setup - Summary

## What Was Created

A complete, automated screenshot generation system for the Blik landing page with professional product images.

## Files Created

### Management Commands

1. **`core/management/commands/generate_screenshot_data.py`**
   - Generates optimized demo data for screenshots
   - Creates "Acme Corporation" with realistic team and review cycles
   - Outputs configuration JSON for screenshot script
   - Creates varied cycle states (completed, partial, new) for visual interest

2. **`core/management/commands/capture_screenshots.py`**
   - Automated Playwright-based screenshot capture
   - Captures 17 screenshots across different pages, themes, and devices
   - Handles authentication, theme switching, and chart rendering
   - Saves to `static/img/screenshots/`

3. **`core/management/commands/optimize_screenshots.py`**
   - Optimizes PNG files for web
   - Generates WebP versions for modern browsers
   - Optional image resizing
   - Reports compression savings

### Configuration & Documentation

4. **`requirements-screenshots.txt`**
   - Dependencies: playwright, Pillow

5. **`docs/SCREENSHOTS.md`**
   - Comprehensive screenshot generation guide
   - Troubleshooting section
   - Update workflow documentation
   - CI/CD integration examples

6. **`scripts/generate_screenshots.sh`**
   - One-command screenshot generation
   - Dependency checking
   - Server status verification
   - Complete automation script

### Landing Page Updates

7. **`templates/landing/index.html`** (modified)
   - Added "See Blik in Action" section after hero
   - Large hero screenshot (report with charts)
   - 3-column grid showcasing: Dashboard, Mobile Feedback, Team Management
   - WebP support with PNG fallback
   - Lazy loading for performance

## Screenshot Inventory

### 17 Total Screenshots

**Report Page (6):**
- `report_desktop_light.png/webp` - 1920x1080
- `report_desktop_dark.png/webp` - 1920x1080
- `report_tablet_light.png/webp` - 1024x768
- `report_tablet_dark.png/webp` - 1024x768

**Admin Dashboard (4):**
- `dashboard_desktop_light.png/webp` - 1920x1080
- `dashboard_desktop_dark.png/webp` - 1920x1080
- `dashboard_mobile_light.png/webp` - 375x812
- `dashboard_mobile_dark.png/webp` - 375x812

**Review Cycle Detail (2):**
- `cycle_detail_desktop_light.png/webp` - 1920x1080
- `cycle_detail_desktop_dark.png/webp` - 1920x1080

**Team Management (2):**
- `team_desktop_light.png/webp` - 1920x1080
- `team_desktop_dark.png/webp` - 1920x1080

**Manage Invitations (1):**
- `invitations_desktop_light.png/webp` - 1920x1080

**Feedback Form (4):**
- `feedback_desktop_light.png/webp` - 1920x1080
- `feedback_desktop_dark.png/webp` - 1920x1080
- `feedback_mobile_light.png/webp` - 375x812
- `feedback_mobile_dark.png/webp` - 375x812

## How to Use

### Quick Start

```bash
# 1. Install dependencies
pip install -r requirements-screenshots.txt
playwright install chromium

# 2. Start the application
docker compose up -d
# OR
python manage.py runserver

# 3. Run the automated script
./scripts/generate_screenshots.sh
```

### Manual Process

```bash
# Step 1: Generate demo data
python manage.py generate_screenshot_data --clear

# Step 2: Capture screenshots
python manage.py capture_screenshots

# Step 3: Optimize images
python manage.py optimize_screenshots --webp

# Step 4: Review
open static/img/screenshots/

# Step 5: Commit
git add static/img/screenshots/
git commit -m "Update landing page screenshots"
```

## Demo Data Details

**Organization:** Acme Corporation
**Admin Login:** `admin` / `demo123`
**Team Members:** 9 total (2 admins, 7 members)

**Review Cycles:**
- John Smith - Completed (with perception gap pattern for visual interest)
- Emma Davis - 60% complete
- Robert Brown - 20% complete
- Sophia Garcia - 90% claimed, minimal completion
- William Lee - Completed

**Special Features:**
- "Imposter syndrome" pattern in completed cycle creates visible perception gaps in charts
- Varied completion percentages for realistic dashboard appearance
- Mix of claimed/unclaimed tokens for invitation management screenshots

## Landing Page Integration

### New "See Blik in Action" Section

Located between "Comparison" and "Features" sections:

1. **Hero Screenshot** - Large report page with charts (dark theme)
2. **3-Column Grid:**
   - Dashboard screenshot (light theme)
   - Mobile feedback form (dark theme)
   - Team management (light theme)

### Technical Implementation

- Uses `<picture>` element with WebP/PNG fallback
- Lazy loading except hero image
- Responsive grid layout
- Semantic alt text for accessibility
- Proper ARIA labels

## Key Features

### Automation
- Single script execution
- Dependency checking
- Server verification
- Error handling

### Optimization
- PNG compression
- WebP generation (85% quality)
- Optional resizing
- Reports savings

### Repeatability
- Idempotent data generation
- Configuration-driven capture
- Documented process
- CI/CD ready

### Visual Quality
- Professional demo data
- Varied states for interest
- Multiple themes shown
- Responsive sizes captured

## Maintenance

### When to Update Screenshots

- Major UI changes
- New features added
- Branding updates
- Theme modifications
- Chart/visualization changes

### Update Process

```bash
# Quick update
./scripts/generate_screenshots.sh

# Review changes
git diff static/img/screenshots/

# Commit if satisfied
git add static/img/screenshots/
git commit -m "Update screenshots: [reason]"
```

## Future Enhancements

Potential improvements:

1. **More Pages:**
   - Settings page
   - Questionnaire builder
   - Email templates preview

2. **Animation Captures:**
   - GIF/MP4 for interactive features
   - Loading states
   - Transitions

3. **Multiple Brands:**
   - Different organization names
   - Custom color schemes
   - White-label examples

4. **A/B Testing:**
   - Multiple screenshot variants
   - Different data patterns
   - Layout variations

## Troubleshooting

See `docs/SCREENSHOTS.md` for comprehensive troubleshooting guide.

Common issues:
- **Playwright not installed:** `playwright install chromium`
- **Server not running:** Start with `python manage.py runserver`
- **Charts not rendering:** Increase wait timeout in capture script
- **Images too large:** Use `--max-width` flag in optimize command

## Performance Impact

**File Sizes (approximate):**
- PNG: ~200-500KB per screenshot
- WebP: ~100-250KB per screenshot
- Total: ~10-15MB for all screenshots

**Page Load Impact:**
- Hero image: Eager loading (~200KB WebP)
- Grid images: Lazy loading (~100-150KB each)
- Modern browsers: WebP support reduces bandwidth by ~50%

## Next Steps

1. **Generate screenshots:**
   ```bash
   ./scripts/generate_screenshots.sh
   ```

2. **Test landing page:**
   ```
   http://localhost:8000/landing/
   ```

3. **Verify responsive design:**
   - Test on mobile viewport
   - Check tablet breakpoints
   - Ensure images load correctly

4. **Deploy:**
   - Commit screenshots to repository
   - Push to staging/production
   - Verify static files served correctly

## Support

For issues or questions:
- See detailed docs in `docs/SCREENSHOTS.md`
- Check command help: `python manage.py [command] --help`
- Review generated config: `/tmp/blik_screenshot_config.json`

---

**Created:** 2025-10-27
**System:** Automated screenshot generation for Blik landing page
**Version:** 1.0
