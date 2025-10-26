# Multitenancy Security Analysis: Django Blik Application

## Executive Summary

This Django application has **critical multitenancy security gaps** that could allow users to access, modify, or delete data belonging to other organizations. The application uses organization-based multitenancy via the `Organization` model and stores organization relationships through ForeignKey relationships in most models, but **lacks custom model managers to enforce organization-level filtering at the ORM level**.

This creates a **security vulnerability**: any endpoint that queries models without explicitly filtering by organization could expose data across organization boundaries.

---

## 1. MODEL ARCHITECTURE & RELATIONSHIPS

### Organization Model (Root Tenant)
**File**: `/Users/tdz/projects/blik/core/models.py`

```python
class Organization(TimeStampedModel):
    """Organization model for multi-tenant support"""
    name = models.CharField(max_length=255)
    email = models.EmailField()
    # ... settings for SMTP, reports, registration, etc.
```

**Key Properties**:
- No custom manager - default manager used
- Root tenant identifier for all organization-specific data
- Single OneToOneField to Subscription

---

### Direct Organization Relationships

#### 1. **UserProfile** (Direct FK)
**File**: `/Users/tdz/projects/blik/accounts/models.py`
```python
class UserProfile(TimeStampedModel):
    user = models.OneToOneField(User)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    can_create_cycles_for_others = models.BooleanField(default=False)
```
**Usage**: Maps Django User to Organization
**Risk Level**: CRITICAL - User access depends on correct organization filtering

---

#### 2. **Reviewee** (Direct FK)
**File**: `/Users/tdz/projects/blik/accounts/models.py`
```python
class Reviewee(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    department = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['organization', 'email']
```
**Risk Level**: CRITICAL - Person being reviewed, sensitive data
**Security Concern**: 
- Referenced in multiple views with incomplete filtering
- Auto-created via signal when UserProfile created
- Emails can be accessed across organizations if filtering fails

---

#### 3. **Questionnaire** (Direct FK - Nullable)
**File**: `/Users/tdz/projects/blik/questionnaires/models.py`
```python
class Questionnaire(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
```
**Risk Level**: HIGH - Nullable FK allows default questionnaires but can cause confusion
**Upstream Impact**: Used in ReviewCycle creation and report generation

---

#### 4. **OrganizationInvitation** (Direct FK)
**File**: `/Users/tdz/projects/blik/accounts/models.py`
```python
class OrganizationInvitation(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(User)
    expires_at = models.DateTimeField()
    
    class Meta:
        unique_together = ['organization', 'email']
```
**Risk Level**: MEDIUM - Could expose invitation tokens/emails

---

#### 5. **Subscription** (Direct OneToOne FK)
**File**: `/Users/tdz/projects/blik/subscriptions/models.py`
```python
class Subscription(TimeStampedModel):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan)
    stripe_customer_id = models.CharField(max_length=255, unique=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
```
**Risk Level**: CRITICAL - Stripe payment data, billing information

---

### Indirect Organization Relationships (Through Reviewee)

#### 6. **ReviewCycle** (Through Reviewee)
**File**: `/Users/tdz/projects/blik/reviews/models.py`
```python
class ReviewCycle(TimeStampedModel):
    reviewee = models.ForeignKey(Reviewee)  # → organization through reviewee
    questionnaire = models.ForeignKey(Questionnaire)
    created_by = models.ForeignKey(User)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    
    @property
    def organization(self):
        return self.reviewee.organization  # Property, not database relation
```
**Risk Level**: CRITICAL - Central model for 360 feedback cycles
**Security Issue**: Organization accessed via property, not direct FK - requires navigation through reviewee
**Impact Chain**: ReviewerToken → ReviewCycle → Reviewee → Organization

---

#### 7. **ReviewerToken** (Through ReviewCycle)
**File**: `/Users/tdz/projects/blik/reviews/models.py`
```python
class ReviewerToken(TimeStampedModel):
    cycle = models.ForeignKey(ReviewCycle)  # → organization through cycle → reviewee
    token = models.UUIDField(unique=True, editable=False, db_index=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    reviewer_email = models.EmailField(null=True, blank=True)
    invitation_sent_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
```
**Risk Level**: CRITICAL - Anonymous reviewer access tokens
**Security Issue**: No direct organization FK - must traverse cycle→reviewee→organization
**Impact**: Could expose invitation tokens and anonymity across orgs

