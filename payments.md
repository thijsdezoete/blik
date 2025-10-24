# Stripe Payments Integration

## Status: Foundation Complete (80%)

### Completed
- Subscriptions app with Plan and Subscription models
- Stripe webhook handler (auto-provision on payment)
- Organization FK added to Questionnaire
- ReviewCycle gets org via reviewee relationship
- Stripe settings in settings.py
- stripe>=7.0.0 dependency added

### Required Environment Variables

```bash
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_SAAS=price_...
STRIPE_PRICE_ID_ENTERPRISE=price_...
```

### Stripe Setup Steps

1. Create Stripe account at stripe.com
2. Create two products:
   - "Blik SaaS" - €49/month, up to 50 employees
   - "Blik Enterprise" - €199/month, up to 200 employees
3. Get API keys from Stripe Dashboard > Developers > API keys
4. Set webhook endpoint: `https://blik360.com/api/stripe/webhook`
5. Subscribe to events: checkout.session.completed, customer.subscription.updated, customer.subscription.deleted, invoice.payment_failed
6. Copy webhook signing secret
7. Add all keys to Dokploy environment variables

### Payment Flow

1. Customer clicks "Start Free Trial" on landing page
2. Redirects to Stripe Checkout with plan metadata
3. Customer enters payment details
4. On successful payment:
   - Stripe sends webhook to /api/stripe/webhook
   - System creates Organization
   - System creates admin User (staff=True)
   - System creates Subscription record
   - Logs credentials (TODO: send welcome email)
5. Customer receives login credentials via email

### Multi-Tenant Architecture

**Type:** Shared database with organization filtering

**How it works:**
- Organization model exists (core/models.py:13)
- Reviewee has organization FK (accounts/models.py:7)
- Questionnaire has organization FK (questionnaires/models.py:7, nullable for defaults)
- ReviewCycle inherits org through reviewee (reviews/models.py:36)
- User authentication determines organization context
- All queries filtered by request.organization (via middleware)

### Database Schema

```
Plan
├── plan_type (saas/enterprise)
├── price_monthly
├── max_employees
└── stripe_price_id

Subscription
├── organization FK (OneToOne)
├── plan FK
├── stripe_customer_id
├── stripe_subscription_id
├── status (active/trialing/past_due/canceled)
├── current_period_start/end
└── trial_start/end

Organization (existing)
├── Already has: name, email, smtp settings
└── New relationships: subscription, questionnaires

Questionnaire (modified)
└── Added: organization FK (nullable)

ReviewCycle (unchanged)
└── Gets org via: reviewee.organization
```

### Remaining Work

1. Create and run migrations
2. Add webhook URL route to urls.py
3. Update landing page with Stripe Checkout buttons
4. Create organization filtering middleware
5. Update admin_views to filter by organization
6. Create Plan fixtures (€49, €199)
7. Send welcome email on signup
8. Add subscription status checks (enforce limits)

### Testing

After setup, test with Stripe test mode:
1. Use test keys (pk_test_..., sk_test_...)
2. Test card: 4242 4242 4242 4242
3. Any future date, any CVC
4. Verify webhook receives events
5. Check Organization + User created
6. Test login with generated credentials

### Production Deployment

1. Switch to live Stripe keys in Dokploy
2. Update webhook URL to production domain
3. Test one real subscription
4. Monitor Stripe Dashboard for events
5. Check logs for credential generation
