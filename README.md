# Blik

Self-hosted 360-degree feedback and performance review system.

Blik is an open-source application for conducting anonymous 360-degree feedback reviews. Built with Django, it provides organizations with a privacy-focused alternative to commercial performance review platforms.

## Quick Start

Blik supports two local startup modes:

- `docker run` starts the standalone app container and uses SQLite by default
- `docker compose` starts the full development stack and uses PostgreSQL by default

### Standalone Docker (Simplest)

For a quick evaluation with ephemeral data:

```bash
docker build -t blik .
docker run -d --name blik -p 8000:8000 blik
```

Visit `http://localhost:8000/setup/` to complete the interactive setup wizard.

To persist SQLite data across container restarts without masking the application code:

```bash
docker run -d --name blik -p 8000:8000 \
  -e DATABASE_URL=sqlite:////data/db.sqlite3 \
  -v blik-data:/data \
  blik
```

### Production Deployment

**One-Click Deploy Options:**

[![Deploy to DigitalOcean](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/thijsdezoete/blik/tree/master)

- **DigitalOcean App Platform** - Fully managed PaaS (~$20/month) - [Guide](docs/DIGITALOCEAN.md)
- **Dokploy** - Self-hosted deployment platform - [Guide](docs/DEPLOYMENT.md)

**Manual Deployment:**

See complete guides for:
- [DigitalOcean Deployment](docs/DIGITALOCEAN.md) - App Platform or Droplet setup
- [General Deployment Guide](docs/DEPLOYMENT.md) - Nginx/Caddy, email, SSL/HTTPS, backups

## Features

- **Review Access** - Token-based links and category-aggregated reports
- **Admin Dashboard** - Complete review cycle management interface
- **Four Questionnaires** - Professional Skills, Software Engineering, Manager 360, and 360 Degree Feedback templates
- **Analytical Reports** - Trends, peer benchmarks, perception gaps, and configurable reporting thresholds
- **Email Notifications** - SMTP integration for invitations
- **Setup Wizard** - Interactive first-run setup at `/setup/`
- **Docker-Ready** - Containerized deployment with SQLite or PostgreSQL

## How It Works

1. Administrator creates a review cycle and designates a reviewee
2. System generates unique access tokens for each reviewer relationship
3. Reviewers receive email invitations with tokenized access links
4. Reviewers complete feedback forms accessible only via their token
5. Responses are stored against tokens, which may contain invitation email addresses
6. Reports are generated when minimum response thresholds are met
7. Aggregated results are provided to reviewee and designated administrators

## Privacy and Security

Blik supports confidential review workflows, but tokenized access is not an anonymity guarantee against database administrators:

- Reviewers use tokenized links rather than authenticated user accounts.
- Reports aggregate feedback by rater category and support minimum response thresholds.
- Responses reference reviewer tokens; tokens may store invitation email addresses.
- Invitation methods, permissions, thresholds, and identifying free-text comments affect confidentiality.
- Export and deletion tools support GDPR obligations; organizations remain responsible for lawful processing, retention, and access controls.

### Landing-site content

Marketing templates in `templates/landing/` run under both the main application and the DB-less `landing_settings` deployment.

- `landing/context_processors.py:PRICING` supplies hosted prices, employee caps, annual equivalents, and trial length to both deployments. Keep it aligned with `subscriptions/fixtures/plans.json` and the checkout trial configuration; do not duplicate these values in page copy.
- Hosted plans cap active reviewees, not organization members. Trial copy must state that a credit card is required.
- Competitor prices retain their source currency, source link, and actual verification date. Do not turn verification dates into dynamic current-year labels.
- `templates/landing/roi_calculator.html` documents its conversion and package assumptions. It uses published Blik tiers, and shows contact pricing rather than inventing a price or savings above the largest tier.
- All landing layout, utilities, page components, and carousel styles live in `static/css/landing.css`, loaded once by the landing base and standalone page templates. Keep page-specific rules scoped to their components so they do not affect other landing pages. Shared application and SVG diagram styles remain in `static/css/main.css`, which is also loaded by reports.
- Keep presentation out of template `style` attributes, embedded style blocks, and JavaScript style writes. Use component classes, `hidden` for visibility, and native progress values. The landing base owns mobile-menu and theme handlers; child pages must not register duplicate handlers.
- Refresh checks: run `python manage.py check`, `DJANGO_SETTINGS_MODULE=landing_settings python manage.py check`, and `python manage.py test accounts subscriptions landing`. Render both deployments, parse JSON-LD, inspect the sitemap, and exercise calculator tier/minimum boundaries in a browser.

## Advanced Configuration

### Connecting to External Database

The standalone Docker image supports SQLite (default) and PostgreSQL:
```bash
docker run -d -p 8000:8000 \
  -e DATABASE_TYPE=postgres \
  -e DATABASE_URL=postgresql://user:password@host:5432/dbname \
  blik
```

Or with separate database variables:

```bash
docker run -d -p 8000:8000 \
  -e DATABASE_TYPE=postgres \
  -e DATABASE_HOST=your-db-host.example.com \
  -e DATABASE_NAME=blik \
  -e DATABASE_USER=blik_user \
  -e DATABASE_PASSWORD=your_secure_password \
  blik
```

### Key Environment Variables

**Database:**
- `DATABASE_TYPE` - `sqlite` (default) or `postgres`
- `DATABASE_URL` - Full connection string (overrides individual settings)
- `DATABASE_HOST`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` - Individual settings

**Security:**
- `SECRET_KEY` - Django secret key (auto-generated if not provided)
- `ENCRYPTION_KEY` - For encrypting SMTP passwords
- `ALLOWED_HOSTS` - Comma-separated hostnames (default: `*`)
- `DEBUG` - `True` or `False` (default: `False`)

**Email & links:**
- `SITE_DOMAIN`, `SITE_PROTOCOL` - Public URL; every link in outgoing email is built from these, not from the request host
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` - SMTP settings

Any `EMAIL_*` or `ORGANIZATION_NAME` variable you set here wins over the admin UI: it is re-applied on every container start, so those fields are shown read-only on the Settings page. Leave them unset (or empty) to configure email from the UI instead.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for complete environment variable documentation.

## Development

### Local Setup

```bash
git clone https://github.com/thijsdezoete/blik.git
cd blik
cp .env.example .env
docker compose up -d --build
```

Unlike the standalone `docker run` example above, this Docker Compose setup uses PostgreSQL by default because [`docker-compose.yml`](docker-compose.yml) starts both `web` and `db` services and sets `DATABASE_TYPE=postgres`.

Check that the web container is healthy:

```bash
docker compose logs -f web
```

Then visit `http://localhost:8000/setup/` to complete setup.

### Contributing

See the [Issues](https://github.com/thijsdezoete/blik/issues) page for current development tasks. Contributors welcome for:

- Core application development
- UI/UX design
- Documentation and technical writing
- Internationalization and localization
- Security review and testing

## Documentation

- **[Deployment Guide](docs/DEPLOYMENT.md)** - Production deployment with Dokploy, manual Docker, Nginx/Caddy setup, email configuration
- **[Admin Guide](docs/ADMIN_GUIDE.md)** - Managing review cycles, users, and questionnaires
- **[User Guide](docs/USER_GUIDE.md)** - For reviewees and reviewers
- **[Report Guide](docs/REPORT_GUIDE.md)** - Understanding feedback reports
- **[Requirements](docs/REQUIREMENTS.md)** - MVP requirements and roadmap

## Technology Stack

- **Backend:** Django 5.x with multi-organization support
- **Database:** SQLite (default) or PostgreSQL 15
- **Frontend:** Django templates with modern CSS
- **Deployment:** Docker and Docker Compose with Gunicorn
- **Static Files:** WhiteNoise for efficient static file serving
- **Email:** SMTP integration (supports Gmail, SendGrid, AWS SES, Mailgun, etc.)


## License

Blik is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](LICENSE) for details.

The AGPL license ensures that any modifications used to provide a network service must be made available as open source, while allowing free use for internal organizational purposes.
