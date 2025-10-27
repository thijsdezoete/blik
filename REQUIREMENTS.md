# Blik - MVP Requirements

## Project Goal

Build a minimal but functional 360-degree feedback system that can be deployed quickly and used immediately with sensible defaults.

## Core Principles

- **Speed over features**: Get to a working POC fast
- **Defaults over configuration**: Ship with a ready-to-use 360 questionnaire
- **Simple over sophisticated**: Manual processes are acceptable, avoid complex automation
- **Anonymous first**: True reviewer anonymity is non-negotiable

## Technical Stack

- **Backend**: Django 5.x with multi-organization support
- **Database**: PostgreSQL 15
- **Frontend**: Django templates + modern CSS
- **Deployment**: Docker + Docker Compose (single command installation)

## MVP Feature Set

### 1. Installation & Setup

**Requirements:**
- Single `docker-compose up` command to start everything
- Post-installation web-based setup wizard for:
  - Creating initial admin user
  - Configuring email settings (SMTP)
  - Basic organization info
- No manual database migrations or complex configuration files

**Out of scope:**
- LDAP/SSO integration
- Advanced configuration options

### 2. User Management

**Admin Users:**
- Simple Django admin authentication
- Create/manage admin accounts via Django admin interface
- Admins can access full system

**Reviewees (People Being Reviewed):**
- Simple model: name, email, department (optional)
- Created and managed by admins
- No login required for reviewees until they view their report

**Reviewers:**
- No user accounts
- Access via anonymous tokens only
- No authentication or registration

### 3. Questionnaire System

**Default Questionnaire:**
- Ship with a pre-configured 360-degree questionnaire covering:
  - Leadership competencies
  - Communication skills
  - Teamwork and collaboration
  - Technical/job-specific skills
  - Overall performance areas
- Question types:
  - Likert scale (1-5 rating)
  - Text response (optional comments)
  
**Flexibility:**
- Admins can create custom questionnaires
- Support for multiple question types:
  - Rating scales (1-5, 1-7, etc.)
  - Multiple choice
  - Free text
- Questionnaires organized into sections/categories
- Questions can be tagged as required or optional

**Out of scope for MVP:**
- Conditional logic / branching
- Question randomization
- Question banks/libraries

### 4. Review Cycle Management

**Core Workflow:**
1. Admin creates a review cycle for a reviewee
2. Admin specifies reviewers and their categories:
   - Self (reviewee themselves)
   - Peer
   - Manager/Supervisor
   - Direct Report
3. System generates unique anonymous token for each reviewer
4. Admin sends invites manually or via built-in email function
5. Reviewers complete feedback via token link
6. Admin manually marks cycle as complete when ready
7. Report becomes available to reviewee

**Simplifications:**
- No automatic deadlines or cycle closure
- No reminder automation (admin sends manually if needed)
- No in-progress tracking dashboards
- Manual review cycle management

**Out of scope:**
- Template review cycles
- Scheduled/recurring reviews
- Advanced workflow states

### 5. Anonymous Token System

**Requirements:**
- UUID-based tokens, cryptographically secure
- Each token maps to: reviewee + reviewer role + questionnaire
- Token provides access to feedback form only
- No tracking of reviewer identity
- Tokens do not expire (keep it simple for MVP)

**Security:**
- Admin interface CANNOT see which token belongs to which reviewer
- Responses stored without any reviewer identification
- Token-response mapping stored separately from response content

### 6. Response Collection

**Requirements:**
- Clean, professional form interface using shadcn/ui components
- Single-page or multi-step form (based on questionnaire length)
- Allow saving and returning to complete (token allows re-entry)
- Clear progress indicator
- Confirmation page after submission
- Prevent duplicate submissions (lock token after completion)

**Out of scope:**
- Draft saving
- Partial submission tracking
- Mobile app

### 7. Report Generation

