# Blik Deployment Guide

This guide covers deploying Blik to production environments, with specific instructions for popular self-hosting platforms.

## Quick Start

Blik is designed for easy deployment with minimal configuration. The basic process:

1. Set environment variables
2. Run `docker-compose up -d`
3. Access the admin interface

## Environment Variables

### Required Variables

```bash
# Django Core
SECRET_KEY=your-production-secret-key-here
DEBUG=False
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Database
DATABASE_NAME=blik
DATABASE_USER=blik
DATABASE_PASSWORD=secure-database-password
DATABASE_HOST=db
DATABASE_PORT=5432

# Email (SMTP)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-email-password
DEFAULT_FROM_EMAIL=noreply@your-domain.com

# Organization
ORGANIZATION_NAME=Your Company Name

# Auto-setup (First Run)
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@your-domain.com
DJANGO_SUPERUSER_PASSWORD=your-secure-admin-password

# Security
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

### Generating a Secret Key

Generate a secure secret key for production:

```bash
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

## Platform-Specific Guides

### Dokploy

Dokploy makes deploying Docker applications simple. Here's how to deploy Blik:

1. **Create a New Application**
   - Log into your Dokploy instance
   - Click "Create Application"
   - Select "Docker Compose"
   - Connect your Blik repository

2. **Configure Environment Variables**
   - Navigate to the "Environment" tab
   - Add all required environment variables (see above)
   - Ensure `ALLOWED_HOSTS` includes your domain
   - Set `DEBUG=False` for production
   - Set `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True`

3. **Important Settings**
   ```bash
   # Make sure to set these for production
   SECRET_KEY=<generate-a-new-one>
   DEBUG=False
   ALLOWED_HOSTS=your-domain.com

   # Database (Dokploy can provide PostgreSQL)
   DATABASE_HOST=<your-postgres-host>
   DATABASE_NAME=blik
   DATABASE_USER=blik
   DATABASE_PASSWORD=<secure-password>

   # Auto-setup
   DJANGO_SUPERUSER_USERNAME=admin
   DJANGO_SUPERUSER_EMAIL=admin@your-domain.com
   DJANGO_SUPERUSER_PASSWORD=<secure-password>
   ```

4. **Deploy**
   - Click "Deploy"
   - Dokploy will build and start the containers
   - The entrypoint script will automatically:
     - Run migrations
     - Create the organization
     - Create the superuser
     - Collect static files

5. **Access Your Instance**
   - Navigate to `https://your-domain.com/admin`
   - Log in with your superuser credentials
   - Start creating review cycles!

### Coolify

Coolify is another excellent self-hosting platform:

1. **Create New Resource**
   - Select "Docker Compose"
   - Choose "Git Repository"
   - Connect to your Blik repository

2. **Environment Configuration**
   - Go to "Environment Variables"
   - Add all required variables
   - Use Coolify's secrets manager for sensitive data