---

#### 8. **Response** (Through ReviewCycle & Question)
**File**: `/Users/tdz/projects/blik/reviews/models.py`
```python
class Response(TimeStampedModel):
    cycle = models.ForeignKey(ReviewCycle)
    question = models.ForeignKey(Question)
    token = models.ForeignKey(ReviewerToken)
    category = models.CharField(max_length=20)
    answer_data = models.JSONField()  # The actual feedback data
```
**Risk Level**: CRITICAL - Sensitive feedback responses
**Security Issue**: No direct organization FK - requires deep navigation
**Impact**: Employee feedback could leak across organizations

---

#### 9. **Report** (Through ReviewCycle)
**File**: `/Users/tdz/projects/blik/reports/models.py`
```python
class Report(TimeStampedModel):
    cycle = models.OneToOneField(ReviewCycle)
    access_token = models.UUIDField(unique=True)
    report_data = models.JSONField()  # Aggregated feedback results
```
**Risk Level**: CRITICAL - Aggregated feedback analysis
**Security Issue**: Organization determined solely through cycle relationship

---

#### 10. **Question & QuestionSection** (Through Questionnaire)
**File**: `/Users/tdz/projects/blik/questionnaires/models.py`
```python
class QuestionSection(TimeStampedModel):
    questionnaire = models.ForeignKey(Questionnaire)
    title = models.CharField(max_length=255)

class Question(TimeStampedModel):
    section = models.ForeignKey(QuestionSection)
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
```
**Risk Level**: MEDIUM - Question content not sensitive but should be isolated by org

---

## 2. CRITICAL FILTERING GAPS IN VIEWS

### admin_views.py - Dashboard & Management
**File**: `/Users/tdz/projects/blik/blik/admin_views.py`

| View | Model Queries | Filtering Issues |
|------|---------------|------------------|
| `dashboard()` | ReviewCycle, Reviewee, ReviewerToken | PARTIALLY OK - filters by org where needed |
| `reviewee_list()` | Reviewee | PARTIALLY OK - filters by org |
| `reviewee_edit()` | Reviewee | VULNERABLE - `get_object_or_404(Reviewee, id=reviewee_id)` - NO ORG FILTER |
| `reviewee_delete()` | Reviewee | VULNERABLE - No org filter |
| `questionnaire_list()` | Questionnaire, Question | PARTIALLY OK but complex |
| `questionnaire_edit()` | Questionnaire, Question, QuestionSection | VULNERABLE - Manual org filter in get_object_or_404() |
| `review_cycle_create()` | ReviewCycle, ReviewerToken, Reviewee, Questionnaire | PARTIALLY OK but incomplete |
| `review_cycle_detail()` | ReviewCycle, ReviewerToken, Report | PARTIALLY OK - uses helper |
| `questionnaire_preview()` | Questionnaire | VULNERABLE - `get_object_or_404(Questionnaire, id=questionnaire_id)` - NO ORG FILTER |

**Example Vulnerability**:
```python
# Line 191 - VULNERABLE
def reviewee_edit(request, reviewee_id):
    reviewee = get_object_or_404(Reviewee, id=reviewee_id)
    # No organization filter! User from Org A can edit Org B's reviewee
```

**Correct Pattern**:
```python
def reviewee_edit(request, reviewee_id):
    reviewee = get_object_or_404(Reviewee, id=reviewee_id, organization=request.organization)
```

**Critical Lines**:
- **Line 193**: `get_object_or_404(Reviewee, id=reviewee_id)` - missing org filter
- **Line 218**: `get_object_or_404(Reviewee, id=reviewee_id)` - missing org filter
- **Line 269**: `get_object_or_404(Questionnaire, id=questionnaire_id)` - no org filter
- **Line 498**: `Reviewee.objects.filter(is_active=True)` - bulk operations missing org

---

### reviews/views.py - Feedback & Responses
**File**: `/Users/tdz/projects/blik/reviews/views.py`

