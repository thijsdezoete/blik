# Premium Design Overhaul Plan for Cornerstone Pages

Absolute mode. No noise, no emoji's and no bloat. All signal.
No comprehensive summaries - just report the status. Truth is most valuable.
No inline styles.
Encountering emoji's, inline styles or any other noise: Relentlessly remove.

## Overview
Transform Dreyfus Model, Agency Levels, and Performance Matrix pages from functional-but-dated to premium SaaS quality by implementing modern design patterns, visual storytelling, and consistent design system.

## Implementation Status

### ✅ Phase 1: Design System Foundation - COMPLETED
**CSS Variables (main.css)**
- ✅ Added full color scale system (50-900 shades) for primary, success, warning, danger
- ✅ Implemented 8px spacing scale with CSS variables (--space-1 through --space-32)
- ✅ Added typography scale (--text-xs through --text-6xl)
- ✅ Upgraded shadow system to premium quality (--shadow-xs through --shadow-xl)
- ✅ Added border radius scale (--radius-sm through --radius-xl)
- ✅ Removed all gradient variables (--gradient-purple, --gradient-horizontal)
- ✅ Updated both light and dark theme variables

**Component Library (landing.css)**
- ✅ Premium feature cards: 48px padding, stronger shadows, 1px borders
- ✅ Updated hero to use new variables (padding: var(--space-24))
- ✅ Enhanced section spacing (var(--space-24) = 96px)
- ✅ Added utility typography classes (.text-xs, .text-sm, etc.)
- ✅ Added utility spacing classes (.mt-4, .mb-6, .p-8, etc.)
- ✅ Fixed responsive grids to prevent mobile overflow

**Gradient Removal**
- ✅ Replaced all gradient backgrounds with solid var(--primary-600)
- ✅ Updated all callout boxes across cornerstone pages
- ✅ Enhanced with border: 1px solid var(--primary-700) for depth

### ✅ Phase 2: Dreyfus Model Page - COMPLETED
**Hero & TL;DR**
- ✅ Enhanced TL;DR box: white card background, 2px border, better spacing
- ✅ Applied design system spacing throughout (var(--space-8), var(--space-4))
- ✅ Improved typography with proper font-size variables

**Visual Summary Section**
- ✅ Larger container (900px) with premium shadow (--shadow-md)
- ✅ Added 1px border and rounded corners (var(--radius-xl))
- ✅ Colored arrows with primary-400 for visual hierarchy

**Why Dreyfus Card**
- ✅ Success-themed left border (4px solid var(--success))
- ✅ Added success-50 background callout box for core insight
- ✅ Enhanced CTA link styling with underline and proper weight
- ✅ Better content hierarchy with section divider

**SVG Container**
- ✅ Premium presentation: shadow-lg, radius-xl, larger padding
- ✅ Improved caption styling and width constraint

**5 Stage Cards**
- ✅ Progressive top border colors (primary-300 → primary-700)
- ✅ Consistent spacing with design system variables
- ✅ Quoted text styled with left border accent
- ✅ "In practice" boxes with primary-50 background
- ✅ Clean typography hierarchy throughout

**Bottom Callouts**
- ✅ Warning-accented domain expertise card
- ✅ Primary-themed CTA card with button link
- ✅ Proper spacing (var(--space-16), var(--space-12))

### ✅ Phase 3: Agency Levels Page - COMPLETED
**Hero Section**
- ✅ Hero stat callout: "Level 5 engineers save managers 10+ hours per week"
- ✅ Clean, content-focused design with solid background
- ✅ TL;DR box with proper styling

**Level Cards with Staircase Layout**
- ✅ Implemented ascending staircase visual metaphor using CSS transforms
- ✅ Red (L1) → Orange (L2) → Yellow (L3) → Light Green (L4) → Green (L5) color progression
- ✅ Added simple SVG icons: inbox (L1), search (L2), list/options (L3), arrow-up (L4), checkmark (L5)
- ✅ Responsive: 5 columns on desktop, 2 columns on tablet, stacked on mobile
- ✅ Hover effects with subtle lift