3. **Domain Setup**
   - Configure your domain in Coolify
   - Enable automatic HTTPS (Let's Encrypt)
   - Update `ALLOWED_HOSTS` to match your domain

4. **Deploy**
   - Click "Deploy"
   - Monitor logs for successful setup
   - Access admin at `https://your-domain.com/admin`

### Railway

1. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your Blik repository

2. **Add PostgreSQL**
   - Click "New Service"
   - Select "PostgreSQL"
   - Railway will automatically provide connection details

3. **Configure Environment Variables**
   ```bash
   # Railway provides DATABASE_URL, but Blik uses individual vars
   # Use Railway's PostgreSQL variables:
   DATABASE_HOST=${{Postgres.PGHOST}}
   DATABASE_NAME=${{Postgres.PGDATABASE}}
   DATABASE_USER=${{Postgres.PGUSER}}
   DATABASE_PASSWORD=${{Postgres.PGPASSWORD}}
   DATABASE_PORT=${{Postgres.PGPORT}}

   # Add other required variables
   SECRET_KEY=<generate-one>
   DEBUG=False
   ALLOWED_HOSTS=${{RAILWAY_PUBLIC_DOMAIN}}

   # Auto-setup
   DJANGO_SUPERUSER_USERNAME=admin
   DJANGO_SUPERUSER_EMAIL=admin@example.com
   DJANGO_SUPERUSER_PASSWORD=<secure-password>
   ```

4. **Deploy**
   - Railway auto-deploys on git push
   - Monitor deployment in the dashboard
   - Access via provided railway.app domain

### CapRover

1. **Prepare CapRover App**
   ```bash
   # Create a new app in CapRover dashboard
   # Enable HTTPS
   # Configure domain
   ```

2. **Deploy via Git**
   ```bash
   # Install CapRover CLI
   npm install -g caprover

   # Initialize in your Blik directory
   caprover deploy
   ```

3. **Set Environment Variables**
   - Go to your app in CapRover
   - Navigate to "App Configs" → "Environment Variables"
   - Add all required variables
   - Set bulk environment variables if available

4. **PostgreSQL Setup**
   - Use CapRover's One-Click Apps to deploy PostgreSQL
   - Or use an external PostgreSQL instance
   - Configure `DATABASE_*` variables accordingly

### Generic VPS (DigitalOcean, Linode, etc.)

For a VPS with Docker installed:

1. **Clone Repository**
   ```bash
   git clone https://github.com/yourusername/blik.git
   cd blik
   ```

2. **Create .env File**
   ```bash
   cp .env.example .env
   nano .env  # Edit with your production values
   ```

3. **Important .env Changes**
   ```bash
   SECRET_KEY=<generate-new-secret-key>
   DEBUG=False
   ALLOWED_HOSTS=your-domain.com,www.your-domain.com

   # Use strong passwords
   DATABASE_PASSWORD=<secure-database-password>
   DJANGO_SUPERUSER_PASSWORD=<secure-admin-password>

   # Configure real SMTP
   EMAIL_HOST=smtp.your-provider.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=your-email@example.com
   EMAIL_HOST_PASSWORD=<email-password>

   # Security
   SESSION_COOKIE_SECURE=True
   CSRF_COOKIE_SECURE=True
   ```

4. **Deploy**
   ```bash
   docker-compose up -d
   ```

5. **Setup Reverse Proxy (Nginx)**
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://localhost:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

6. **Setup SSL with Let's Encrypt**
   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   ```

## Post-Deployment

### Verify Installation

1. **Check Logs**
   ```bash
   docker-compose logs -f web
   ```

   Look for:
   ```
   ========================================
   Blik is ready!
   ========================================
   Admin username: admin
   ========================================
   ```

2. **Access Admin Interface**
   - Navigate to `https://your-domain.com/admin`
   - Log in with your superuser credentials

3. **Verify Organization**
   - In Django admin, check "Organizations"
   - Should see your organization created

### Load Default Questionnaire

Blik ships with a default 360-degree feedback questionnaire:

```bash
# If using Docker
docker-compose exec web python manage.py loaddata default_questionnaire

# Or from within the container
python manage.py loaddata default_questionnaire
```

### Creating Your First Review Cycle

1. Log into Django admin
2. Navigate to "Reviewees" → "Add reviewee"
3. Create a reviewee (person being reviewed)
4. Navigate to "Review Cycles" → "Add review cycle"
5. Select the reviewee and default questionnaire
6. Click "Save"
7. In the review cycle detail page, you'll see reviewer tokens
8. Generate tokens for different categories (self, peer, manager, direct report)
9. Send invitation emails to reviewers

## Email Configuration

### Gmail

```bash
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-specific-password
```

**Note**: Use an [App Password](https://support.google.com/accounts/answer/185833), not your regular password.

### SendGrid

```bash
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=your-sendgrid-api-key
```

### Mailgun

```bash
EMAIL_HOST=smtp.mailgun.org
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-mailgun-username
EMAIL_HOST_PASSWORD=your-mailgun-password
```

## Backups

### Database Backup

```bash
# Backup
docker-compose exec db pg_dump -U blik blik > backup.sql

# Restore
docker-compose exec -T db psql -U blik blik < backup.sql
```

### Automated Backups

Create a cron job:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * cd /path/to/blik && docker-compose exec -T db pg_dump -U blik blik > backups/backup-$(date +\%Y\%m\%d).sql
```

## Monitoring

### Health Check Endpoint

Coming in a future release. For now, monitor:

```bash
# Check if web service is running
curl https://your-domain.com/admin/login/

# Check logs
docker-compose logs -f web
```

### Resource Usage

```bash
# Check Docker resource usage
docker stats

# Check specific container
docker stats blik_web_1
```

## Troubleshooting

### Issue: "Bad Request (400)"

**Cause**: `ALLOWED_HOSTS` not configured properly

**Solution**: Add your domain to `ALLOWED_HOSTS`:
```bash
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
```

### Issue: "CSRF verification failed"

**Cause**: Security settings misconfigured

**Solution**: Ensure HTTPS is enabled and:
```bash
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

### Issue: "No superuser created"

**Cause**: `DJANGO_SUPERUSER_PASSWORD` not set

**Solution**:
```bash
# Set the environment variable
DJANGO_SUPERUSER_PASSWORD=your-password

# Or create manually
docker-compose exec web python manage.py createsuperuser
```

### Issue: Email not sending

**Cause**: SMTP configuration incorrect

**Solution**: Test email settings:
```bash
docker-compose exec web python manage.py shell
>>> from django.core.mail import send_mail
>>> send_mail('Test', 'Test message', 'from@example.com', ['to@example.com'])
```

### Issue: Static files not loading

**Cause**: Static files not collected

**Solution**:
```bash
docker-compose exec web python manage.py collectstatic --noinput
```

## Security Checklist

- [ ] `DEBUG=False` in production
- [ ] Strong, unique `SECRET_KEY` generated
- [ ] Strong database password set
- [ ] Strong admin password set
- [ ] `ALLOWED_HOSTS` properly configured
- [ ] `SESSION_COOKIE_SECURE=True`
- [ ] `CSRF_COOKIE_SECURE=True`
- [ ] HTTPS enabled (SSL certificate)
- [ ] Database backups automated
- [ ] Email credentials secured (use app-specific passwords)
- [ ] Firewall configured (only expose port 80/443)
- [ ] Regular security updates applied

## Updating Blik

```bash
# Pull latest changes
git pull origin master

# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d

# Run migrations (if any)
docker-compose exec web python manage.py migrate
```

## Support

- Documentation: https://github.com/yourusername/blik
- Issues: https://github.com/yourusername/blik/issues
- Discussions: https://github.com/yourusername/blik/discussions

## License

Blik is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