| View | Query | Risk |
|------|-------|------|
| `claim_token()` | Filter by invitation token only | MODERATE - tokens are UUIDs (secure) but cycle access is implicit |
| `feedback_form()` | `get_object_or_404(ReviewerToken, token=token)` | MODERATE - UUID token is secure but could enumerate |
| `submit_feedback()` | Filter Response/Question by cycle | OK - cycle access already validated |
| `feedback_complete()` | `get_object_or_404(ReviewerToken, token=token)` | MODERATE - UUID tokens are per-cycle |

**Issue**: Public feedback endpoints don't validate organization, but they use UUID tokens for security (not relying on organization filtering).

---

### reports/views.py - Report Access
**File**: `/Users/tdz/projects/blik/reports/views.py`

| View | Query | Issue |
|------|-------|-------|
| `view_report()` | `get_object_or_404(ReviewCycle, id=cycle_id)` | VULNERABLE - @staff_member_required but no org filter |
| `regenerate_report()` | Same as above | VULNERABLE |
| `reviewee_report()` | `Report.objects.get(access_token=access_token)` | OK - access token is UUID (secure public access) |

**Critical Line 13**:
```python
@staff_member_required
def view_report(request, cycle_id):
    cycle = get_object_or_404(ReviewCycle, id=cycle_id)  # NO ORG FILTER!
    # Staff from Org A can view Org B's reports
```

---

### subscriptions/views.py - Subscription & Checkout
**File**: `/Users/tdz/projects/blik/subscriptions/views.py`

| Query | Filtering |
|-------|-----------|
| Subscription lookups by Stripe IDs | OK - Stripe IDs are unique |
| User creation/lookup | OK - email is case-sensitive unique check |
| Organization creation | OK - only from Stripe webhook |

**Risk**: LOWER in this module - Stripe webhooks are trusted sources and lookups use unique Stripe IDs

---

### accounts/invitation_views.py - Invitations
**File**: `/Users/tdz/projects/blik/accounts/invitation_views.py`

Handles invitation acceptance - needs review for complete filtering.

---

## 3. DETAILED VULNERABILITY MATRIX

### Highest Risk - Direct Organization FK Models

| Model | Where Used | Missing Org Filter |
|-------|------------|-------------------|
| **Reviewee** | admin_views (reviewee_edit, reviewee_delete), subscriptions/utils | reviewee_edit(L193), reviewee_delete(L218) |
| **ReviewCycle** | reports/views (view_report) | view_report(L13) |
| **Questionnaire** | admin_views (questionnaire_preview) | questionnaire_preview(L269) |
| **UserProfile** | Core access control | Generally OK but check all profile access |
| **Subscription** | subscriptions/views | OK - via Stripe ID |
| **OrganizationInvitation** | accounts | Generally OK |

### High Risk - Indirect Organization FK Models (Deep Chain)

| Model | Access Chain | Risk |
|-------|--------------|------|
| **ReviewerToken** | token.cycle.reviewee.organization | UUID token secures access, but querysets need org filter |
| **Response** | response.cycle.reviewee.organization | Could expose feedback across orgs |
| **Report** | report.cycle.reviewee.organization | Aggregated sensitive data |
| **Question** | question.section.questionnaire.organization | Medium risk |

---

## 4. IDENTIFIED VULNERABILITIES IN DETAIL

### A. Direct Object Access Without Organization Filter

**Location**: `admin_views.py:191-212` - `reviewee_edit()`
```python
def reviewee_edit(request, reviewee_id):
    reviewee = get_object_or_404(Reviewee, id=reviewee_id)  # VULNERABLE
    if request.method == 'POST':
        reviewee.name = request.POST.get('name', reviewee.name)
        # ... saves without org check
```
**Attack**: User from Org A can guess Org B's reviewee ID and edit their profile
**Severity**: CRITICAL

---

**Location**: `admin_views.py:216-224` - `reviewee_delete()`
```python
def reviewee_delete(request, reviewee_id):
    reviewee = get_object_or_404(Reviewee, id=reviewee_id)  # VULNERABLE
    if request.method == 'POST':
        reviewee.is_active = False
        reviewee.save()
```
**Attack**: User from Org A can deactivate Org B's reviewees
**Severity**: CRITICAL

---

**Location**: `admin_views.py:267-277` - `questionnaire_preview()`
```python
def questionnaire_preview(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)  # VULNERABLE
```
**Attack**: User can preview questionnaires from other organizations
**Severity**: HIGH

---

