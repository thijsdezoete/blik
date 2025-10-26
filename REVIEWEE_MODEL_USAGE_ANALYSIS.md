# Reviewee Model Security Analysis

## Overview
The `Reviewee` model represents people being reviewed in 360 feedback cycles. It's a **critical security model** because:
1. It contains personal information (name, email, department)
2. It's the organizational unit for review cycles and feedback data
3. All feedback flows through the Reviewee → ReviewCycle relationship

## Model Definition

**File**: `/Users/tdz/projects/blik/accounts/models.py:72-91`

```python
class Reviewee(TimeStampedModel):
    """Person being reviewed in 360 feedback"""
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='reviewees'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    department = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'reviewees'
        ordering = ['name']
        unique_together = ['organization', 'email']
```

**Key Properties**:
- Direct `organization` ForeignKey - allows simple filtering
- `unique_together` on organization + email - prevents duplicates within org
- `is_active` boolean - soft delete flag
- Related to ReviewCycle via `review_cycles` related name

---

## Reviewee Creation Flows

### Flow 1: Auto-creation from UserProfile Signal
**File**: `accounts/signals.py:20-43`

When a user joins an organization (via Stripe signup or invitation), auto-create Reviewee:

```python
@receiver(post_save, sender=UserProfile)
def create_reviewee_from_user(sender, instance, created, **kwargs):
    if created:
        existing = Reviewee.objects.filter(
            organization=instance.organization,
            email=instance.user.email
        ).first()
        
        if not existing:
            Reviewee.objects.create(
                organization=instance.organization,
                name=instance.user.get_full_name() or instance.user.username,
                email=instance.user.email,
                is_active=True
            )
```

**Status**: SECURE - Correctly uses `instance.organization` from UserProfile

---

### Flow 2: Manual Creation in Admin
**File**: `blik/admin_views.py:152-187`

```python
def reviewee_create(request):
    """Create a new reviewee"""
    if request.method == 'POST':
        # ...
        organization = request.organization or Organization.objects.first()
        reviewee = Reviewee.objects.create(
            organization=organization,
            name=name,
            email=email,
            department=department
        )
```

**Status**: MOSTLY SECURE - Uses `request.organization` but fallback to `.first()` is concerning
**Risk**: If `request.organization` is None, uses first organization (cross-org issue)

---

### Flow 3: CSV/Bulk Import (Not Found)
No bulk import functionality found - reviewees created one at a time

---

## Reviewee Usage Across Codebase

### 1. Reviewee Listing & Management

#### Location: `blik/admin_views.py:132-148` - `reviewee_list()`
```python
def reviewee_list(request):
    """List and manage reviewees"""
    org = request.organization
    reviewees_qs = Reviewee.objects.filter(is_active=True)

    if org:
        reviewees_qs = reviewees_qs.filter(organization=org)

    reviewees = reviewees_qs.annotate(
        cycle_count=Count('review_cycles')
    ).order_by('name')
```

**Status**: PARTIALLY VULNERABLE
- Checks if `org` exists before filtering
- If `org` is None, returns ALL active reviewees from ALL organizations
- **Risk**: Staff without profile organization could see all reviewees

**Fix**:
```python
if not org:
    messages.error(request, 'No organization found.')
    return redirect('admin_dashboard')

reviewees = Reviewee.objects.filter(organization=org, is_active=True)
```

---

#### Location: `blik/admin_views.py:152-187` - `reviewee_create()`
```python
def reviewee_create(request):
    organization = request.organization or Organization.objects.first()
    if not organization:
        messages.error(request, 'No organization found.')
        return redirect('admin_dashboard')

    reviewee = Reviewee.objects.create(
        organization=organization,
        name=name,
        email=email,
        department=department
    )
```

**Status**: PARTIALLY VULNERABLE
- Has fallback to `Organization.objects.first()` if no organization
- **Risk**: Creates reviewee in WRONG organization if request context is lost

**Fix**: Remove fallback, require organization
```python
if not request.organization:
    messages.error(request, 'No organization found.')
    return redirect('admin_dashboard')

reviewee = Reviewee.objects.create(
    organization=request.organization,
    name=name,
    email=email,
    department=department
)
```

---

### 2. Reviewee Editing

#### Location: `blik/admin_views.py:191-212` - `reviewee_edit()`
```python
def reviewee_edit(request, reviewee_id):
    """Edit an existing reviewee"""
    reviewee = get_object_or_404(Reviewee, id=reviewee_id)
    
    if request.method == 'POST':
        reviewee.name = request.POST.get('name', reviewee.name)
        reviewee.email = request.POST.get('email', reviewee.email)
        reviewee.department = request.POST.get('department', '')
        reviewee.save()
```

**Status**: CRITICAL VULNERABILITY
- **No organization filter on lookup**
- User A can edit User B's reviewee by guessing ID
- POST request allows modification without permission check

**Attack**:
```python
# User from Org A can:
POST /admin/dashboard/reviewees/999/edit/
  name=Hacked
  # Modifies Org B's reviewee with ID 999
```

**Fix**:
```python
def reviewee_edit(request, reviewee_id):
    reviewee = get_object_or_404(
        Reviewee, 
        id=reviewee_id, 
        organization=request.organization
    )
```