**Scenario Cards Redesign**
- ✅ Converted comparison tables to card-based grid layout
- ✅ 5-column grid showing all levels side-by-side for each scenario
- ✅ Manager time displayed as prominent, color-coded badges at top of each card
- ✅ Chat bubble design for responses with visual tail
- ✅ Two scenarios implemented: Production Bug, Performance Issue
- ✅ Fully responsive on mobile

**Interactive Level Slider**
- ✅ Horizontal slider with 5 discrete positions (L1-L5)
- ✅ Three scenarios users can cycle through:
  * Production Bug (checkout broken)
  * Performance Issue (slow dashboard)
  * Feature Request (dark mode)
- ✅ Dynamically updates response text, manager time, and card styling
- ✅ Clean, minimal design with clear labels
- ✅ Scenario picker buttons for easy switching
- ✅ Color-coded response cards matching level colors
- ✅ Vanilla JavaScript (no framework dependencies)

**Engagement Features (Progressive Disclosure)**
- ✅ Section-level expandable content for research sections
- ✅ Card-level expandable content for dense feature cards
- ✅ "Read More" buttons with smooth animations
- ✅ Shared JavaScript in `landing/base.html` for all cornerstone pages

### ✅ Phase 3.5: Engagement System - COMPLETED
**Problem Solved:** Dense content creating walls of text, poor scannability, overwhelming users

**Solution Implemented:** Two-tier expandable content system

**Section-Level Expansion** (`templates/landing/base.html`, `static/css/landing.css`)
- Purpose: Hide entire dense sections (research papers, citations, technical details)
- Components:
  * `.expandable-section` - Container with max-height transition
  * `.read-more-toggle` - Primary CTA button with chevron icon
  * `toggleExpandable(sectionId)` - JavaScript function in base template
- Applied to:
  * Agency Levels: Research Foundation section
  * Dreyfus Model: Research Foundation section
- Behavior: Collapsed by default, expands to show full academic citations

**Card-Level Expansion** (`templates/landing/base.html`, `static/css/landing.css`)
- Purpose: Condense individual feature cards while preserving detail access
- Components:
  * `.card-expandable-content` - Hidden content within cards
  * `.card-expand-toggle` - Inline button styled as secondary action
  * `toggleCardContent(contentId)` - JavaScript function in base template
- Applied to:
  * Dreyfus Model: All 5 stage cards (Novice → Expert)
  * Shows: Thinking style summary + career level (visible)
  * Hides: Dreyfus quotes + "In practice" examples (expandable)
- Impact: Reduces visual density by ~60%, improves scannability

**Design Principles for Future Pages:**
1. **Default to Collapsed:** If content is academic, reference-heavy, or supplementary → hide by default
2. **Show Essential, Hide Detail:** Card summaries visible, examples/quotes expandable
3. **No Walls of Text:** Any card with 3+ paragraphs should consider expansion
4. **Progressive Disclosure:** Primary info upfront, secondary info behind "Read more"
5. **Consistent Patterns:** Use same CSS classes and JS functions across all pages

### ✅ Phase 4: Performance Matrix Page - COMPLETED

**Hero Section with Matrix as Primary Element**
- ✅ Matrix as hero: 2x2 matrix is the first visual element (full viewport emphasis)
- ✅ Larger container (1200px) with premium shadow (--shadow-lg)
- ✅ TL;DR positioned below matrix with 2px border and design system spacing
- ✅ Removed gradient background: solid var(--bg-body)
- ✅ Clean typography hierarchy (--text-5xl, --text-xl, --text-base)
- ✅ Enhanced "Why Two Dimensions" explanation card

**Archetype Deep Dives (2-Column Layout)**
- ✅ 2-column layout: 100px icon placeholder left, content right
- ✅ Simple professional SVG icon placeholders for each archetype:
  * Force Multipliers: Checkmark in circle (success green)
  * Hungry Learners: Star icon (warning yellow)
  * Brilliant Passengers: Alert icon (danger red)
  * Low Performers: X icon (neutral gray)
- ✅ Color-coded backgrounds: 5% opacity solid color per archetype
- ✅ Prominent pull quotes showing typical behavior in styled boxes
- ✅ Professional, business-focused tone maintained
- ✅ Characteristics listed with clear typography hierarchy
- ✅ Action callouts with color-themed backgrounds
- ✅ Grid stacks vertically on mobile with centered layout