**Location**: `reports/views.py:13` - `view_report()`
```python
@staff_member_required
def view_report(request, cycle_id):
    cycle = get_object_or_404(ReviewCycle, id=cycle_id)  # VULNERABLE
    # @staff_member_required only checks is_staff, not organization
```
**Attack**: Any staff member can view any organization's reports
**Severity**: CRITICAL

---

### B. Bulk Operations Without Organization Filter

**Location**: `admin_views.py:498-505` - `review_cycle_create()` (bulk mode)
```python
if creation_mode == 'bulk':
    reviewees = Reviewee.objects.filter(is_active=True)  # VULNERABLE - NO ORG FILTER
    for reviewee in reviewees:
        cycle = ReviewCycle.objects.create(
            reviewee=reviewee,
            questionnaire=questionnaire,
        )
```
**Attack**: Bulk cycle creation would process ALL reviewees across all orgs
**Severity**: CRITICAL

---

**Location**: `admin_views.py:602-603` - `review_cycle_create()` (single mode reviewees list)
```python
reviewees = Reviewee.objects.filter(is_active=True).order_by('name')
```
**Impact**: Form dropdown shows ALL reviewees from all orgs
**Severity**: HIGH

---

### C. Querysets Without Organization Filter

**Location**: `blik/admin_views.py:242-256` - `questionnaire_list()`
```python
questionnaires_qs = Questionnaire.objects.filter(
    organization=org
) if org else Questionnaire.objects.filter(organization__isnull=False)
```
**Issue**: Returns all non-null org questionnaires if org is None (fallback to staff check)
**Risk**: Staff without profile gets all questionnaires
**Severity**: MEDIUM

---

### D. Model Property vs. Direct FK for Organization

**Location**: `reviews/models.py:35-38`
```python
class ReviewCycle(TimeStampedModel):
    reviewee = models.ForeignKey(Reviewee)
    
    @property
    def organization(self):
        return self.reviewee.organization  # Property, not real FK
```

**Problem**: 
- No direct `organization` FK field
- Requires database traversal for filtering
- Filters like `filter(organization=org)` won't work
- Must use `filter(reviewee__organization=org)` instead

**Example Error Risk**:
```python
# This WORKS
ReviewCycle.objects.filter(reviewee__organization=org)

# But if code is refactored to use .organization property:
# This FAILS (silently returns all)
ReviewCycle.objects.filter(organization=org)
```

---

### E. Nullable Organization FK (Questionnaire)

**Location**: `questionnaires/models.py:7-13`
```python
class Questionnaire(TimeStampedModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,  # PROBLEMATIC
        blank=True
    )
```

**Issues**:
1. Default questionnaires have `organization=None`
2. Filters like `organization=org` exclude defaults
3. Code has to special-case defaults:
```python
questionnaires = Questionnaire.objects.filter(
    Q(organization=org) | Q(organization__isnull=True)
)
```
4. If filter is missing the null check, defaults are skipped

---

## 5. CURRENT FILTERING PATTERNS (What Works)

### Correct Patterns Found

**Pattern 1**: Helper function with explicit org filter
```python
# admin_views.py:19-27
def get_cycle_or_404(cycle_id, organization):
    cycles_qs = ReviewCycle.objects.select_related('reviewee', 'questionnaire', 'created_by')
    if organization:
        cycles_qs = cycles_qs.filter(reviewee__organization=organization)
    return get_object_or_404(cycles_qs, id=cycle_id)
```
**Usage**: Correct and reusable pattern

---

**Pattern 2**: Conditional filtering in view
```python
# admin_views.py:113-115
users = UserProfile.objects.filter(
    organization=org
).select_related('user').order_by('-user__date_joined')
```
**Usage**: Direct FK allows simple filter

---

**Pattern 3**: Nullable FK special case
```python
# admin_views.py:250-252
questionnaires_qs = Questionnaire.objects.filter(
    organization=org
) if org else Questionnaire.objects.filter(organization__isnull=False)
```
**Issue**: Still vulnerable if `org` is unexpectedly None

---

## 6. SIGNAL & AUTO-CREATION FLOWS

### UserProfile Post-Save Signal
**File**: `accounts/signals.py:20-43`
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
                email=instance.user.email,
                # ...
            )
