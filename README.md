# Blik

Self-hosted 360-degree feedback and performance review system.

Blik is an open-source application for conducting anonymous 360-degree feedback reviews. Built with Django, it provides organizations with a privacy-focused alternative to commercial performance review platforms.

## Quick Start

### Standalone Docker (Simplest)

Run Blik with a single Docker command:

```bash
docker build -t blik .
docker run -d -p 8000:8000 -v blik-data:/app blik
```

Visit `http://localhost:8000/setup/` to complete the interactive setup wizard.

### Production Deployment

**One-Click Deploy Options:**

[![Deploy to DigitalOcean](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/thijsdezoete/blik/tree/master&refcode=your-referral-code)

- **DigitalOcean App Platform** - Fully managed PaaS (~$20/month) - [Guide](docs/DIGITALOCEAN.md)
- **Dokploy** - Self-hosted deployment platform - [Guide](docs/DEPLOYMENT.md)

**Manual Deployment:**

See complete guides for:
- [DigitalOcean Deployment](docs/DIGITALOCEAN.md) - App Platform or Droplet setup
- [General Deployment Guide](docs/DEPLOYMENT.md) - Nginx/Caddy, email, SSL/HTTPS, backups

## Features

- **Anonymous Feedback** - Token-based access system with no reviewer tracking
- **Admin Dashboard** - Complete review cycle management interface
- **Dual Questionnaires** - Professional Skills & Software Engineering templates (Dreyfus model-based)
- **Analytical Reports** - Statistical analysis with configurable anonymity thresholds
- **Email Notifications** - SMTP integration for invites and reminders
- **Setup Wizard** - Interactive first-run setup at `/setup/`
- **Docker-Ready** - Single command deployment with SQLite or PostgreSQL

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

## Advanced Configuration

### Connecting to External Database

The standalone Docker image supports SQLite (default) and PostgreSQL:
```bash
docker run -d -p 8000:8000 \
  -e DATABASE_TYPE=postgres \
  -e DATABASE_URL=postgresql://user:password@host:5432/dbname \
  -v blik-data:/app \
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
  -v blik-data:/app \
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

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for complete environment variable documentation.

## Development

### Local Setup

```bash
git clone https://github.com/yourusername/blik.git
cd blik
cp .env.example .env
docker compose up -d
```

Visit `http://localhost:8000/setup/` to complete setup.

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