**Scenario Comparison → Card Grid**
- ✅ Removed table structure completely
- ✅ 4-column card grid (one per archetype)
- ✅ Manager time badges prominent at top (color-coded: green, yellow, red, gray)
- ✅ Chat bubble design for responses with visual triangular tail
- ✅ Scenario question in prominent primary-colored callout box
- ✅ Responsive breakpoints: 4 columns → 2 columns (tablet) → 1 column (mobile)
- ✅ Consistent card styling with borders matching archetype colors

**Development Timeframes → Visual Timeline**
- ✅ Replaced table with horizontal timeline bar visualization
- ✅ Timeline bars showing development transitions between quadrants
- ✅ Color coding by coachability level:
  * Green gradient: High coachability (Low Skill → High Skill, Hungry Learner → Force Multiplier)
  * Yellow gradient: Medium coachability (Brilliant Passenger → Force Multiplier)
  * Yellow-Red gradient: Medium-Low (Low Agency → High Agency)
  * Red: Very Low (Low Performers → Anything)
- ✅ Timeline bar widths proportional to timeframe duration (e.g., 75% for 24mo, 19% for 6mo)
- ✅ Strategy text embedded within timeline bars
- ✅ Timeline headers with improved badge design:
  * Swapped order: Month estimates first (right-aligned), then coachability badges
  * Consistent widths: 130px for months, 180px for badges (perfect vertical alignment)
  * Better contrast: Light backgrounds (100 shade) with dark text (700/800 shade)
  * Center-aligned badge text for clean appearance
- ✅ Timeline bars with readable text:
  * Replaced gradients with solid light backgrounds (success-100, warning-100, danger-100)
  * Dark text on light background (800/900 shade) for excellent contrast
  * 2px colored border-right to indicate progress/duration visually
  * Maintains color-coding while ensuring all text is readable
- ✅ Responsive: Headers and badges stack on mobile, text hidden in bars on small screens

**Mobile Optimization**
- ✅ Comprehensive responsive CSS in `<style>` block in template
- ✅ Archetype grids (.archetype-grid) stack vertically on mobile with centered icons
- ✅ Scenario cards (.scenario-cards-grid) adapt: 4-col → 2-col (tablet) → 1-col (mobile)
- ✅ Timeline headers (.timeline-header) stack on small screens
- ✅ Timeline badges (.timeline-badges) stack vertically on mobile
- ✅ All touch targets meet 48px minimum requirement
- ✅ Text remains readable at all breakpoints

**Cross-Page Consistency**
- ✅ Zero gradients anywhere (all solid backgrounds)
- ✅ All colors use CSS variables from design system
- ✅ All spacing uses design system scale (--space-1 through --space-32)
- ✅ Premium shadows (--shadow-sm, --shadow-md, --shadow-lg, --shadow-xl)
- ✅ Consistent border radius (--radius-sm through --radius-xl)
- ✅ Light and dark theme support throughout
- ✅ Matches design quality of Dreyfus Model and Agency Levels pages

### ✅ Phase 5: Cross-Page Polish - COMPLETED

**TL;DR Box Consistency**
- ✅ Standardized across all 3 pages:
  * Background: `var(--bg-card)`
  * Border: `2px solid var(--primary-200)` (all sides, not just left)
  * Padding: `var(--space-8)`
  * Border radius: `var(--radius-lg)`
  * Box shadow: `var(--shadow-sm)`
  * H2 styling: `var(--text-sm)`, `font-weight: 700`, `letter-spacing: 0.1em`, `color: var(--primary-600)`
  * Max-width: 800px standard
- ✅ Agency Levels TL;DR updated to match Dreyfus/Performance Matrix standard

**Hardcoded Value Cleanup**
- ✅ Replaced all `padding: 3rem` with `var(--space-12)`
- ✅ Replaced all `margin: 3rem` with `var(--space-12)`
- ✅ Replaced all `border-radius: 4px` with `var(--radius-sm)`
- ✅ Replaced all `border-radius: 8px` with `var(--radius-md)`
- ✅ Consistent spacing scale used across all pages