```
**Status**: OK - Correctly uses organization from UserProfile instance

---

## 7. COMPLETE FILTERING REQUIREMENTS TABLE

### Per-Model Organization Filtering Needs

| Model | Current Status | Direct FK | Requires Filter | Priority |
|-------|---|---|---|---|
| **UserProfile** | OK | Yes | `organization=org` | HIGH |
| **Reviewee** | VULNERABLE | Yes | `organization=org` | CRITICAL |
| **ReviewCycle** | NEEDS ATTENTION | No (property) | `reviewee__organization=org` | CRITICAL |
| **ReviewerToken** | VULNERABLE | No | `cycle__reviewee__organization=org` | CRITICAL |
| **Response** | VULNERABLE | No | `cycle__reviewee__organization=org` | CRITICAL |
| **Report** | VULNERABLE | No | `cycle__reviewee__organization=org` | CRITICAL |
| **Questionnaire** | VULNERABLE | Yes (nullable) | `organization=org` (+ null handling) | CRITICAL |
| **QuestionSection** | OK | No | `questionnaire__organization=org` | HIGH |
| **Question** | OK | No | `section__questionnaire__organization=org` | HIGH |
| **OrganizationInvitation** | OK | Yes | `organization=org` | HIGH |
| **Subscription** | OK | Yes | `organization=org` | MEDIUM |
| **Plan** | OK (system-wide) | No | None (shared across orgs) | LOW |

---

## 8. SOLUTION: CUSTOM MODEL MANAGERS

### Manager Implementation Strategy

```python
# core/managers.py - Create this new file

class OrganizationFilteredManager(models.Manager):
    """
    Custom manager for models with direct organization FK.
    Enforces organization filtering at the ORM level.
    """
    def get_queryset(self):
        # This won't filter by default - use .for_organization() method instead
        # Never auto-filter default queryset (can hide bugs)
        return super().get_queryset()
    
    def for_organization(self, organization):
        """Filter by organization - use in views"""
        if organization is None:
            return self.none()
        return self.filter(organization=organization)


class ReviewCycleManager(models.Manager):
    """Custom manager for ReviewCycle - filters through reviewee"""
    def get_queryset(self):
        return super().get_queryset().select_related('reviewee')
    
    def for_organization(self, organization):
        """Filter by organization through reviewee relationship"""
        if organization is None:
            return self.none()
        return self.filter(reviewee__organization=organization)


class ReviewerTokenManager(models.Manager):
    """Custom manager for ReviewerToken - filters through cycle→reviewee"""
    def get_queryset(self):
        return super().get_queryset().select_related('cycle', 'cycle__reviewee')
    
    def for_organization(self, organization):
        """Filter by organization through cycle→reviewee"""
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)


class ResponseManager(models.Manager):
    """Custom manager for Response - filters through cycle→reviewee"""
    def get_queryset(self):
        return super().get_queryset().select_related(
            'cycle', 'cycle__reviewee', 'question', 'token'
        )
    
    def for_organization(self, organization):
        """Filter by organization through cycle→reviewee"""
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)


class ReportManager(models.Manager):
    """Custom manager for Report - filters through cycle→reviewee"""
    def get_queryset(self):
        return super().get_queryset().select_related('cycle', 'cycle__reviewee')
    
    def for_organization(self, organization):
        """Filter by organization through cycle→reviewee"""
        if organization is None:
            return self.none()
        return self.filter(cycle__reviewee__organization=organization)
```

### Updated Models

```python
# accounts/models.py
class Reviewee(TimeStampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='reviewees')
    name = models.CharField(max_length=255)
    email = models.EmailField()
    department = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    
    objects = OrganizationFilteredManager()
    
    class Meta:
        db_table = 'reviewees'
        ordering = ['name']
        unique_together = ['organization', 'email']


# reviews/models.py
class ReviewCycle(TimeStampedModel):
    reviewee = models.ForeignKey(Reviewee, on_delete=models.CASCADE, related_name='review_cycles')
    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.PROTECT, related_name='review_cycles')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_review_cycles')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    objects = ReviewCycleManager()
    
    @property
    def organization(self):
        return self.reviewee.organization


class ReviewerToken(TimeStampedModel):
    cycle = models.ForeignKey(ReviewCycle, on_delete=models.CASCADE, related_name='tokens')
    token = models.UUIDField(unique=True, db_index=True, editable=False)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    # ... other fields
    
    objects = ReviewerTokenManager()


