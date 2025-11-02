# DigitalOcean Deployment Guide

This guide covers deploying Blik to DigitalOcean using two approaches:

1. **App Platform** - Managed PaaS (recommended for quick deployment)
2. **Droplet** - VPS with Docker Compose (recommended for cost optimization and full control)

## Table of Contents

- [Prerequisites](#prerequisites)
- [Option 1: App Platform Deployment](#option-1-app-platform-deployment)
  - [One-Click Deploy](#one-click-deploy)
  - [Manual Setup](#manual-setup)
  - [Configuration](#app-platform-configuration)
- [Option 2: Droplet Deployment](#option-2-droplet-deployment)
  - [Initial Setup](#initial-droplet-setup)
  - [Deployment](#droplet-deployment)
  - [SSL Configuration](#ssl-configuration)
- [Post-Deployment](#post-deployment)
- [Troubleshooting](#troubleshooting)
- [Cost Comparison](#cost-comparison)

---

## Prerequisites

### For Both Options:
- DigitalOcean account ([sign up here](https://www.digitalocean.com))
- GitHub repository with your Blik code
- Domain name (optional but recommended)
- Email service credentials (Gmail, SendGrid, Amazon SES, etc.)

### Generate Required Secrets:

```bash
# SECRET_KEY
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# ENCRYPTION_KEY
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

---

## Option 1: App Platform Deployment

### One-Click Deploy

The fastest way to deploy Blik to DigitalOcean:

1. **Click the Deploy Button** in the README
2. **Authorize GitHub** - Grant DigitalOcean access to your repository
3. **Configure Environment Variables** - See [App Platform Configuration](#app-platform-configuration)
4. **Review and Deploy** - Click "Create Resources"

### Manual Setup

If you prefer manual setup or need more control:

#### 1. Create App via Dashboard

1. Log in to [DigitalOcean](https://cloud.digitalocean.com)
2. Navigate to **Apps** in the left sidebar
3. Click **Create App**
4. Choose **GitHub** as source
5. Authorize and select your repository
6. Select the `master` branch
7. Click **Next**

#### 2. Configure Build Settings

- **Source Directory**: `/` (root)
- **Dockerfile Path**: `Dockerfile`
- **Build Command**: (leave default)
- **Run Command**: (leave default - uses Dockerfile CMD)

#### 3. Add Database Component

1. Click **Add Database**
2. Select **PostgreSQL**
3. Choose **Version 15**
4. Select **Basic** plan ($15/month)
5. Name it `db`

#### 4. Configure Resources

- **Name**: `web`
- **Instance Type**: Basic
- **Instance Size**: Basic XXS ($5/month) for testing, Basic XS ($12/month) for production
- **HTTP Port**: 8000

#### 5. Set Environment Variables

See [App Platform Configuration](#app-platform-configuration) section below.

#### 6. Deploy

1. Review your configuration
2. Click **Create Resources**
3. Wait 5-10 minutes for deployment
4. Your app will be available at `https://your-app-name.ondigitalocean.app`

### App Platform Configuration

#### Required Environment Variables

Set these in the **Environment Variables** section:

| Variable | Type | Value | Notes |
|----------|------|-------|-------|
| `DEBUG` | Plain | `False` | Never use True in production |
| `ALLOWED_HOSTS` | Plain | `${APP_DOMAIN}` | Auto-provided by DO |
| `CSRF_TRUSTED_ORIGINS` | Plain | `https://${APP_DOMAIN}` | Use your domain if custom |
| `DATABASE_URL` | Plain | `${db.DATABASE_URL}` | Auto-provided when DB attached |
| `DATABASE_TYPE` | Plain | `postgres` | |
| `SECRET_KEY` | Secret | `<generated>` | Generate using command above |
| `ENCRYPTION_KEY` | Secret | `<generated>` | Generate using command above |
| `SESSION_COOKIE_SECURE` | Plain | `True` | |
| `CSRF_COOKIE_SECURE` | Plain | `True` | |
| `SECURE_SSL_REDIRECT` | Plain | `True` | |
| `ORGANIZATION_NAME` | Plain | `Your Org Name` | Optional - can set via /setup/ |

#### Email Configuration (Required)

| Variable | Type | Value |
|----------|------|-------|
| `EMAIL_BACKEND` | Plain | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | Secret | Your SMTP host (e.g., `smtp.gmail.com`) |
| `EMAIL_PORT` | Plain | `587` |
| `EMAIL_USE_TLS` | Plain | `True` |
| `EMAIL_HOST_USER` | Secret | Your email address |
| `EMAIL_HOST_PASSWORD` | Secret | Your email password/app password |
| `DEFAULT_FROM_EMAIL` | Plain | `noreply@yourdomain.com` |

#### Stripe Configuration (Optional)

Only if using subscription features:

| Variable | Type | Value |
|----------|------|-------|
| `STRIPE_PUBLISHABLE_KEY` | Secret | `pk_live_...` |
| `STRIPE_SECRET_KEY` | Secret | `sk_live_...` |
| `STRIPE_WEBHOOK_SECRET` | Secret | `whsec_...` |
| `STRIPE_PRICE_ID_SAAS` | Plain | `price_...` |
| `STRIPE_PRICE_ID_ENTERPRISE` | Plain | `price_...` |

### Custom Domain (App Platform)

1. Go to **Settings** → **Domains**
2. Click **Add Domain**
3. Enter your domain (e.g., `feedback.yourdomain.com`)
4. Add the CNAME record to your DNS provider:
   ```
   Type: CNAME
   Name: feedback (or @)
   Value: <provided-by-digitalocean>.ondigitalocean.app
   ```
5. Wait for DNS propagation (5-30 minutes)
6. SSL certificate is automatically provisioned

### Monitoring (App Platform)

- **Logs**: Apps → Your App → Runtime Logs
- **Metrics**: Apps → Your App → Insights
- **Alerts**: Apps → Your App → Settings → Alerts

---

## Option 2: Droplet Deployment

For more control and cost optimization.

### Initial Droplet Setup

#### 1. Create Droplet

1. Log in to [DigitalOcean](https://cloud.digitalocean.com)
2. Click **Create** → **Droplets**
3. Choose an image: **Ubuntu 24.04 LTS**
4. Choose a plan: **Basic** → $6/month (1GB RAM)
5. Choose a datacenter region (closest to your users)
6. Authentication: **SSH keys** (recommended) or Password
7. Hostname: `blik-production`
8. Click **Create Droplet**

#### 2. Initial Server Configuration

SSH into your droplet:

```bash
ssh root@your-droplet-ip
```

Clone your repository:

```bash
cd /opt
git clone https://github.com/yourusername/blik.git
cd blik
```

Run the setup script:

```bash
sudo .do/droplet/deploy.sh setup
```

This will:
- Update system packages
- Install Docker and Docker Compose
- Configure UFW firewall (ports 22, 80, 443)
- Create project directory structure

#### 3. Configure Environment

Copy and edit the environment file:

```bash
cp .env.digitalocean.template .env.production
nano .env.production
```

Fill in all required values (see `.env.digitalocean.template` for details).

Secure the environment file:

```bash
chmod 600 .env.production
```

### Droplet Deployment

#### Deploy the Application

```bash
sudo .do/droplet/deploy.sh deploy
```

This will:
- Pull latest code (if git repo)
- Build Docker images
- Start all services (web, db, nginx, certbot)
- Run database migrations
- Collect static files

#### Verify Deployment

Check service status:

```bash
sudo .do/droplet/deploy.sh status
```

View logs:

```bash
sudo .do/droplet/deploy.sh logs
# Or for specific service:
sudo .do/droplet/deploy.sh logs web
```

#### Access Your Application

Your app is now running at:
- HTTP: `http://your-droplet-ip`
- HTTPS: Not yet configured (next step)

### SSL Configuration

#### 1. Point Your Domain

Add an A record in your DNS provider:

```
Type: A
Name: @ (or feedback)
Value: your-droplet-ip
TTL: 300
```

Wait for DNS propagation (can take 5-30 minutes). Verify:

```bash
dig yourdomain.com
# or
nslookup yourdomain.com
```

#### 2. Set Up Let's Encrypt

Run the SSL setup script:

```bash
sudo .do/droplet/deploy.sh ssl
```

This will:
1. Prompt for your domain and email
2. Update nginx configuration
3. Obtain Let's Encrypt SSL certificate
4. Configure nginx for HTTPS
5. Set up automatic renewal

Your app is now accessible at:
- `https://yourdomain.com`

#### 3. Verify SSL

Check certificate:

```bash
sudo docker compose -f .do/droplet/docker-compose.production.yml exec nginx ls -la /etc/letsencrypt/live/
```

Test renewal (dry run):

```bash
sudo docker compose -f .do/droplet/docker-compose.production.yml exec certbot certbot renew --dry-run
```

### Database Backups (Droplet)

#### Create Manual Backup

```bash
sudo .do/droplet/deploy.sh backup
```

Backups are stored in `/opt/blik/backups/`

#### Restore from Backup

```bash
sudo .do/droplet/deploy.sh restore
```

#### Automated Backups

Uncomment the backup service in `.do/droplet/docker-compose.production.yml` to enable daily backups with 7-day retention.

#### DigitalOcean Managed Backups

Alternatively, use DigitalOcean's managed PostgreSQL with automated backups:

1. Create Managed Database → PostgreSQL 15
2. Update `docker-compose.production.yml` to remove the `db` service
3. Update `.env.production` with managed database credentials

### Updating the Application (Droplet)

```bash
cd /opt/blik
git pull
sudo .do/droplet/deploy.sh deploy
```

---

## Post-Deployment

### 1. Access Setup Wizard

Visit your application URL and navigate to `/setup/`:

- **App Platform**: `https://your-app.ondigitalocean.app/setup/`
- **Droplet**: `https://yourdomain.com/setup/`

Complete the installation wizard:
1. Set organization name
2. Create admin user
3. Configure email settings (if not set via environment)
4. Test email delivery

### 2. Create Your First Review Cycle

1. Log in as admin
2. Go to **Admin** → **Questionnaires**
3. Select a template or create custom questionnaire
4. Create a review cycle
5. Invite participants

### 3. Security Checklist

- [ ] SSL/HTTPS is working
- [ ] `DEBUG=False` in environment
- [ ] Strong `SECRET_KEY` and `ENCRYPTION_KEY`
- [ ] Database password is secure
- [ ] Email is configured and tested
- [ ] Firewall is enabled (Droplet only)
- [ ] Regular backups are scheduled
- [ ] Admin user has strong password

### 4. Optional Configuration

#### Custom Domain (App Platform)
See [Custom Domain section](#custom-domain-app-platform) above.

#### Email Deliverability
- Set up SPF, DKIM, and DMARC records for your domain
- Use a dedicated email service (SendGrid, Amazon SES) for better deliverability
- Configure email reply-to address

#### Monitoring & Alerts
- **App Platform**: Use built-in Insights and Alerts
- **Droplet**: Consider setting up monitoring (e.g., Uptime Robot, New Relic)

---

## Troubleshooting

### Common Issues

#### App Platform: Application Won't Start

**Check logs:**
```
Apps → Your App → Runtime Logs
```

**Common causes:**
- Missing environment variables
- Database not attached
- Invalid `SECRET_KEY` or `ENCRYPTION_KEY`
- SMTP credentials incorrect

**Solution:**
1. Verify all required environment variables are set
2. Check that database component is attached
3. Review build logs for errors

#### App Platform: Static Files Not Loading

Blik uses WhiteNoise to serve static files. This should work automatically.

**Verify:**
1. Check that `STATIC_ROOT=/app/staticfiles` is set (automatic in Dockerfile)
2. Review build logs for `collectstatic` output
3. Ensure WhiteNoise is in `INSTALLED_APPS` (already configured)

#### Droplet: Connection Refused

**Check firewall:**
```bash
sudo ufw status
```

**Ensure ports are open:**
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

#### Droplet: nginx Won't Start

**Check nginx configuration:**
```bash
sudo docker compose -f .do/droplet/docker-compose.production.yml exec nginx nginx -t
```

**Common causes:**
- SSL certificate paths incorrect (before SSL setup)
- Domain name not updated in `nginx.conf`

**Solution for initial deployment:**
Edit `.do/droplet/nginx.conf` and comment out SSL certificate lines until you run the SSL setup.

#### Droplet: Database Connection Error

**Check database status:**
```bash
sudo docker compose -f .do/droplet/docker-compose.production.yml ps db
```

**View database logs:**
```bash
sudo docker compose -f .do/droplet/docker-compose.production.yml logs db
```

**Verify credentials:**
Check that `DATABASE_PASSWORD` in `.env.production` matches the `POSTGRES_PASSWORD`.

#### Email Not Sending

**Test SMTP connection:**
```bash
# App Platform
doctl apps logs <app-id> --type RUN

# Droplet
sudo docker compose -f .do/droplet/docker-compose.production.yml exec web python manage.py shell
```

```python
from django.core.mail import send_mail
send_mail('Test', 'Test message', 'from@example.com', ['to@example.com'])
```

**Common causes:**
- Incorrect SMTP credentials
- Gmail: Using account password instead of app password
- Firewall blocking port 587 (Droplet)
- SMTP host requires TLS on different port

**Gmail setup:**
1. Enable 2-factor authentication
2. Generate app password: https://myaccount.google.com/apppasswords
3. Use app password in `EMAIL_HOST_PASSWORD`

#### 500 Internal Server Error

**Check logs:**
```bash
# App Platform
Apps → Runtime Logs

# Droplet
sudo .do/droplet/deploy.sh logs web
```

**Common causes:**
- `ALLOWED_HOSTS` doesn't include your domain
- `CSRF_TRUSTED_ORIGINS` doesn't include your domain
- Database migration not run
- Missing static files

### Getting Help

If you encounter issues not covered here:

1. **Check logs** (see above for how to access logs)
2. **Review environment variables** against `.env.digitalocean.template`
3. **Consult main deployment docs**: `docs/DEPLOYMENT.md`
4. **GitHub Issues**: https://github.com/yourusername/blik/issues
5. **DigitalOcean Community**: https://www.digitalocean.com/community

---

## Cost Comparison

### App Platform

| Component | Tier | Monthly Cost |
|-----------|------|--------------|
| Web Service | Basic XXS (512MB) | $5 |
| Web Service | Basic XS (1GB, recommended) | $12 |
| PostgreSQL | Basic (1GB, 10GB storage) | $15 |
| **Total (Testing)** | | **$20** |
| **Total (Production)** | | **$27** |

**Pros:**
- Fully managed
- Auto-scaling
- Zero-downtime deployments
- Automatic SSL
- Built-in monitoring
- GitHub auto-deploy

**Best for:** Quick deployment, managed infrastructure, teams without DevOps

### Droplet

| Component | Tier | Monthly Cost |
|-----------|------|--------------|
| Droplet | Basic (1GB RAM, 25GB SSD) | $6 |
| Droplet | Basic (2GB RAM, 50GB SSD) | $12 |
| Backups | +20% of droplet cost | $1.20-$2.40 |
| **Total (Small)** | | **$7.20** |
| **Total (Production)** | | **$14.40** |

**Optional Add-ons:**
- Managed PostgreSQL: +$15/month (high availability, automated backups)
- Spaces (object storage): $5/month (if needed for media files)

**Pros:**
- Lower cost
- Full control
- Can run multiple apps
- Local volume storage

**Cons:**
- Manual management
- No auto-scaling
- Responsible for security updates
- Manual SSL renewal monitoring

**Best for:** Cost optimization, full control, existing DevOps expertise

---

## Next Steps

- [ ] Complete post-deployment checklist
- [ ] Set up monitoring and alerts
- [ ] Configure automated backups
- [ ] Plan scaling strategy
- [ ] Review security best practices
- [ ] Set up staging environment

---

## Resources

- [DigitalOcean App Platform Docs](https://docs.digitalocean.com/products/app-platform/)
- [DigitalOcean Droplet Docs](https://docs.digitalocean.com/products/droplets/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Django Deployment Checklist](https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/)
- [Main Blik Deployment Guide](DEPLOYMENT.md)