---

### 3. Reviewee Deletion

#### Location: `blik/admin_views.py:216-230` - `reviewee_delete()`
```python
def reviewee_delete(request, reviewee_id):
    """Soft delete a reviewee"""
    reviewee = get_object_or_404(Reviewee, id=reviewee_id)
    
    if request.method == 'POST':
        reviewee.is_active = False
        reviewee.save()
```

**Status**: CRITICAL VULNERABILITY
- **No organization filter on lookup**
- User A can deactivate User B's reviewees
- No permission check before soft delete

**Attack**:
```python
# User from Org A can:
POST /admin/dashboard/reviewees/999/delete/
  # Deactivates Org B's reviewee with ID 999
```

**Fix**:
```python
def reviewee_delete(request, reviewee_id):
    reviewee = get_object_or_404(
        Reviewee,
        id=reviewee_id,
        organization=request.organization
    )
```

---

### 4. ReviewCycle Creation (Reviewee Selection)

#### Location: `blik/admin_views.py:596-602` - `review_cycle_create()` (Form Display)
```python
# User can only create cycles for themselves (permission-based)
if hasattr(request.user, 'profile') and not request.user.profile.can_create_cycles_for_others:
    reviewees = Reviewee.objects.filter(
        is_active=True,
        email=request.user.email
    ).order_by('name')
else:
    reviewees = Reviewee.objects.filter(is_active=True).order_by('name')
```

**Status**: VULNERABLE
- When user CAN create for others, shows ALL active reviewees from ALL orgs
- Form dropdown displays all reviewees globally

**Attack**: User sees all other org's reviewees in dropdown

**Fix**:
```python
# Always filter by organization
reviewees = Reviewee.objects.filter(
    organization=request.organization,
    is_active=True
).order_by('name')

if not request.user.profile.can_create_cycles_for_others:
    # Additional filter for users who can only create for themselves
    reviewees = reviewees.filter(email=request.user.email)
```

---

#### Location: `blik/admin_views.py:498-505` - `review_cycle_create()` (Bulk Mode)
```python
if creation_mode == 'bulk':
    reviewees = Reviewee.objects.filter(is_active=True)  # NO ORG FILTER!
    
    for reviewee in reviewees:
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
            created_by=request.user,
            status='active'
        )
```

**Status**: CRITICAL VULNERABILITY
- Bulk mode creates cycles for ALL active reviewees
- Cycles would be created for ALL organizations
- All get notification emails, all create review tokens

**Attack**:
```python
# User from Org A clicks "Create bulk review cycles"
# Creates cycles for EVERY active reviewee from EVERY organization
# If 100 reviewees across 10 orgs, creates 100 cycles in seconds
# Sends 100 notification emails to random people
```

**Fix**:
```python
if creation_mode == 'bulk':
    reviewees = Reviewee.objects.filter(
        organization=request.organization,
        is_active=True
    )
    
    for reviewee in reviewees:
        cycle = ReviewCycle.objects.create(...)
```

---

### 5. Subscription Limit Checking

#### Location: `subscriptions/utils.py:6-30`
```python
def check_employee_limit(request):
    """Check if organization can add more employees based on subscription plan"""
    # ...
    active_reviewees = Reviewee.objects.filter(
        organization=request.organization,
        is_active=True
    ).count()
    
    if active_reviewees >= subscription.plan.max_employees:
        return False, f"You've reached your plan limit..."
```

**Status**: SECURE - Correctly filters by `request.organization`

---

#### Location: `subscriptions/utils.py:33-58`
```python
def get_subscription_status(organization):
    """Get subscription status and usage information"""
    active_reviewees = Reviewee.objects.filter(
        organization=organization,
        is_active=True
    ).count()
```

**Status**: SECURE - Takes organization as parameter and filters correctly

---

### 6. Reviewee in Templates/Forms

#### Location: `blik/admin_views.py:592`
```python
# GET request - show form
reviewees = Reviewee.objects.filter(is_active=True).order_by('name')

# ... later ...
context = {
    'reviewees': reviewees,
    'questionnaires': questionnaires,
}
```

**Status**: VULNERABLE
- Returns all reviewees globally
- Form dropdown shows all org's reviewees

**Fix**: Add organization filter before returning context

---

## Related Model Access Through Reviewee

### ReviewCycle → Reviewee
```python
class ReviewCycle(TimeStampedModel):
    reviewee = models.ForeignKey(Reviewee, ...)
    
    @property
    def organization(self):
        return self.reviewee.organization
```

**Implication**: Every ReviewCycle must have valid reviewee from correct organization

### Response → ReviewCycle → Reviewee → Organization
```python
Response.objects.filter(cycle__reviewee__organization=org)
```

**Implication**: Feedback data is accessible through reviewee relationship

---

## Reviewee Unique Constraints

**Definition**: `unique_together = ['organization', 'email']`

**Meaning**: 
- Email must be unique WITHIN organization
- Same email can exist in different organizations
- Prevents duplicate reviewees in same org
- Allows team member with same email in different org instances

