#!/bin/sh
set -e

echo "Configuring nginx with environment variables..."
echo "NGINX_PORT: ${NGINX_PORT:-80}"
echo "PORT: ${PORT:-8000}"
echo "LANDING_PORT: ${LANDING_PORT:-8001}"

# Substitute environment variables in nginx config template
envsubst '${NGINX_PORT} ${PORT} ${LANDING_PORT}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

echo "Nginx configuration ready"
echo ""

# Start nginx
exec nginx -g 'daemon off;'
