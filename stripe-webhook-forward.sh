#!/bin/bash
# Stripe webhook forwarding for local development
# This forwards Stripe webhooks to your local Docker container

echo "Starting Stripe webhook forwarding..."
echo ""
echo "This will:"
echo "1. Forward webhooks from Stripe to http://localhost:8000/api/stripe/webhook/"
echo "2. Print the webhook signing secret (add this to your .env file)"
echo ""

# Login if not already logged in
stripe login 2>/dev/null || echo "Already logged in to Stripe"

echo ""
echo "Starting webhook forwarding..."
echo "Press Ctrl+C to stop"
echo ""

# Forward webhooks to local development server
stripe listen --forward-to http://localhost:8000/api/stripe/webhook/