**Security**: GOOD - Prevents accidental duplicates

---

## Data Flow: Reviewee Security Implications

```
Reviewee Creation
  ↓
UserProfile Signal (auto-create from email)
  OR Manual creation in admin (admin_views.py)
  ↓
Reviewee stored in database
  ↓
ReviewCycle references Reviewee
  ↓
ReviewerToken references ReviewCycle
  ↓
Response references ReviewCycle
  ↓
Report aggregates from Response
  ↓
Public view uses Report.access_token (UUID - secure)
  OR
  Admin views access via Reviewee ID (VULNERABLE)
```

---

## Reviewee Security Checklist

### Critical - Fix Before Production
- [ ] `reviewee_edit()` - Add `organization=request.organization` filter
- [ ] `reviewee_delete()` - Add `organization=request.organization` filter
- [ ] `review_cycle_create()` bulk mode - Add org filter to reviewee query
- [ ] `review_cycle_create()` form - Add org filter to dropdown reviewees
- [ ] `reviewee_list()` - Handle None organization case

### High Priority - Implement Manager
- [ ] Create `OrganizationFilteredManager` for Reviewee
- [ ] Use in all view queries: `Reviewee.objects.for_organization(org)`

### Medium Priority - Hardening
- [ ] Add permission check for `can_create_cycles_for_others`
- [ ] Add audit logging for reviewee modifications
- [ ] Add test coverage for cross-org access

---

## Testing Requirements for Reviewee

```python
class RevieweeSecurityTests(TestCase):
    """Test organization isolation for Reviewee model"""
    
    def setUp(self):
        self.org1 = Organization.objects.create(name='Org1')
        self.org2 = Organization.objects.create(name='Org2')
        
        self.user1 = create_user_with_profile('user1', self.org1)
        self.user2 = create_user_with_profile('user2', self.org2)
        
        self.rev1 = Reviewee.objects.create(
            organization=self.org1, 
            name='Rev1', 
            email='rev1@org1.com'
        )
        self.rev2 = Reviewee.objects.create(
            organization=self.org2,
            name='Rev2',
            email='rev2@org2.com'
        )
    
    def test_cannot_edit_reviewee_from_other_org(self):
        """User1 from Org1 cannot edit Org2's reviewee"""
        self.client.login(username='user1', password='pw')
        
        response = self.client.post(
            f'/admin/dashboard/reviewees/{self.rev2.id}/edit/',
            {'name': 'Hacked', 'email': self.rev2.email}
        )
        
        assert response.status_code == 404
        self.rev2.refresh_from_db()
        assert self.rev2.name == 'Rev2'  # Not changed
    
    def test_cannot_delete_reviewee_from_other_org(self):
        """User1 from Org1 cannot delete Org2's reviewee"""
        self.client.login(username='user1', password='pw')
        
        response = self.client.post(
            f'/admin/dashboard/reviewees/{self.rev2.id}/delete/'
        )
        
        assert response.status_code == 404
        self.rev2.refresh_from_db()
        assert self.rev2.is_active == True  # Not deactivated
    
    def test_bulk_cycle_creation_only_affects_own_org(self):
        """Bulk cycle creation in Org1 doesn't affect Org2's reviewees"""
        self.client.login(username='user1', password='pw')
        
        questionnaire = Questionnaire.objects.create(
            organization=self.org1,
            name='Test'
        )
        
        response = self.client.post(
            '/admin/dashboard/review-cycles/create/',
            {
                'creation_mode': 'bulk',
                'questionnaire': questionnaire.id,
                'self_count': 1,
                'peer_count': 0,
                'manager_count': 0,
                'direct_report_count': 0,
            }
        )
        
        # Only Org1's reviewee should have a cycle
        cycles = ReviewCycle.objects.filter(reviewee__organization=self.org1)
        assert cycles.count() == 1
        
        cycles_org2 = ReviewCycle.objects.filter(reviewee__organization=self.org2)
        assert cycles_org2.count() == 0
    
    def test_reviewee_dropdown_only_shows_own_org(self):
        """Review cycle form only shows own org's reviewees"""
        self.client.login(username='user1', password='pw')
        
        response = self.client.get('/admin/dashboard/review-cycles/create/')
        
        # Check that form context only has org1's reviewees
        assert self.rev1 in response.context['reviewees']
        assert self.rev2 not in response.context['reviewees']
```

---

## Summary: Reviewee Model Risks

| Location | Issue | Severity | Fix |
|----------|-------|----------|-----|
| `reviewee_edit()` line 193 | No org filter | CRITICAL | Add organization param |
| `reviewee_delete()` line 218 | No org filter | CRITICAL | Add organization param |
| `review_cycle_create()` bulk line 498 | No org filter | CRITICAL | Add org filter before loop |
| `review_cycle_create()` form line 602 | No org filter | HIGH | Add org filter to dropdown |
| `reviewee_list()` line 138 | Fallback missing | MEDIUM | Require organization |

**Total Reviewee Security Fixes Needed**: 5 critical/high-priority locations
**Estimated Fix Time**: 1-2 hours
**Risk if Not Fixed**: Users can view, edit, delete, and create cycles for reviewees in other organizations