class Response(TimeStampedModel):
    cycle = models.ForeignKey(ReviewCycle, on_delete=models.CASCADE, related_name='responses')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='responses')
    token = models.ForeignKey(ReviewerToken, on_delete=models.CASCADE, related_name='responses')
    category = models.CharField(max_length=20)
    answer_data = models.JSONField()
    
    objects = ResponseManager()


# reports/models.py
class Report(TimeStampedModel):
    cycle = models.OneToOneField(ReviewCycle, on_delete=models.CASCADE, related_name='report')
    access_token = models.UUIDField(unique=True, editable=False, db_index=True, null=True, blank=True)
    report_data = models.JSONField()
    generated_at = models.DateTimeField(auto_now_add=True)
    available = models.BooleanField(default=True)
    
    objects = ReportManager()
```

---

## 9. VIEW FIXES REQUIRED

### Critical Fixes for admin_views.py

**Fix 1**: reviewee_edit - Add organization filter
```python
# Line 193 - BEFORE
reviewee = get_object_or_404(Reviewee, id=reviewee_id)

# AFTER
reviewee = get_object_or_404(Reviewee.objects.for_organization(request.organization), id=reviewee_id)
# OR more explicitly:
reviewee = Reviewee.objects.get(id=reviewee_id, organization=request.organization)
```

**Fix 2**: reviewee_delete - Add organization filter
```python
# Line 218 - BEFORE
reviewee = get_object_or_404(Reviewee, id=reviewee_id)

# AFTER
reviewee = get_object_or_404(Reviewee.objects.for_organization(request.organization), id=reviewee_id)
```

**Fix 3**: review_cycle_create (bulk) - Add organization filter
```python
# Line 498 - BEFORE
reviewees = Reviewee.objects.filter(is_active=True)

# AFTER
reviewees = Reviewee.objects.for_organization(request.organization).filter(is_active=True)
```

**Fix 4**: review_cycle_create (form) - Add organization filter
```python
# Line 602 - BEFORE
reviewees = Reviewee.objects.filter(is_active=True).order_by('name')

# AFTER
reviewees = Reviewee.objects.for_organization(request.organization).filter(is_active=True).order_by('name')
```

**Fix 5**: questionnaire_preview - Add organization filter
```python
# Line 269 - BEFORE
questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

# AFTER
questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, organization=request.organization)
```

---

### Critical Fixes for reports/views.py

**Fix 1**: view_report - Add organization filter
```python
# Line 13 - BEFORE
cycle = get_object_or_404(ReviewCycle, id=cycle_id)

# AFTER
cycle = get_object_or_404(ReviewCycle.objects.for_organization(request.organization), id=cycle_id)
```

---

### Fixes for admin_views.py dashboard & stats

**Fix 2**: questionnaire_edit - Verify organization filter
```python
# Line 325-329 - CURRENTLY:
questionnaire = get_object_or_404(
    Questionnaire,
    id=questionnaire_id,
    organization=org
)
# This is CORRECT
```

**Fix 3**: review_cycle_detail - Uses helper (CORRECT)
```python
# Line 624
cycle = get_cycle_or_404(cycle_id, request.organization)
# Pattern is good, replicate elsewhere
```

---

## 10. COMPREHENSIVE IMPLEMENTATION CHECKLIST

### Phase 1: Create Infrastructure
- [ ] Create `/Users/tdz/projects/blik/core/managers.py`
- [ ] Define `OrganizationFilteredManager`
- [ ] Define `ReviewCycleManager`
- [ ] Define `ReviewerTokenManager`
- [ ] Define `ResponseManager`
- [ ] Define `ReportManager`

### Phase 2: Add Denormalized FK to ReviewCycle (Optional but Recommended)
- [ ] Add direct `organization = models.ForeignKey(Organization)` to ReviewCycle
- [ ] This simplifies filtering from `cycle__reviewee__organization` to `cycle__organization`
- [ ] Create data migration to populate field
- [ ] Update manager to use direct FK

### Phase 3: Update Models with Managers
- [ ] Reviewee - add `objects = OrganizationFilteredManager()`
- [ ] ReviewCycle - add `objects = ReviewCycleManager()`
- [ ] ReviewerToken - add `objects = ReviewerTokenManager()`
- [ ] Response - add `objects = ResponseManager()`
- [ ] Report - add `objects = ReportManager()`

### Phase 4: Fix Views - Critical
- [ ] admin_views.py:191 - reviewee_edit()
- [ ] admin_views.py:216 - reviewee_delete()
- [ ] admin_views.py:498 - review_cycle_create() bulk
- [ ] admin_views.py:602 - review_cycle_create() form
- [ ] admin_views.py:269 - questionnaire_preview()
- [ ] reports/views.py:13 - view_report()

### Phase 5: Fix Views - Supporting
- [ ] Check all Questionnaire lookups for org filter
- [ ] Check all subscription/utils.py queries
- [ ] Review all management commands for multi-org safety
- [ ] Review invitation_views.py for org filter

### Phase 6: Add Query Validation Helper
```python
# core/utils.py
def validate_organization_access(obj, user_org):
    """Validate that object belongs to user's organization"""
    if hasattr(obj, 'organization'):
        obj_org = obj.organization
    elif hasattr(obj, 'cycle') and hasattr(obj.cycle, 'reviewee'):
        obj_org = obj.cycle.reviewee.organization
    else:
        raise ValueError(f"Cannot determine organization for {type(obj)}")
    
    if obj_org != user_org:
        raise PermissionDenied(f"Object does not belong to user's organization")
    return obj
