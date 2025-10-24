#!/bin/sh
set -e

echo "Configuring nginx with environment variables..."
echo "PORT: ${PORT:-8000}"
echo "LANDING_PORT: ${LANDING_PORT:-8001}"

# Substitute environment variables in nginx config template
envsubst '${PORT} ${LANDING_PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

echo "Nginx configuration ready"
echo ""

# Start nginx
exec nginx -g 'daemon off;'