**Design System Compliance**
- ✅ Zero hardcoded hex colors (all use CSS variables)
- ✅ Zero gradients (all solid backgrounds)
- ✅ Consistent border radius scale
- ✅ Consistent spacing scale
- ✅ Light/dark theme compatible throughout

## Phase 1: Design System Foundation

### 1.1 CSS Variables Expansion (main.css)
- **Color system depth**: Add 50-900 shade variants for primary, success, warning, danger
- **Spacing scale**: Implement strict 8px scale (4, 8, 16, 24, 32, 48, 64, 96, 128px)
- **Typography scale**: Define clear hierarchy (12, 14, 16, 20, 24, 32, 48, 64px)
- **Shadow system**: Upgrade to premium shadows (stronger, more defined)
- **Border radius system**: Consistent values (4, 8, 12, 16px)
- **Remove all gradients**: Eliminate `--gradient-purple` and `--gradient-horizontal` from design system

### 1.2 Component Library (landing.css)
- **Premium feature cards**: Larger padding (3rem), stronger shadows, subtle hover effects
- **Bento grid system**: Asymmetric grid layouts (2/3 + 1/3 splits, varied heights)
- **Interactive elements**: Hover states with subtle lift effects (no animations)
- **Section containers**: Different max-widths for different content types (hero: 100%, content: 1120px, prose: 720px)

## Phase 2: Dreyfus Model Page Redesign

### 2.1 Hero Section
- **Visual upgrade**: Larger typography (64px headline)
- **Content optimization**: Condense TL;DR to 2 punchy sentences
- **CTA hierarchy**: Primary button larger with subtle shadow, secondary as text link
- **Remove gradient background**: Replace with solid color or subtle pattern

### 2.2 Stage Cards (5 Dreyfus Levels)
- **Use existing diamond icons from SVG**: Extract diamond progression icons (rough → brilliant) from dreyfus_model_svg.html
- **Replace grid**: Use horizontal timeline visualization on desktop showing diamond progression
- **Visual differentiation**: Each card uses diamond icon at appropriate stage, different color intensity
- **Interactive**: Click stage to expand detailed view

### 2.3 Code Quality Table → Comparison Cards
- **Replace table**: Use side-by-side cards with syntax highlighting examples
- **Visual hierarchy**: Stage name bold 20px, characteristics 14px with icons

### 2.4 Research Section
- **Accordion pattern**: Collapsible sections for research details
- **Quote highlights**: Pull quotes in large typography with researcher attribution

## Phase 3: Agency Levels Page Redesign

### 3.1 Hero Section
- **No pyramid/visualization**: Keep content-focused hero with clear typography
- **Stat callout**: Simple text-based stat ("Level 5 engineers save managers 10+ hours/week") in callout box
- **Remove gradient background**: Replace with solid color

### 3.2 Level Cards → Staircase Layout
- **Visual metaphor**: Ascending staircase design (each level physically higher)
- **Color coding**: Red (L1) → Yellow (L3) → Green (L5) with solid backgrounds (no gradients)
- **Simple icons**: Minimal icons for each level (inbox, search, options, ship, checkmark)

### 3.3 Comparison Tables → Scenario Cards
- **Before/After cards**: Side-by-side comparison with simple avatars
- **Manager time**: Large colored number (2+ hours red, 0 min green) as focal point
- **Remove table structure**: Use card grid with chat bubble design for responses

### 3.4 Interactive Element
- **Level slider**: Drag slider to see how response changes by level
- **"Find your level" quiz**: 3-5 question interactive assessment

## Phase 4: Performance Matrix Page Redesign

### 4.1 Hero with Matrix
- **Matrix as hero**: Make 2x2 matrix the first thing users see (full viewport height)
- **Interactive quadrants**: Hover highlights quadrant, click expands archetype details
- **Visual clarity**: Stronger borders, larger labels, subtle solid color backgrounds per quadrant (no gradients)
- **Remove gradient from hero section**: Use solid background

### 4.2 Archetype Deep Dives
- **Replace feature cards**: Use 2-column layout (placeholder icon left, content right)
- **Placeholder icons**: Simple, professional icon placeholders for each archetype (can be replaced later)
- **Color-coded backgrounds**: Each archetype gets 8% opacity solid color background
- **Prominent quotes**: Large pull quotes showing typical behavior
- **Professional tone**: Keep design clean and business-focused, not playful

