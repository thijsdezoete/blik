# Blik - MVP Requirements

## Project Goal

Build a minimal but functional 360-degree feedback system that can be deployed quickly and used immediately with sensible defaults.

## Core Principles

- **Speed over features**: Get to a working POC fast
- **Defaults over configuration**: Ship with a ready-to-use 360 questionnaire
- **Simple over sophisticated**: Manual processes are acceptable, avoid complex automation
- **Anonymous first**: True reviewer anonymity is non-negotiable

## Technical Stack

- **Backend**: Django 5.x
- **Database**: PostgreSQL 15
- **Frontend**: Django templates + shadcn/ui components
- **Deployment**: Docker + Docker Compose (single command installation)
- **Task Queue**: Deferred - not needed for MVP

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
- Multi-tenant support
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
- Bulk operations
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
- Rate limiting on token validation (prevent brute force)

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
- Distribution visualization (simple bar/radar charts)
- Anonymous text comments grouped by category
- Clear indication when data is suppressed due to low response count

**Report Access:**
- Reviewee can access via email link or admin-provided access
- Report available as web view
- PDF export (nice-to-have, can be post-MVP)

**Out of scope for MVP:**
- Advanced analytics
- Historical comparisons
- Benchmarking against organization averages
- Custom report templates

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

## Data Models (High-Level)

### Core Models

```
Organization
├── name
├── email settings
└── created_at

Reviewee
├── name
├── email
├── department (optional)
├── organization FK
└── created_at

Questionnaire
├── name
├── description
├── is_default
└── sections[]

QuestionSection
├── questionnaire FK
├── title
└── order

Question
├── section FK
├── question_text
├── question_type (rating, text, multiple_choice)
├── config (JSON: scale, choices, etc.)
├── required
└── order

ReviewCycle
├── reviewee FK
├── questionnaire FK
├── created_by (admin)
├── status (active, completed)
└── created_at

ReviewerToken
├── cycle FK
├── token (UUID)
├── category (self, peer, manager, direct_report)
├── completed_at
└── created_at

Response
├── cycle FK
├── question FK
├── token FK
├── category (denormalized for reporting)
├── answer_data (JSON)
└── created_at

Report
├── cycle FK
├── generated_at
├── report_data (JSON: aggregated results)
└── available (boolean)
```

## Estimated Timeline (Solo Developer)

**Week 1: Foundation**
- Day 1-2: Django project setup, Docker configuration [COMPLETED]
  - Django 5.2.7 initialized with uv package manager
  - Docker and Docker Compose configured
  - PostgreSQL 15 database setup
  - Environment variable system
  - Six Django apps created (core, accounts, questionnaires, reviews, reports, notifications)
  - Static file serving with Whitenoise
  - System running at http://localhost:8000
- Day 3: Core models and migrations [COMPLETED]
  - Organization model with email settings
  - Reviewee model with organization FK
  - Questionnaire, QuestionSection, Question models with JSON config
  - ReviewCycle, ReviewerToken (UUID-based), Response models
  - Report model with JSON aggregation storage
  - All migrations created and applied
- Day 4-5: Django admin configuration, basic views [COMPLETED]
  - All models registered in Django admin
  - Inline editing for related models
  - List filters and search configured
  - Default 360 questionnaire fixture created (35 questions, 10 sections)
  - Dreyfus skill model integrated into technical expertise questions

**Week 2: Core Features**
- Day 6-7: Anonymous token system [COMPLETED]
  - Token-based feedback form view with UUID validation
  - Multi-section questionnaire rendering
  - Rating and text question types
  - AJAX form submission with validation
  - Response persistence in transaction
  - Token completion tracking
  - Email invitation templates (text + HTML)
  - Mailpit integration for development
- Day 8-9: Questionnaire rendering and response collection [COMPLETED]
- Day 10: Default questionnaire setup [COMPLETED]

**Week 3: Integration & Polish**
- Day 11-12: Report generation and aggregation logic [COMPLETED]
  - Report generation service with anonymity thresholds (3+ responses)
  - Aggregation by category (self, peer, manager, direct_report)
  - Average calculation for rating questions
  - Text response grouping
  - Staff-only report viewing with visualizations
  - Progress bars and category badges
  - "View Report" link in Django admin
- Day 13: Email system integration [COMPLETED]
  - Email invitation templates (HTML + text)
  - Mailpit integration for development
  - Management command for sending invitations
- Day 14: UI polish and styling [IN PROGRESS]
  - Multi-step feedback form with progress indicator
  - Simplified questionnaire (12 questions, 4 sections)
  - Clean, professional styling with gradients
  - Mobile-responsive design
  - Smooth animations and transitions
- Day 15: Testing and final polish [PENDING]

**Total: 15 working days for functional MVP**

## Success Criteria

MVP is successful if:
1. Deploys with `docker-compose up` in under 5 minutes ✓
2. First-run setup takes under 10 minutes ✓
3. Admin can create a review cycle in under 5 minutes ✓
4. Reviewers can complete feedback form in 10-15 minutes ✓
5. Reports display correctly with anonymity preserved ✓
6. Zero manual database or configuration file editing required ✓

## Current Status (93% Complete - Day 14/15)

### Completed Features
- Docker single-command deployment
- All data models with migrations
- Django admin fully configured
- Anonymous token-based feedback system
- Multi-step feedback form (4 sections)
- Simplified questionnaire (12 questions)
- Email invitation system
- Report generation with anonymity thresholds
- Report viewing interface
- Professional UI/UX

### Remaining Work

**High Priority:**
- Admin dashboard homepage with quick actions
- User management interface (add/edit reviewees and admins)
- Questionnaire selection and preview interface
- Questionnaire creation/editing interface
- Send reminders functionality for pending reviews
- Dedicated reviewee report viewing page (public-facing)

**Medium Priority:**
- PDF export for reports (optional)
- Improved email templates
- Final testing and bug fixes

**Completed Recently:**
- First-run setup wizard ✓
- Automated deployment system ✓
- Management commands for org/user setup ✓
- Production deployment documentation ✓

## Post-MVP Enhancements

After MVP validation, consider:
- Celery task queue for email sending
- Automated reminder system
- PDF export functionality
- Historical review tracking
- Custom competency frameworks
- API for integrations
- Advanced analytics
- Multi-language support
