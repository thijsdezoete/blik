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

echo "Compiling translations..."
# Non-fatal: a malformed .po file must not prevent the container from starting.
# Before the upgrade steps, which read the translations of the shipped questionnaires.
python manage.py compilemessages || echo "WARNING: compilemessages failed, using existing .mo files"

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Running upgrade steps..."
python manage.py upgrade

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

# Set up cron for the daily email tasks
# Cron starts jobs with an empty environment, so pass the whole container environment, quoted
export -p | sed 's/^declare -x /export /' > /app/.env.cron
chmod 600 /app/.env.cron
crontab - <<'EOF'
0 9 * * * . /app/.env.cron && cd /app && python manage.py send_cycle_reminders >> /var/log/cron.log 2>&1
5 9 * * * . /app/.env.cron && cd /app && python manage.py send_trial_reminders >> /var/log/cron.log 2>&1
10 9 * * * . /app/.env.cron && cd /app && python manage.py send_lifecycle_emails >> /var/log/cron.log 2>&1
EOF
service cron start
echo "Cron started (cycle reminders, trial reminders and lifecycle emails daily from 09:00 UTC)"

exec "$@"
