# Multitenancy Security - Quick Reference Guide

## Critical Vulnerabilities (MUST FIX BEFORE PRODUCTION)

### 1. Reviewee Model Access
**Files**: `blik/admin_views.py` (lines 193, 218)
**Issue**: Can edit/delete other org's reviewees by guessing ID
```python
# VULNERABLE (current):
reviewee = get_object_or_404(Reviewee, id=reviewee_id)

# FIXED:
reviewee = get_object_or_404(Reviewee, id=reviewee_id, organization=request.organization)
```

### 2. Report Access
**Files**: `reports/views.py` (line 13)
**Issue**: Any staff member can view any org's reports
```python
# VULNERABLE (current):
@staff_member_required
def view_report(request, cycle_id):
    cycle = get_object_or_404(ReviewCycle, id=cycle_id)

# FIXED:
@staff_member_required
def view_report(request, cycle_id):
    cycle = get_object_or_404(
        ReviewCycle.objects.for_organization(request.organization), 
        id=cycle_id
    )
```

### 3. Bulk Operations
**Files**: `blik/admin_views.py` (line 498)
**Issue**: Bulk review cycle creation processes ALL reviewees
```python
# VULNERABLE (current):
reviewees = Reviewee.objects.filter(is_active=True)

# FIXED:
reviewees = Reviewee.objects.for_organization(request.organization).filter(is_active=True)
```

### 4. Questionnaire Preview
**Files**: `blik/admin_views.py` (line 269)
**Issue**: Can preview other org's questionnaires
```python
# VULNERABLE (current):
questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

# FIXED:
questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, organization=request.organization)
```

---

## Implementation Priority

### PHASE 1 (Do First - 30 minutes)
Create custom managers file: `/Users/tdz/projects/blik/core/managers.py`

```python
class OrganizationFilteredManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset()
    
    def for_organization(self, organization):
        if organization is None:
            return self.none()
        return self.filter(organization=organization)

class ReviewCycleManager(models.Manager):
    def for_organization(self, organization):
        if organization is None:
            return self.none()
        return self.filter(reviewee__organization=organization)

class ResponseManager(models.Manager):
    def for_organization(self, organization):
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)

class ReportManager(models.Manager):
    def for_organization(self, organization):
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)

class ReviewerTokenManager(models.Manager):
    def for_organization(self, organization):
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)
```

### PHASE 2 (Do Second - 1 hour)
Update model files to use managers:

**accounts/models.py**:
```python
from core.managers import OrganizationFilteredManager

class Reviewee(TimeStampedModel):
    # ... existing fields ...
    objects = OrganizationFilteredManager()
```

**reviews/models.py**:
```python
from core.managers import ReviewCycleManager, ReviewerTokenManager, ResponseManager

class ReviewCycle(TimeStampedModel):
    # ... existing fields ...
    objects = ReviewCycleManager()

class ReviewerToken(TimeStampedModel):
    # ... existing fields ...
    objects = ReviewerTokenManager()

class Response(TimeStampedModel):
    # ... existing fields ...
    objects = ResponseManager()
```

**reports/models.py**:
```python
from core.managers import ReportManager

class Report(TimeStampedModel):
    # ... existing fields ...
    objects = ReportManager()
```

### PHASE 3 (Do Third - 1 hour)
Fix vulnerable views in `blik/admin_views.py`:

| Line | Fix |
|------|-----|
| 193 | Add `organization=request.organization` to reviewee lookup |
| 218 | Add `organization=request.organization` to reviewee lookup |
| 498 | Add `.for_organization(request.organization)` before `.filter()` |
| 602 | Add `.for_organization(request.organization)` before `.filter()` |
| 269 | Add `organization=request.organization` to questionnaire lookup |

### PHASE 4 (Do Fourth - 30 minutes)
Fix `reports/views.py` line 13:
```python
cycle = get_object_or_404(
    ReviewCycle.objects.for_organization(request.organization),
    id=cycle_id
)
```

### PHASE 5 (Do Last - 2+ hours)
Add unit tests for organization filtering

---

## Model Relationship Map

```
Organization (root tenant)
├── UserProfile → User (manages access)
├── Reviewee (people being reviewed)
│   ├── ReviewCycle (360 feedback cycles)
│   │   ├── ReviewerToken (access tokens)
│   │   ├── Response (feedback answers)
│   │   └── Report (aggregated results)
│   └── (can auto-create via signal when user joins)
├── Questionnaire (feedback forms, nullable org FK)
│   ├── QuestionSection
│   │   └── Question (individual questions)
├── OrganizationInvitation (email invites)
└── Subscription (Stripe payment data)
```

