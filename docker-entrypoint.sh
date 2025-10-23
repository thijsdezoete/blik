#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
until pg_isready -h "$DATABASE_HOST" -p "$DATABASE_PORT" -U "$DATABASE_USER"; do
  echo "PostgreSQL is unavailable - sleeping"
  sleep 1
done
echo "PostgreSQL is up and running"

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Setting up organization..."
python manage.py setup_organization

echo "Setting up superuser..."
python manage.py setup_superuser

echo ""
echo "========================================="
echo "Blik is ready!"
echo "========================================="
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  echo "Admin username: $DJANGO_SUPERUSER_USERNAME"
  if [ -z "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "WARNING: No superuser password set!"
    echo "Please create a superuser manually:"
    echo "  docker-compose exec web python manage.py createsuperuser"
  fi
else
  echo "No auto-setup configured."
  echo "Create a superuser with:"
  echo "  docker-compose exec web python manage.py createsuperuser"
fi
echo "========================================="
echo ""

exec "$@"