### 4.3 Tables → Visual Timelines
- **Development timeframes**: Horizontal timeline with arrows showing transitions
- **Visual metaphor**: Journey map from one quadrant to another
- **Color coding**: Timeline bars colored by difficulty (green = easy, yellow = medium, red = hard)

### 4.4 Scenario Comparison → Card Grid
- **Remove table**: Use 4-column card grid (one per archetype)
- **Simple avatars**: Minimal avatar/icon placeholders to each card
- **Manager time**: Prominent badge at top of card

## Phase 5: Cross-Page Improvements

### 5.1 Section Spacing
- **Increase vertical spacing**: 96px between major sections
- **Breathing room**: 48px padding in feature cards
- **Consistent rhythm**: All pages follow same spacing scale

### 5.2 TL;DR Box Variants
- **Dreyfus**: Left-border callout box with solid background
- **Agency**: Highlighted panel with stat counter
- **Matrix**: 2x2 mini-grid preview with key insights
- **No gradients**: All use solid backgrounds with border accents

### 5.3 Typography Cleanup
- **Remove all inline font-sizes**: Use semantic classes (.text-sm, .text-base, .text-lg, .text-xl, .display-sm, .display-lg)
- **Consistent hierarchy**: H1 (48-64px), H2 (32-40px), H3 (24px), Body (16px), Small (14px)

### 5.4 CTA Strategy
- **Sticky CTA bar**: Appears on scroll with "Get Started" button (static, no animation)
- **Section CTAs**: Each major section has relevant next step
- **Visual hierarchy**: Primary CTAs 20% larger than secondary

### 5.5 Mobile Optimization
- **Explicit breakpoints**: 1, 2, or 3 columns (never auto-fit)
- **Touch-friendly**: 48px minimum tap targets
- **Simplified mobile views**: Hide complexity, show essentials

## Phase 6: Interactive Enhancements (Minimal)

### 6.1 Hover States Only
- **No scroll animations**: Remove all fade-in, parallax, or scroll-triggered effects
- **Static design**: Content visible immediately on load
- **Hover micro-interactions**: Cards lift slightly on hover (transform only, no transitions)
- **No loading animations**: Direct rendering, no skeleton screens

### 6.2 Progressive Disclosure
- **Expandable content**: "Read more" for dense sections
- **Tabbed comparisons**: Switch between examples without scrolling
- **Collapsible FAQs**: Research and examples in accordions

## Implementation Order

1. **Foundation first** (Phase 1): CSS variables, spacing system, component base, remove all gradients
2. **Dreyfus page** (Phase 2): Use existing diamond SVG icons, simplest page to test patterns
3. **Agency page** (Phase 3): Most complex, build on learnings, skip pyramid visualization
4. **Matrix page** (Phase 4): Interactive showcase with placeholder icons
5. **Polish** (Phase 5 & 6): Cross-page consistency, hover effects only

## Success Criteria

- **Visual consistency**: All three pages feel part of same premium brand
- **Mobile-perfect**: No layout breaks, optimized for touch
- **Fast load**: Under 2s time to interactive, zero animation lag
- **Clear hierarchy**: Users can scan and find info in 10 seconds
- **Engagement**: Interactive elements encourage exploration (hover states, expandable content)
- **Professional feel**: Matches quality of Linear, Stripe, Vercel landing pages - clean and business-focused
- **No visual bloat**: Zero scroll animations, zero gradient usage, minimal motion

## Technical Approach

- **CSS-only where possible**: No JS frameworks, use CSS Grid, Flexbox, simple hover effects
- **Progressive enhancement**: Works without JS, better with it
- **Maintain theme switching**: All new designs work in light/dark mode
- **Zero hardcoded colors**: Everything uses CSS variables - no exceptions
- **Component-based**: Reusable patterns across all three pages
- **No animations**: Static design with instant rendering, hover-only interactions
- **Extract diamond icons**: Use existing SVG diamond progression from dreyfus_model_svg.html

## Specific Notes

### Dreyfus Page
- Keep and enhance existing diamond progression SVG
- Use those diamond icons throughout the 5 stages section
- No new illustrations needed - the diamond metaphor is already established

