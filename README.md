# Blik

Self-hosted 360-degree feedback and performance review system.

Blik is an open-source application for conducting anonymous 360-degree feedback reviews. Built with Django, it provides organizations with a privacy-focused alternative to commercial performance review platforms.

## Overview

360-degree feedback is a performance review method where employees receive anonymous input from multiple sources including peers, managers, direct reports, and self-assessment. Blik implements this process with a focus on true anonymity, ease of deployment, and data ownership.

## Status

Blik is currently in early development (pre-alpha). The core functionality is being actively developed. Production use is not recommended at this time.

## Features

### Current Implementation
- Review cycle management and administration
- Token-based anonymous access system
- Customizable questionnaires with multiple question types
- Multi-rater categories (self, peer, manager, direct report)
- Response aggregation with configurable anonymity thresholds
- Email notification system
- Docker-based deployment

### Planned Features
- PDF report generation with visualizations
- Historical review cycle tracking and comparison
- Custom competency framework definitions
- REST API for external integrations
- Multi-language interface support
- LDAP/SSO authentication for administrators

## Architecture

### Technology Stack
- Backend: Django 5.x with Django REST Framework
- Database: PostgreSQL 15
- Task Queue: Celery with Redis broker
- Frontend: Django templates with Alpine.js
- Visualization: Chart.js
- PDF Generation: WeasyPrint
- Containerization: Docker and Docker Compose

### Design Principles
- Anonymity-first architecture with no reviewer identity tracking
- Self-hosted deployment with no external service dependencies
- Minimal configuration required for basic operation
- Modular Django application structure for extensibility

## Installation

Blik is not yet ready for installation. Installation documentation will be provided with the first alpha release.

Planned installation method:

```bash
git clone https://github.com/yourusername/blik.git
cd blik
cp .env.example .env
# Configure .env with your settings
docker-compose up -d
```

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
