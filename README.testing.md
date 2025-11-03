# Testing Documentation

Zero-configuration Docker-based testing for Blik360.

## Quick Start

```bash
# Run all tests
./test.sh

# Run specific app tests
./test.sh accounts
./test.sh questionnaires

# Run specific test class
./test.sh accounts.tests.UserInvitationTestCase

# Run with verbose output
./test.sh -v

# Keep database between runs (faster)
./test.sh --keepdb
```

## Test Environment

The test setup includes:

- **PostgreSQL database** (temporary, in-memory)
- **Mailpit** for email testing (http://localhost:8125)
- **Sample data fixtures**:
  - Test organization
  - Admin and manager users
  - 3 test reviewees
  - Default questionnaire
  - Sample review cycle with tokens

## Email Testing

All emails sent during tests go to Mailpit:

```bash
# Open Mailpit UI
./test.sh mailpit
```

Then visit http://localhost:8125 to see all sent emails.

**Note:** Test environment uses non-standard ports to avoid conflicts:
- Mailpit Web UI: `8125` (instead of 8025)
- Mailpit SMTP: `1125` (instead of 1025)

## Test Data

### Test Data Generation

Tests use **factory_boy** to generate data programmatically (not JSON fixtures).

Key factories available:
- `OrganizationFactory` - Create test organizations
- `UserFactory` / `AdminUserFactory` - Create users
- `RevieweeFactory` - Create reviewees
- `QuestionnaireFactory` - Create questionnaires
- `QuestionSectionFactory` / `QuestionFactory` - Create questions
- `ReviewCycleFactory` - Create review cycles
- `ReviewerTokenFactory` - Create reviewer tokens

### Test Users

| Username | Email | Password | Role |
|----------|-------|----------|------|
| admin | admin@test.local | admin123 | Superuser |
| manager | manager@test.local | - | Regular user |

### Test Reviewees

- **John Developer** (john.dev@test.local) - Senior Software Engineer
- **Jane Manager** (jane.manager@test.local) - Engineering Manager
- **Bob Junior** (bob.junior@test.local) - Junior Developer

## Test Coverage

### Questionnaire Tests (`questionnaires/tests.py`)

- ✓ Fixture loading
- ✓ Questionnaire sections
- ✓ Questions

### Invite Link Tests (`questionnaires/tests.py`)

- ✓ Invitation token generation
- ✓ Token uniqueness
- ✓ Claiming invite links
- ✓ Reviewer token access

### Email Invite Tests (`questionnaires/tests.py`)

- ✓ Assigning emails to tokens
- ✓ Sending reviewer invitations
- ✓ Preventing resend to completed reviews

### Dashboard Tests (`accounts/tests.py`)

- ✓ Dashboard access
- ✓ Reviewee listing

### User Invitation Tests (`accounts/tests.py`)

- ✓ Creating invitations
- ✓ Token uniqueness
- ✓ Expiration validation
- ✓ Acceptance validation

### Report Generation Tests (`accounts/tests.py`)

- ✓ Manual report generation
- ○ Auto-generation (depends on signals)

### Reviewee Management Tests (`accounts/tests.py`)

- ✓ Listing reviewees
- ✓ Creating reviewees
- ✓ Deactivating reviewees

## Advanced Usage

### Interactive Shell

```bash
# Open Django shell in test environment
./test.sh shell

# Then in the shell:
python manage.py shell
python manage.py migrate
python manage.py loaddata core/fixtures/test_data.json
```

### Clean Environment

```bash
# Remove all test containers and volumes
./test.sh clean
```

### Setup Only

```bash
# Just start services without running tests
./test.sh setup
```

## Writing New Tests

### Test Structure

```python
from django.test import TestCase
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import RevieweeFactory

class MyTestCase(TestCase):
    def setUp(self):
        # Create test data with factories
        self.org = OrganizationFactory(name='Test Org')
        self.user = UserFactory()
        self.reviewee = RevieweeFactory(organization=self.org)

    def test_something(self):
        # Your test here
        self.assertEqual(self.org.name, 'Test Org')
        self.assertIsNotNone(self.reviewee.organization)
```

Benefits of factories over JSON fixtures:
- **Type-safe** - Catches model changes immediately
- **Flexible** - Override any field easily
- **No maintenance** - Auto-adapts to model changes
- **Readable** - Clear what data is being created

### Using Factories

Create test data programmatically:

```python
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import RevieweeFactory
from questionnaires.factories import QuestionnaireFactory

# Create organization
org = OrganizationFactory(name='Acme Corp')

# Create user
user = UserFactory(username='testuser')
user.set_password('password123')
user.save()

# Create reviewee
reviewee = RevieweeFactory(
    organization=org,
    name='John Doe',
    email='john@acme.com'
)

# Create questionnaire with questions
questionnaire = QuestionnaireFactory(organization=org)
```

### Testing Email

```python
from django.core import mail

def test_send_email(self):
    # Send email
    send_email(
        subject='Test',
        message='Body',
        recipient_list=['test@example.com']
    )

    # Check email was sent
    self.assertEqual(len(mail.outbox), 1)
    self.assertEqual(mail.outbox[0].subject, 'Test')

    # Or check in Mailpit UI at http://localhost:8125
```

### Testing Invite Links

```python
def test_invite_link(self):
    cycle = ReviewCycle.objects.get(pk=1)

    # Get invitation URL
    url = reverse('reviews:claim_token', kwargs={
        'invitation_token': cycle.invitation_token_peer
    })

    # Claim the invite
    response = self.client.get(url)

    # Should create reviewer token
    self.assertEqual(response.status_code, 200)
```

## CI/CD Integration

The test script is designed for CI/CD:

```yaml
# GitHub Actions example
- name: Run tests
  run: |
    ./test.sh --verbosity=2
```

## Troubleshooting

### Database Connection Issues

```bash
# Clean and restart
./test.sh clean
./test.sh setup
```

### Tests Hanging

Check if services are running:

```bash
docker compose -f docker-compose.test.yml ps
```

### Viewing Logs

```bash
docker compose -f docker-compose.test.yml logs -f
```

### Port Conflicts

Test environment uses non-standard ports to minimize conflicts:
- Mailpit Web UI: **8125** (not 8025)
- Mailpit SMTP: **1125** (not 1025)
- PostgreSQL: **5432** (only accessible internally, not exposed)

If you still have conflicts:

```bash
# Stop conflicting services
docker compose -f docker-compose.test.yml down

# Or check what's using the port
lsof -i :8125
lsof -i :1125
```

## Performance Tips

1. **Use `--keepdb`** for repeated test runs:
   ```bash
   ./test.sh --keepdb
   ```

2. **Run specific tests** instead of full suite:
   ```bash
   ./test.sh accounts.tests.UserInvitationTestCase
   ```

3. **Database is in-memory** (tmpfs) for speed

## Environment Variables

Test environment uses `.env.test`:

- `DATABASE_TYPE=postgres`
- `DATABASE_NAME=blik_test`
- `EMAIL_HOST=mailpit`
- `DEBUG=True`
- All security features relaxed for testing

## Manual Testing

For manual testing with real data:

```bash
# Start test environment
./test.sh setup

# Open shell
./test.sh shell

# Create test data using Django shell
python manage.py shell

# In shell:
from core.factories import *
from accounts.factories import *
from questionnaires.factories import *

org = OrganizationFactory(name='Test Org')
user = UserFactory(username='admin', is_superuser=True)
user.set_password('admin')
user.save()
reviewee = RevieweeFactory(organization=org)

# Create superuser
python manage.py createsuperuser

# Run dev server
python manage.py runserver 0.0.0.0:8000
```

Then access at http://localhost:8000 and check emails at http://localhost:8125.