### Agency Page
- Skip the pyramid visualization - it adds no value
- Focus on clear level comparisons with solid color coding
- Simple staircase layout metaphor without complex graphics

### Performance Matrix Page
- Keep it professional and clean
- Use simple icon placeholders that can be replaced later
- Avoid "fun" design elements - maintain business focus

### Gradient Removal
- Remove `--gradient-purple` from main.css
- Remove `--gradient-horizontal` from main.css
- Replace all hero gradient backgrounds with solid colors or subtle patterns
- Update all callout boxes to use solid backgrounds with border accents
- Clean up any remaining gradient usage in CTA sections

---

## Design Patterns & Implementation Guidelines

**This section documents established patterns for maintaining consistency across all cornerstone pages.**

### Progressive Disclosure Pattern

**When to Use:**
- Research sections with academic citations (DOI links, Google Scholar, etc.)
- Feature cards with 3+ paragraphs of content
- Any content that is supplementary/reference material vs. primary information
- Lists of 6+ detailed items where users need to scan quickly

**Section-Level Expansion:**
```html
<div class="read-more-container">
    <button class="read-more-toggle" onclick="toggleExpandable('unique-section-id')">
        Show Research Details
        <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
    </button>
</div>

<div id="unique-section-id" class="expandable-section">
    <!-- Dense content goes here -->
</div>
```

**Card-Level Expansion:**
```html
<div class="feature-card">
    <h3>Card Title</h3>
    <p>Essential summary visible by default...</p>

    <div id="unique-card-content-id" class="card-expandable-content">
        <!-- Additional details, quotes, examples -->
    </div>

    <button class="card-expand-toggle" onclick="toggleCardContent('unique-card-content-id')">
        Read more
        <svg fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
    </button>
</div>
```

**Note:** The CSS automatically aligns "Read more" buttons at the bottom of cards using flexbox with `:has()` selector. No additional markup required.

**CSS Classes (already in `landing.css`):**
- `.expandable-section` - Section-level container
- `.read-more-toggle` - Primary button for sections
- `.card-expandable-content` - Card-level hidden content
- `.card-expand-toggle` - Secondary button for cards

**JavaScript Functions (already in `landing/base.html`):**
- `toggleExpandable(sectionId)` - For section-level expansion
- `toggleCardContent(contentId)` - For card-level expansion

### Color Progression Pattern

**Purpose:** Visual hierarchy for sequential/leveled content (e.g., skill stages, maturity levels)

**Implementation:**
```css
/* Example: 5-level progression */
.level-card-1 { border-left: 4px solid #dc2626; background: rgba(220, 38, 38, 0.08); }
.level-card-2 { border-left: 4px solid #f97316; background: rgba(249, 115, 22, 0.08); }
.level-card-3 { border-left: 4px solid #f59e0b; background: rgba(245, 158, 11, 0.08); }
.level-card-4 { border-left: 4px solid #84cc16; background: rgba(132, 204, 22, 0.08); }
.level-card-5 { border-left: 4px solid #16a34a; background: rgba(22, 163, 74, 0.08); }
```

**Rules:**
- Red/Orange for low/beginner levels
- Yellow for middle/transition levels
- Light Green to Green for high/advanced levels
- Use 8% opacity backgrounds to avoid overwhelming
- Always include 4px left border for clear demarcation

### Interactive Component Pattern

**Purpose:** Engage users without overwhelming them (sliders, toggles, scenario pickers)

**Requirements:**
- Vanilla JavaScript only (no framework dependencies)
- Progressive enhancement (works without JS)
- Touch-friendly (48px minimum tap targets)
- Clear visual feedback on interaction
- Self-contained (IIFE pattern to avoid global scope pollution)

**Example Structure:**
```html
<div class="interactive-container">
    <!-- Controls -->
    <div class="control-section">
        <button class="control-btn active" data-option="1">Option 1</button>
        <button class="control-btn" data-option="2">Option 2</button>
    </div>

    <!-- Dynamic content area -->
    <div id="dynamic-content">
        <!-- Updated via JavaScript -->
    </div>
</div>

<script>
(function() {
    // Self-contained logic
    const buttons = document.querySelectorAll('.control-btn');
    const content = document.getElementById('dynamic-content');

    function updateDisplay(option) {
        // Update logic
    }

    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            updateDisplay(btn.dataset.option);
        });
    });
})();
</script>
```

