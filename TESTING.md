# Testing Quick Reference

## Run Tests

```bash
./test.sh              # All tests
./test.sh accounts     # Specific app
./test.sh --keepdb     # Faster (keep DB)
./test.sh -v           # Verbose
```

## Utilities

```bash
./test.sh shell        # Interactive shell
./test.sh mailpit      # Open email UI (http://localhost:8125)
./test.sh clean        # Clean up
```

## Write Tests

```python
from django.test import TestCase
from core.factories import OrganizationFactory, UserFactory
from accounts.factories import RevieweeFactory

class MyTest(TestCase):
    def setUp(self):
        self.org = OrganizationFactory(name='Acme')
        self.user = UserFactory(username='john')

    def test_something(self):
        self.assertEqual(self.org.name, 'Acme')
```

## Available Factories

- `OrganizationFactory` - Organizations
- `UserFactory`, `AdminUserFactory` - Users
- `RevieweeFactory` - Reviewees
- `QuestionnaireFactory` - Questionnaires
- `QuestionFactory` - Questions
- `ReviewCycleFactory` - Review cycles
- `ReviewerTokenFactory` - Reviewer tokens

See `README.testing.md` for full documentation.
