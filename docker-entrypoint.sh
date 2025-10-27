#!/bin/bash
set -e

# Generate a secure SECRET_KEY if not set
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "your-secret-key-here-change-in-production" ] || [ "$SECRET_KEY" = "django-insecure-)32-g7%2_@jy@ycdh1lh2*)2pg8y$ftwd88j*vuc%ev%%t(@-f" ]; then
  echo "Generating secure SECRET_KEY..."
  export SECRET_KEY=$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
  echo "✓ SECRET_KEY generated"
  echo ""
  echo "IMPORTANT: For production deployments, save this SECRET_KEY to your environment:"
  echo "SECRET_KEY=$SECRET_KEY"
  echo ""
fi

# Check if we're using PostgreSQL and wait for it to be ready
DATABASE_TYPE="${DATABASE_TYPE:-sqlite}"

if [ "$DATABASE_TYPE" = "postgres" ] || [ "$DATABASE_TYPE" = "postgresql" ]; then
  echo "Waiting for PostgreSQL to be ready..."

  # Extract host and port from DATABASE_URL if set
  if [ -n "$DATABASE_URL" ]; then
    DB_HOST=$(echo "$DATABASE_URL" | sed -n 's/.*@\(.*\):.*/\1/p')
    DB_PORT=$(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
    DB_USER=$(echo "$DATABASE_URL" | sed -n 's/.*:\/\/\(.*\):.*/\1/p')
  else
    DB_HOST="${DATABASE_HOST:-db}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-blik}"
  fi

  # Check if pg_isready is available
  if command -v pg_isready > /dev/null 2>&1; then
    until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER"; do
      echo "PostgreSQL is unavailable - sleeping"
      sleep 1
    done
    echo "PostgreSQL is up and running"
  else
    echo "Warning: pg_isready not found. Proceeding without PostgreSQL health check."
  fi
else
  echo "Using SQLite database - no connection wait needed"
fi

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
