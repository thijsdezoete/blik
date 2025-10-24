#!/bin/bash
set -e

echo "Collecting static files for landing container..."
python manage.py collectstatic --noinput --clear --settings=landing_settings

echo ""
echo "========================================="
echo "Landing container is ready!"
echo "========================================="
echo "Serving marketing/landing pages only"
echo "Port: ${LANDING_PORT:-8001}"
echo "========================================="
echo ""

exec "$@"