```

### Phase 7: Add Tests
- [ ] Test that reviewee_edit rejects cross-org access
- [ ] Test that report view rejects cross-org access
- [ ] Test bulk operations only affect target org
- [ ] Test Reviewee queryset organization filtering
- [ ] Test Response queryset organization filtering

### Phase 8: Audit & Documentation
- [ ] Document manager usage patterns
- [ ] Create security checklist for new views
- [ ] Update developer guide for multitenancy requirements

---

## 11. ATTACK SCENARIOS & MITIGATION

### Scenario 1: Direct ID-based Access Across Organizations
**Attack Vector**: User from Org A guesses Org B's reviewee ID
```
GET /admin/dashboard/reviewees/999/edit/
```
**Current Risk**: CRITICAL (no org filter)
**Mitigation**: Add `organization=request.organization` to queryset

---

### Scenario 2: Bulk Operations Affecting Wrong Organization
**Attack Vector**: Trigger review_cycle_create bulk mode while viewing Org A
```
POST /admin/dashboard/review-cycles/create/
  creation_mode: bulk
```
**Current Risk**: CRITICAL (processes all reviewees)
**Mitigation**: Filter `Reviewee.objects.filter(organization=request.organization)`

---

### Scenario 3: Report Access Cross-Organization
**Attack Vector**: Staff member views another org's report
```
GET /admin/dashboard/cycles/999/report/
```
**Current Risk**: CRITICAL (@staff_member_required ignores org)
**Mitigation**: Check `cycle.organization == request.organization`

---

### Scenario 4: Questionnaire Enumeration
**Attack Vector**: User sees other org's questionnaires in dropdowns
```
GET /admin/dashboard/questionnaires/
```
**Current Risk**: HIGH (info disclosure)
**Mitigation**: Use manager's `for_organization()`

---

### Scenario 5: Feedback Data Leakage via Response Model
**Attack Vector**: Direct query/crawling of Response table
```
GET /api/responses/?cycle_id=999
```
**Current Risk**: CRITICAL (if API endpoint exists)
**Mitigation**: Always filter `Response.objects.for_organization()`

---

## 12. SECONDARY CONCERNS

### Questionnaire Nullable Organization
**Issue**: `organization` field can be NULL for "default" questionnaires
**Current**: Handled in views but fragile
**Recommendation**: 
1. Create system organization for defaults (cleaner)
2. Or consistently handle NULL in managers

```python
class Questionnaire(TimeStampedModel):
    # Option 1: Use system org instead of NULL
    # organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=False)
    
    # Option 2: Keep NULL but always filter carefully
    # For org X: filter(Q(organization=X) | Q(is_default=True))