**Aggregation Rules:**
- Minimum threshold: 3 responses per category before showing results
- If threshold not met: "Insufficient responses to display"
- Self-assessment always shown separately (not anonymous)

**Report Contents:**
- Overall summary scores by competency area
- Breakdown by reviewer category (peer, manager, direct report)
- Self-assessment vs others comparison
- Anonymous text comments grouped by category
- Clear indication when data is suppressed due to low response count

**Report Access:**
- Reviewee can access via email link or admin-provided access
- Report available as web view
- PDF export (nice-to-have, can be post-MVP)

**Out of scope for MVP:**
- Charts and visualizations
- Historical comparisons
- Benchmarking against organization averages

### 8. Email System

**Requirements:**
- SMTP configuration during setup
- Email templates for:
  - Reviewer invitation with token link
  - Report ready notification for reviewee
- Simple template variables (name, link, etc.)
- Sent from admin interface (manual trigger)

**Out of scope:**
- Email scheduling
- Automated reminders
- Email template customization in UI
- Email delivery tracking

### 9. Admin Interface

**Requirements:**
- Django admin for system management
- Custom admin dashboard with:
  - Quick access to common tasks
  - Overview of active review cycles
  - Recent activity summary
- User management interface:
  - Add/edit reviewees
  - Manage admin users
  - Simple user listing and search
- Questionnaire management:
  - Select from existing questionnaires
  - Preview questionnaire questions before use
  - Create new custom questionnaires
  - Edit existing questionnaires
- Review cycle management:
  - Create new review cycles
  - View cycle status and progress
  - Generate reviewer tokens
  - Send email invitations
  - Send reminders to pending reviewers (no individual tracking)
- Report access:
  - Reviewees can view their reports via email link
  - Dedicated report viewing page (not just Django admin)
  - Clean, professional report presentation

**Out of scope:**
- Analytics/reporting for admins
- Bulk operations
- Advanced user permissions

## UI/UX Requirements

**Design System:**
- Use shadcn/ui components for consistent, professional look
- Responsive design (mobile-friendly)
- Accessible (WCAG 2.1 AA compliance as goal)
- Clean, minimal interface focused on usability

**Key Pages:**
1. Setup wizard (first-run)
2. Admin login
3. Review cycle creation/management
4. Reviewer feedback form (token-based access)
5. Reviewee report view

## Next Development Phase

### 1. Enhanced Reporting & Visualization
**Priority: High**

- **Charts and Graphs**
  - Score visualization with bar charts, radar charts, or other meaningful visualizations
  - Visual comparison of self vs others ratings
  - Section-level performance summaries with graphics

- **Better Data Presentation**
  - Improve readability and usefulness of reports
  - Clear visual hierarchy for feedback data
  - Export-friendly formatting

### 2. Historical Analysis & Trends
**Priority: High**

- **Multi-Cycle Reports**
  - Show progress over time across multiple review cycles
  - Compare current vs previous performance
  - Trend visualization for each competency area

- **Growth Tracking**
  - Identify improvement areas and track progress
  - Visualize skill development over time
  - Year-over-year performance comparison

### 3. Extended Question Types
**Priority: Medium**

- **Additional Question Formats**
  - Multi-select questions (choose multiple options)
  - Matrix/grid questions (rate multiple items on same scale)
  - Ranking questions
  - Other specialized question types as needed

### 4. API & Integration Layer
**Priority: Medium**

- **REST API**
  - Programmatic cycle creation and management
  - API-based workflow automation
  - Token generation and invitation management

- **Webhooks**
  - External system notifications for cycle events
  - Integration with HR systems or other platforms

### 5. Security Enhancements
**Priority: High**

- **Rate Limiting**
  - Prevent token brute force attacks on feedback endpoints
  - Rate limiting on public pages and API endpoints
  - Configurable limits per organization

- **Additional Security Controls**
  - Enhanced access logging
  - Security audit trail
  - IP-based restrictions (optional)
