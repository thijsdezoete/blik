#!/bin/bash
set -e

echo "Collecting static files for landing container..."
python manage.py collectstatic --noinput --clear --settings=landing_settings

# Render the sample report PDF with the current code, against a throwaway database.
# At start, not at build: the compose file mounts the checkout over /app, which would hide a built file.
echo "Rendering the sample report PDF..."
DATABASE_URL=sqlite:////tmp/sample.sqlite3 DEBUG=False ALLOWED_HOSTS=* \
    SESSION_COOKIE_SECURE=False CSRF_COOKIE_SECURE=False \
    sh -c 'python manage.py migrate -v0 && python manage.py upgrade > /dev/null \
        && python manage.py export_sample_pdf landing/sample-report.pdf' \
    || echo "WARNING: the sample report PDF was not rendered; /sample-report.pdf will be 404"
rm -f /tmp/sample.sqlite3

echo ""
echo "========================================="
echo "Landing container is ready!"
echo "========================================="
echo "Serving marketing/landing pages only"
echo "Port: ${LANDING_PORT:-8001}"
echo "========================================="
echo ""

exec "$@"