```

---

### ReviewCycle Organization Property
**Issue**: `organization` is property, not real FK
**Pros**: Stays DRY (no data duplication)
**Cons**: Makes filtering harder, can't use `filter(organization=org)`
**Recommendation**: Add denormalized `organization_id` FK
```python
class ReviewCycle(TimeStampedModel):
    reviewee = models.ForeignKey(Reviewee)
    organization = models.ForeignKey(Organization)  # Denormalized for filtering
    
    def save(self, *args, **kwargs):
        # Auto-set organization from reviewee
        if not self.organization_id:
            self.organization_id = self.reviewee.organization_id
        super().save(*args, **kwargs)
```

---

### UserProfile Organization Assignment
**Issue**: User is OneToOneField to User, could have multiple profiles
**Current**: Only one allowed via OneToOne
**Status**: OK - one profile per user enforced at database level

---

## 13. TESTING STRATEGY

### Unit Tests - Manager Tests
```python
class RevieweeManagerTests(TestCase):
    def test_for_organization_filters_correctly(self):
        org1, org2 = Organization.objects.create(name='Org1'), Organization.objects.create(name='Org2')
        r1 = Reviewee.objects.create(organization=org1, name='Rev1', email='r1@org1.com')
        r2 = Reviewee.objects.create(organization=org2, name='Rev2', email='r2@org2.com')
        
        qs = Reviewee.objects.for_organization(org1)
        assert list(qs) == [r1]
    
    def test_for_organization_none_returns_empty(self):
        qs = Reviewee.objects.for_organization(None)
        assert qs.count() == 0
```

### Integration Tests - View Tests
```python
class RevieweeEditTests(TestCase):
    def test_cannot_edit_other_org_reviewee(self):
        org1, org2 = Organization.objects.create(name='Org1'), Organization.objects.create(name='Org2')
        user1 = User.objects.create_user('user1', password='pw')
        UserProfile.objects.create(user=user1, organization=org1)
        reviewee2 = Reviewee.objects.create(organization=org2, name='Rev2', email='r2@org2.com')
        
        self.client.login(username='user1', password='pw')
        response = self.client.post(f'/admin/reviewees/{reviewee2.id}/edit/', {'name': 'Hacked'})
        
        assert response.status_code == 404  # Not found in org1
```

---

## 14. RELATED FILES NEEDING REVIEW

### Management Commands
- [ ] `/Users/tdz/projects/blik/core/management/commands/generate_demo_data.py` - Bulk creates
- [ ] `/Users/tdz/projects/blik/questionnaires/management/commands/clone_default_questionnaires.py`

### Signals
- [ ] `/Users/tdz/projects/blik/accounts/signals.py` - OK currently
- [ ] `/Users/tdz/projects/blik/questionnaires/signals.py` - Check for org filtering

### Services
- [ ] `/Users/tdz/projects/blik/reports/services.py` - Report generation
- [ ] `/Users/tdz/projects/blik/reviews/services.py` - Review services

---

## 15. SECURITY SUMMARY TABLE

| Area | Current State | Risk Level | Fix Priority | Estimated Effort |
|------|---|---|---|---|
| Reviewee Model | Partial filtering | CRITICAL | P0 | 30 min |
| ReviewCycle Access | Partial filtering | CRITICAL | P0 | 30 min |
| ReviewerToken Access | Token-based (OK) | MEDIUM | P1 | 20 min |
| Response Data | No direct filtering | CRITICAL | P0 | 30 min |
| Report Access | Partial filtering | CRITICAL | P0 | 30 min |
| Questionnaire Access | Partial filtering | CRITICAL | P0 | 30 min |
| Model Managers | None exist | N/A | P0 | 2 hours |
| View Fixes | Ad-hoc | N/A | P0 | 3 hours |
| Data Migration | N/A | N/A | P1 | 1 hour |
| Tests | None | N/A | P1 | 4 hours |
| **Total** | | | | **11 hours** |

---

## CONCLUSION

This application has **critical multitenancy security vulnerabilities** that could allow:
1. Users to access/modify data from other organizations
2. Exposure of sensitive feedback data across org boundaries
3. Staff members viewing reports they're not authorized to see
4. Bulk operations affecting the wrong organizations

**Recommended Action**: Implement custom model managers and fix views immediately before production use or scaling to multiple paying customers. This is a security-critical architectural issue.

The fixes are straightforward and don't require schema changes (except optional denormalization), but require systematic review of all ORM queries.