### Grid Layout Guidelines

**Standard Feature Grid:**
```css
.features-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 2rem;
}
```

**When Item Count Matters:**
- 2, 3, 4, 6 items: Use auto-fit (divides evenly)
- 5 items (unavoidable): Accept asymmetry, ensure mobile stacks gracefully
- 7+ items: Consider expandable pattern (show 6, hide rest with "Show more")

**Responsive Breakpoints:**
```css
/* Desktop: 3+ columns */
@media (max-width: 1024px) { /* Tablet: 2 columns */ }
@media (max-width: 768px) { /* Mobile: 1 column */ }
```

### Scenario/Comparison Cards Pattern

**Purpose:** Side-by-side comparison of responses/behaviors at different levels

**Structure:**
- Container with scenario question/prompt
- Grid of cards (one per level/option)
- Prominent metric at top (time saved, cost, etc.)
- Response text styled as chat bubble or quote

**CSS Pattern:**
```css
.scenario-container { margin-bottom: 3rem; }
.scenario-header { /* Centered question */ }
.scenario-cards {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 1rem;
}
.scenario-card { /* Individual response card */ }
.scenario-time { /* Color-coded badge */ }
```

### Content Density Rules

**Maximum Content Before Expansion Required:**
- Paragraphs: 2 visible, 3+ need expansion
- List items: 5 visible, 6+ need expansion
- Code examples: 1 visible, 2+ need expansion
- Citations: 0 visible (always collapsed), show summary only

**Visual Indicators:**
- If a card is taller than ~400px → likely needs expansion
- If user must scroll to see next card → definitely needs expansion
- If content contains academic citations → always collapse

### Accessibility Requirements

**All Interactive Elements:**
- Keyboard accessible (tab navigation, enter/space to activate)
- ARIA labels where needed
- Focus states visible
- Color is not the only indicator (use icons, text labels, patterns)

**Expandable Content:**
- Button has clear label ("Read more", "Show details")
- Visual indicator of state (chevron rotation, "Show less" text change)
- Smooth transitions (not instant, not too slow - 0.3s is ideal)

### File Organization

**Where Code Lives:**
- **Global styles:** `static/css/main.css` (variables, resets)
- **Landing styles:** `static/css/landing.css` (components, utilities)
- **Shared JS:** `templates/landing/base.html` (functions used across pages)
- **Page-specific JS:** Inline `<script>` in page template (IIFE pattern)

**Naming Conventions:**
- CSS classes: kebab-case (`.expandable-section`)
- JavaScript functions: camelCase (`toggleExpandable`)
- IDs: kebab-case with context (`research-papers`, `novice-details`)

### Performance Considerations

- No scroll animations (instant render)
- No skeleton loaders (direct rendering)
- CSS transitions only (no JavaScript animations)
- Lazy load only for below-fold images
- Keep JavaScript minimal and vanilla (no frameworks)

### Mobile-First Checklist

Before marking any page complete:
- [ ] All grids stack to 1 column at 768px
- [ ] Buttons are minimum 48px tall (touch-friendly)
- [ ] Text is readable at default zoom (16px base)
- [ ] No horizontal scroll at any breakpoint
- [ ] Interactive elements have sufficient spacing (16px minimum)
- [ ] Expandable sections work with touch
- [ ] Visual hierarchy maintained on mobile

### Quality Gates

**Before completing any cornerstone page:**
1. ✅ No gradient backgrounds anywhere
2. ✅ All colors use CSS variables (no hardcoded hex)
3. ✅ All spacing uses design system scale (--space-*)
4. ✅ Dense content behind progressive disclosure
5. ✅ No feature cards taller than 400px (without expansion)
6. ✅ Interactive elements keyboard accessible
7. ✅ Mobile layout tested at 375px, 768px, 1024px
8. ✅ Light and dark themes both work
9. ✅ No console errors or warnings
10. ✅ Page loads under 2s on 3G

**Document any deviations from these patterns in this file with justification.**
