#!/bin/bash
# Stripe webhook forwarding for local development
# This forwards Stripe webhooks to your local Docker container

echo "Starting Stripe webhook forwarding..."
echo ""
echo "This will:"
echo "1. Forward webhooks from Stripe to http://localhost:8000/api/stripe/webhook/"
echo "2. Automatically update STRIPE_WEBHOOK_SECRET in .env"
echo "3. Restart the web container to apply the new secret"
echo ""

# Login if not already logged in
stripe login 2>/dev/null || echo "Already logged in to Stripe"

echo ""
echo "Getting webhook signing secret..."

# Start stripe listen in background, capture output, extract secret, then bring to foreground
stripe listen --forward-to http://localhost:8000/api/stripe/webhook/ --print-secret > /tmp/stripe_secret.txt 2>&1 &
STRIPE_PID=$!

# Wait for secret to appear (max 10 seconds)
for i in {1..10}; do
    if grep -q "whsec_" /tmp/stripe_secret.txt 2>/dev/null; then
        break
    fi
    sleep 1
done

# Extract the webhook secret
WEBHOOK_SECRET=$(grep -o "whsec_[a-zA-Z0-9]*" /tmp/stripe_secret.txt | head -1)

if [ -n "$WEBHOOK_SECRET" ]; then
    echo "✓ Webhook secret obtained: ${WEBHOOK_SECRET:0:20}..."

    # Update .env file
    if [ -f .env ]; then
        if grep -q "STRIPE_WEBHOOK_SECRET=" .env; then
            # Replace existing secret
            if [[ "$OSTYPE" == "darwin"* ]]; then
                # macOS
                sed -i '' "s/STRIPE_WEBHOOK_SECRET=.*/STRIPE_WEBHOOK_SECRET=$WEBHOOK_SECRET/" .env
            else
                # Linux
                sed -i "s/STRIPE_WEBHOOK_SECRET=.*/STRIPE_WEBHOOK_SECRET=$WEBHOOK_SECRET/" .env
            fi
            echo "✓ Updated STRIPE_WEBHOOK_SECRET in .env"
        else
            # Add new secret
            echo "STRIPE_WEBHOOK_SECRET=$WEBHOOK_SECRET" >> .env
            echo "✓ Added STRIPE_WEBHOOK_SECRET to .env"
        fi

        # Restart web container
        echo ""
        echo "Restarting web container..."
        docker compose restart web
        echo "✓ Web container restarted"
    else
        echo "⚠ Warning: .env file not found, please create it and add:"
        echo "STRIPE_WEBHOOK_SECRET=$WEBHOOK_SECRET"
    fi
else
    echo "⚠ Warning: Could not extract webhook secret automatically"
    echo "Please copy it from the output below and add to .env manually"
fi

echo ""
echo "✓ Webhook forwarding active"
echo "Press Ctrl+C to stop"
echo ""

# Kill the background process and start a new one in foreground
kill $STRIPE_PID 2>/dev/null
wait $STRIPE_PID 2>/dev/null

# Clean up temp file
rm -f /tmp/stripe_secret.txt

# Now run stripe listen in foreground
exec stripe listen --forward-to http://localhost:8000/api/stripe/webhook/
