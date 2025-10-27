# Blik

Self-hosted 360-degree feedback and performance review system.

Blik is an open-source application for conducting anonymous 360-degree feedback reviews. Built with Django, it provides organizations with a privacy-focused alternative to commercial performance review platforms.

## Overview

360-degree feedback is a performance review method where employees receive anonymous input from multiple sources including peers, managers, direct reports, and self-assessment. Blik implements this process with a focus on true anonymity, ease of deployment, and data ownership.

## Status

Blik is production-ready with core 360-degree feedback functionality. The system includes a complete review cycle workflow, anonymous feedback collection, report generation with statistical analysis, and an easy-to-use admin dashboard.

## Features

### Core Features
- **Admin Dashboard** - Complete review cycle management interface
- **Anonymous Feedback** - Token-based access system with no reviewer tracking
- **Dual Questionnaires** - Professional Skills & Software Engineering templates (Dreyfus model-based)
- **Flexible Review Types** - Self, peer, manager, and direct report assessments
- **Analytical Reports** - Statistical analysis of feedback data with aggregation by category
- **Dynamic Invitations** - Shareable links that automatically assign available tokens
- **Email Notifications** - SMTP integration for invites and reminders
- **Privacy Controls** - Configurable anonymity thresholds per organization
- **Setup Wizard** - Interactive first-run setup at `/setup/`
- **Production-Ready** - Docker deployment with security defaults

### Planned Features
- PDF export with visualizations
- Historical trend analysis across review cycles
- Custom questionnaire builder
- REST API for external integrations
- Multi-language interface support
- LDAP/SSO authentication for administrators

## Architecture

### Technology Stack
- **Backend:** Django 5.x with multi-organization support
- **Database:** SQLite (default) or PostgreSQL 15
- **Frontend:** Django templates with modern CSS
- **Deployment:** Docker and Docker Compose with Gunicorn
- **Static Files:** WhiteNoise for efficient static file serving
- **Email:** SMTP integration (supports Gmail, SendGrid, AWS SES, Mailgun, etc.)

### Design Principles
- Anonymity-first architecture with no reviewer identity tracking
- Self-hosted deployment with no external service dependencies
- Minimal configuration required for basic operation
- Modular Django application structure for extensibility

## Quick Start

### Standalone Docker (Simplest)

Run Blik with a single Docker command using SQLite:

```bash
docker build -t blik .
docker run -d -p 8000:8000 -v blik-data:/app blik
```

Visit `http://localhost:8000/setup/` to complete the interactive setup wizard.

**Features:**
- Uses SQLite (no separate database needed)
- Auto-generates SECRET_KEY on first run
- Data persists in the `blik-data` volume
- Perfect for testing and small deployments

**For PostgreSQL instead of SQLite:**

```bash
docker run -d -p 8000:8000 \
  -e DATABASE_TYPE=postgres \
  -e DATABASE_URL=postgres://user:password@host:5432/dbname \
  -v blik-data:/app \
  blik
```

### Development with Docker Compose

For development with PostgreSQL:

```bash
git clone https://github.com/yourusername/blik.git
cd blik
cp .env.example .env
# The defaults work for local development
docker compose up -d
```

Visit `http://localhost:8000/setup/` to complete the interactive setup wizard.

### Production Deployment

**Recommended: Dokploy (One-Click Deploy)**

1. Install [Dokploy](https://dokploy.com/) on your server
2. Create a new Docker Compose application
3. Connect this repository
4. Set environment variables from `.env.production` template
5. Deploy and visit `https://yourdomain.com/setup/`

**See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for complete deployment instructions** including:
- Dokploy step-by-step guide
- Manual Docker deployment
- Nginx/Caddy reverse proxy setup
- Email provider configuration (Gmail, SendGrid, AWS SES, Mailgun)
- SSL/HTTPS configuration
- Database backups and maintenance

**Note:** SECRET_KEY is auto-generated securely on first startup if not provided. For production, it's recommended to set a persistent value in your environment variables.

## How It Works

1. Administrator creates a review cycle and designates a reviewee
2. System generates unique anonymous tokens for each reviewer relationship
3. Reviewers receive email invitations with tokenized access links
4. Reviewers complete feedback forms accessible only via their token
5. Responses are stored without attribution to reviewer identity
6. Reports are generated when minimum response thresholds are met
7. Aggregated results are provided to reviewee and designated administrators

## Privacy and Security

Blik implements several measures to ensure reviewer anonymity:

- Token-based access without user authentication for reviewers
- Configurable minimum response thresholds before displaying results
- Separation of feedback by rater category to prevent identification
- No storage of token-to-reviewer mappings in standard operation
- Rate limiting on token validation to prevent enumeration
- Administrative access does not expose individual response attribution

## Development

Development documentation will be provided as the project matures. Currently seeking contributors interested in:

- Core application development
- User interface and experience design
- Documentation and technical writing
- Internationalization and localization
- Security review and testing

See the [Issues](https://github.com/thijsdezoete/blik/issues) page for current development tasks.

## Roadmap

### Phase 1: Core Functionality
- Basic review cycle operations
- Anonymous token system implementation
- Questionnaire engine
- Response collection and storage
- Simple report generation
- Docker deployment configuration

### Phase 2: Production Readiness
- PDF export capabilities
- Enhanced reporting with visualizations
- Comprehensive test coverage
- Complete documentation
- Security audit and hardening

### Phase 3: Advanced Features
- Historical analytics and trends
- Customizable competency frameworks
- Public API with authentication
- Integration examples and plugins
- Multi-tenant support

## License

Blik is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.

The AGPL license requires that any modifications to Blik used to provide a network service must be made available as open source. This ensures that improvements to the software benefit the community while allowing free use for internal organizational purposes.

For alternative licensing arrangements, contact the project maintainers.

## Acknowledgments

- Open360 project for demonstrating open-source 360 feedback implementation
- Django Software Foundation for the web framework
- Contributors to dependencies and libraries used in this project
