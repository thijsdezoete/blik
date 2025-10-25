# Stripe Webhook Setup

## Local Development

For local development, you need to forward Stripe webhooks from Stripe to your local machine.

### Quick Start

1. **Run the webhook forwarding script:**
   ```bash
   ./stripe-webhook-forward.sh
   ```

2. **First time setup:**
   - The script will prompt you to login to Stripe (opens browser)
   - After login, it will display a webhook signing secret like `whsec_xxxxx`
   - Copy this secret and add it to your `.env` file:
     ```
     STRIPE_WEBHOOK_SECRET=whsec_xxxxx
     ```

3. **Restart your Docker container:**
   ```bash
   docker compose restart web
   ```

4. **Test the flow:**
   - Visit http://localhost:8000/landing/signup/
   - Complete a test checkout
   - Webhooks will be forwarded to your local server
   - Check logs: `docker compose logs -f web`

### Manual Setup (Alternative)

If you prefer to run the Stripe CLI manually:

```bash
# Login to Stripe
stripe login

# Forward webhooks to your local server
stripe listen --forward-to http://localhost:8000/api/stripe/webhook/

# In a separate terminal, trigger test events
stripe trigger checkout.session.completed
```

### What Gets Created

When a customer completes checkout, the webhook handler:
1. Creates an Organization with the customer's name and email
2. Creates an admin User with a random password
3. Creates a UserProfile linking the user to the organization
4. Creates a Subscription record with Stripe IDs and trial dates
5. Sends a welcome email with login credentials

## Production Setup

### Stripe Dashboard Configuration

1. **Go to Stripe Dashboard:**
   - Navigate to Developers → Webhooks
   - Click "Add endpoint"

2. **Configure the endpoint:**
   - URL: `https://yourdomain.com/api/stripe/webhook/`
   - Events to listen for:
     - `checkout.session.completed`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
     - `invoice.payment_failed`

3. **Get the signing secret:**
   - After creating the endpoint, click "Reveal" under "Signing secret"
   - Copy the secret (starts with `whsec_`)
   - Add it to your production environment variables

4. **Update your `.env.production` file:**
   ```
   STRIPE_WEBHOOK_SECRET=whsec_your_production_secret_here
   ```

## Troubleshooting

### Webhook not firing locally
- Make sure `./stripe-webhook-forward.sh` is running
- Check that Docker container is accessible at http://localhost:8000
- Verify logs: `docker compose logs -f web`

### Invalid signature error
- Ensure `STRIPE_WEBHOOK_SECRET` in `.env` matches the one from Stripe CLI
- Restart container after updating `.env`

### Organization/user not created
- Check webhook handler logs: `docker compose logs web | grep "checkout.session.completed"`
- Verify Plans exist in database: `docker compose exec web python manage.py shell -c "from subscriptions.models import Plan; print(Plan.objects.all())"`
- Check for email sending errors in logs

### Email not received
- For local dev, check Mailpit at http://localhost:8025
- Verify SMTP settings in Organization admin panel
- Check logs for email sending errors

## Testing Webhooks

### Trigger test events with Stripe CLI:

```bash
# Test successful checkout
stripe trigger checkout.session.completed

# Test subscription update
stripe trigger customer.subscription.updated

# Test subscription cancellation
stripe trigger customer.subscription.deleted

# Test payment failure
stripe trigger invoice.payment_failed
```

### View webhook delivery logs:

```bash
# In Stripe Dashboard
Developers → Webhooks → [Your endpoint] → View logs

# Local logs
docker compose logs -f web
```
