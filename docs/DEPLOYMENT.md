# Deployment Guide

This guide covers deploying Blik to production using various platforms.

## Quick Start: Dokploy Deployment

[Dokploy](https://dokploy.com/) is a self-hosted PaaS that makes deployment simple. Here's how to deploy Blik:

### Prerequisites

- A Dokploy instance running on your server
- A domain name pointing to your server
- SSL certificate (Let's Encrypt is automatically handled by Dokploy)

### Step 1: Create a New Application

1. Log into your Dokploy dashboard
2. Click **"Create Application"**
3. Choose **"Docker Compose"** as the deployment method
4. Connect your Git repository or upload the code

### Step 2: Configure Environment Variables

In Dokploy's environment variables section, set the following (use `.env.production` as a template):

#### Required Security Settings
```env
# SECRET_KEY is auto-generated if not set (recommended to set for production persistence)
SECRET_KEY=<your-secret-key-here>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

**Note on SECRET_KEY:**
- If not set, a secure random key is **auto-generated on first startup**
- For production, it's recommended to set a persistent value so sessions remain valid across restarts
- The auto-generated key will be displayed in the logs on first startup

**Generate SECRET_KEY manually (optional):**
```bash
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

#### Database Settings
```env
DATABASE_NAME=blik
DATABASE_USER=blik
DATABASE_PASSWORD=<generate-secure-password>
DATABASE_HOST=db
DATABASE_PORT=5432
```

#### Email Configuration (Example: Gmail)
```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
```

#### Organization Settings
```env
ORGANIZATION_NAME=Your Company Name
```

### Step 3: Deploy

1. Click **"Deploy"** in Dokploy
2. Wait for the build and deployment to complete
3. Dokploy will automatically:
   - Build the Docker images
   - Run database migrations
   - Collect static files
   - Start the application

### Step 4: Initial Setup

**Option A: Use the Setup Wizard (Recommended)**

1. Visit `https://yourdomain.com/setup/`
2. Follow the interactive setup wizard to:
   - Create your admin account
   - Configure organization details
   - Set up email (optional, can be configured later)
3. Generate test data if desired

**Option B: Auto-Setup (Advanced)**

Add these to environment variables before first deployment:
```env
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@yourdomain.com
DJANGO_SUPERUSER_PASSWORD=<secure-password>
```

### Step 5: Configure SSL/HTTPS

Dokploy handles SSL automatically:

1. In your application settings, enable **"SSL/TLS"**
2. Choose **"Let's Encrypt"** for automatic certificate
3. Add your domain name
4. Dokploy will obtain and auto-renew the certificate

---

## Manual Docker Compose Deployment

For deploying without Dokploy on any server with Docker:

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/blik.git
cd blik
```

### 2. Configure Environment

```bash
cp .env.production .env
# Edit .env with your production settings
nano .env
```

**Critical settings to change:**
- `SECRET_KEY` - Generate a new one
- `DEBUG=False`
- `ALLOWED_HOSTS` - Your domain(s)
- `DATABASE_PASSWORD` - Secure password
- `EMAIL_*` - Your SMTP settings
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`

### 3. Deploy

```bash
docker compose up -d
```

The entrypoint script will automatically:
- Wait for PostgreSQL
- Run migrations
- Collect static files
- Load default questionnaires

### 4. Set Up Reverse Proxy (Nginx/Caddy)

**Example Nginx Configuration:**

```nginx
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /path/to/blik/staticfiles/;
    }
}
```

**Example Caddy Configuration (Simpler):**

```
yourdomain.com {
    reverse_proxy localhost:8000
}
```

### 5. Initial Setup

Visit `https://yourdomain.com/setup/` to complete the setup wizard.

---

## Other Deployment Platforms

### Heroku

1. Add `heroku.yml` or use buildpacks
2. Set environment variables via Heroku dashboard
3. Add PostgreSQL addon: `heroku addons:create heroku-postgresql:mini`
4. Deploy: `git push heroku main`

### Railway

1. Connect your GitHub repository
2. Railway auto-detects Dockerfile
3. Set environment variables in Railway dashboard
4. Add PostgreSQL service from Railway marketplace
5. Deploy automatically on push

### DigitalOcean App Platform

1. Connect repository
2. Choose "Docker Hub" or "Dockerfile"
3. Add PostgreSQL database component
4. Set environment variables
5. Deploy

### AWS/GCP/Azure

Use the Docker Compose configuration with your platform's container orchestration:
- **AWS:** ECS with RDS PostgreSQL
- **GCP:** Cloud Run with Cloud SQL
- **Azure:** Container Instances with Azure Database for PostgreSQL

---

## Post-Deployment Checklist

- [ ] SSL/HTTPS is configured and working
- [ ] `DEBUG=False` in production
- [ ] Strong `SECRET_KEY` is set
- [ ] Database password is secure
- [ ] `ALLOWED_HOSTS` includes your domain(s)
- [ ] Email is configured and tested
- [ ] Admin account created
- [ ] Default questionnaires loaded
- [ ] Static files are being served correctly
- [ ] Security cookies enabled (`SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`)
- [ ] Database backups configured
- [ ] Monitoring/logging set up (optional)

---

## Email Provider Setup

### Gmail (For Testing/Small Scale)

1. Enable 2-factor authentication on your Google account
2. Generate an **App Password**: https://myaccount.google.com/apppasswords
3. Use the app password in `EMAIL_HOST_PASSWORD`

```env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=youremail@gmail.com
EMAIL_HOST_PASSWORD=your-16-char-app-password
```

**Note:** Gmail has sending limits (500 emails/day). For production, use a transactional email service.

### SendGrid (Recommended for Production)

1. Sign up at https://sendgrid.com
2. Create an API key
3. Configure:

```env
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=your-sendgrid-api-key
```

### AWS SES

```env
EMAIL_HOST=email-smtp.us-east-1.amazonaws.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-ses-smtp-username
EMAIL_HOST_PASSWORD=your-ses-smtp-password
```

### Mailgun

```env
EMAIL_HOST=smtp.mailgun.org
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=postmaster@yourdomain.mailgun.org
EMAIL_HOST_PASSWORD=your-mailgun-password
```

---

## Maintenance

### Database Backups

**Manual Backup:**
```bash
docker compose exec db pg_dump -U blik blik > backup_$(date +%Y%m%d).sql
```

**Restore from Backup:**
```bash
docker compose exec -T db psql -U blik blik < backup_20241024.sql
```

**Automated Backups:**
Set up a cron job:
```bash
0 2 * * * cd /path/to/blik && docker compose exec -T db pg_dump -U blik blik | gzip > /backups/blik_$(date +\%Y\%m\%d).sql.gz
```

### Updating the Application

```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker compose down
docker compose up -d --build

# Migrations run automatically via entrypoint
```

### View Logs

```bash
# All logs
docker compose logs -f

# Just the web app
docker compose logs -f web

# Just the database
docker compose logs -f db
```

### Scale Workers (if needed)

```bash
docker compose up -d --scale web=3
```

---

## Troubleshooting

### Static Files Not Loading

1. Check if collectstatic ran: `docker compose logs web | grep "static"`
2. Verify volume mount: `docker compose exec web ls -la /app/staticfiles`
3. Ensure your reverse proxy serves `/static/` correctly

### Database Connection Issues

1. Check database is running: `docker compose ps db`
2. Verify credentials in `.env` match `docker-compose.yml`
3. Test connection: `docker compose exec web python manage.py dbshell`

### Email Not Sending

1. Test SMTP settings: `docker compose exec web python manage.py shell`
   ```python
   from django.core.mail import send_mail
   send_mail('Test', 'Body', 'from@example.com', ['to@example.com'])
   ```
2. Check logs: `docker compose logs web | grep -i email`
3. Verify firewall allows outbound SMTP (port 587/465)

### Permission Errors

```bash
# Fix static files permissions
docker compose exec web chown -R www-data:www-data /app/staticfiles

# Fix media files permissions
docker compose exec web chown -R www-data:www-data /app/mediafiles
```

---

## Security Best Practices

1. **Never commit `.env` files to version control**
   - `.env` is in `.gitignore` by default
   - Use `.env.production` as a template only

2. **Keep dependencies updated**
   ```bash
   uv pip list --outdated
   uv pip install --upgrade <package>
   ```

3. **Regular security audits**
   ```bash
   uv pip install safety
   safety check
   ```

4. **Use strong passwords**
   - Database password: 32+ characters
   - Admin password: 16+ characters
   - SECRET_KEY: Django's generated key (50+ characters)

5. **Enable fail2ban or similar**
   - Protect against brute force login attempts

6. **Regular backups**
   - Database: Daily automated backups
   - Retention: Keep 7-30 days of backups
   - Test restore process quarterly

7. **Monitor logs**
   - Set up centralized logging (e.g., Sentry, LogDNA)
   - Alert on errors and security events

---

## Support

- **Documentation:** `/docs/` directory
- **Issues:** GitHub Issues
- **Setup Wizard:** Available at `/setup/` on first run