---

## Models Requiring Organization Filtering

| Model | Filter Path | Status |
|-------|-------------|--------|
| UserProfile | `organization=org` | OK |
| Reviewee | `organization=org` | VULNERABLE - Add org filter to view queries |
| ReviewCycle | `reviewee__organization=org` | VULNERABLE - Need manager |
| ReviewerToken | `cycle__reviewee__organization=org` | VULNERABLE - Need manager |
| Response | `cycle__reviewee__organization=org` | VULNERABLE - Need manager |
| Report | `cycle__reviewee__organization=org` | VULNERABLE - Need manager |
| Questionnaire | `organization=org` | PARTIALLY OK - Handle null defaults |
| OrganizationInvitation | `organization=org` | OK |

---

## Public/Anonymous Endpoints (Different Security Model)

These use UUID tokens for security instead of organization filtering:

- `/feedback/{invitation_token}/` - Public review page (uses UUID token)
- `/reports/view/{access_token}/` - Public report view (uses UUID token)
- `/api/stripe/webhook/` - Stripe webhook (trusted source)

These are OK as-is because UUID tokens are non-enumerable and per-cycle.

---

## Testing Checklist

```python
# Test that cross-org access fails
def test_reviewee_edit_blocks_cross_org():
    org1, org2 = Organization.objects.create(...), Organization.objects.create(...)
    user = create_user_for_org(org1)
    reviewee = Reviewee.objects.create(organization=org2, ...)
    
    client.login(user)
    response = client.post(f'/admin/reviewees/{reviewee.id}/edit/', {...})
    assert response.status_code == 404

# Test that bulk operations only affect target org
def test_bulk_cycle_creation_filters_org():
    org1, org2 = Organization.objects.create(...), Organization.objects.create(...)
    user = create_user_for_org(org1)
    r1 = Reviewee.objects.create(organization=org1, ...)
    r2 = Reviewee.objects.create(organization=org2, ...)
    
    client.login(user)
    response = client.post('/admin/review-cycles/create/', {'creation_mode': 'bulk', ...})
    
    cycles = ReviewCycle.objects.filter(reviewee__organization=org1)
    assert cycles.count() == 1  # Only org1's reviewee has cycle
```

---

## Common Patterns

### Correct Pattern 1: Direct FK
```python
# When model has direct organization FK
items = Model.objects.filter(organization=request.organization)
```

### Correct Pattern 2: Indirect FK with Manager
```python
# When model filters through another model
items = Model.objects.for_organization(request.organization)
```

### Correct Pattern 3: Single Object with Org Check
```python
# When getting single object
obj = get_object_or_404(Model, id=obj_id, organization=request.organization)

# OR with manager
obj = get_object_or_404(Model.objects.for_organization(request.organization), id=obj_id)
```

### Incorrect Pattern (AVOID)
```python
# Missing organization filter
obj = get_object_or_404(Model, id=obj_id)  # VULNERABLE

# Querying all objects
items = Model.objects.all()  # VULNERABLE

# Filtering without org
items = Model.objects.filter(is_active=True)  # VULNERABLE
```

---

## Questions to Ask When Adding Features

1. Does this model have organization-scoped data? → Add organization FK or filter
2. Does this view access organization models? → Add organization filter
3. Can this be accessed by multiple org users? → Verify organization filtering
4. Is this a Stripe webhook or public endpoint? → Use UUID token security instead
5. Does this query use `.all()` or filter without org? → VULNERABLE

---

## Files Changed During Implementation

After fixing all vulnerabilities, these files will be modified:
1. `core/managers.py` - NEW FILE
2. `accounts/models.py` - Add manager
3. `reviews/models.py` - Add managers to 3 models
4. `reports/models.py` - Add manager
5. `blik/admin_views.py` - Fix 5 critical lines
6. `reports/views.py` - Fix 1 critical line

Total estimated time: **6-8 hours** including tests

---

## Emergency Hotfix (If in Production Now)

If this is already in production, apply these temporary fixes immediately:

1. Add to `core/middleware.py` - Add view permission checks
2. Add to all admin views - Check `request.organization` is not None
3. Add to all model gets - Always include organization in filter

But these are temporary - proper manager-based implementation is required.
