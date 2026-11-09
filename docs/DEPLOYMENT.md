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

# CRITICAL: Disable debug mode in production
DEBUG=False

# REQUIRED: Add your domain(s) here, comma-separated
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# REQUIRED: CSRF trusted origins (include protocol)
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# CRITICAL: Set to True when using HTTPS (which you should be!)
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# REQUIRED: Encryption key for sensitive data (SMTP passwords in database)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=<your-encryption-key-here>
```

**Note on SECRET_KEY:**
- If not set, a secure random key is **auto-generated on first startup**
- For production, it's recommended to set a persistent value so sessions remain valid across restarts
- The auto-generated key will be displayed in the logs on first startup

**Generate keys manually:**
```bash
# SECRET_KEY
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
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

Any `EMAIL_*` variable you set here is authoritative: it is written to the
organization on every container start, and the matching field on the Settings
page is shown read-only ("Managed by `EMAIL_HOST` in the environment"). To
configure SMTP from the admin UI instead, leave these unset or empty
(`EMAIL_HOST=`). See [ADMIN_GUIDE.md](ADMIN_GUIDE.md#settings-managed-by-environment-variables).

#### Site URLs (used in every email link)
```env
SITE_DOMAIN=feedback.yourdomain.com
SITE_PROTOCOL=https
```

All links in outgoing email — reviewer invitations, self-assessments, report
links — are built from `SITE_DOMAIN`, never from the incoming request's host.
Behind a reverse proxy the request host is often an internal upstream name, so
deriving links from it would send recipients a URL they cannot open. Set
`SITE_DOMAIN` to the public hostname your users type in the browser.

#### Organization Settings
```env
ORGANIZATION_NAME=Your Company Name
# Default language of emails and feedback forms: en, de or de-informal
ORGANIZATION_LANGUAGE=en
```

#### Report PDFs (Optional)
```env
# Where generated report PDFs are stored. Never served directly. Default: privatefiles/
PRIVATE_MEDIA_ROOT=
# Days a report PDF is kept before it is deleted. An organization can override this. Default: 30
REPORT_PDF_RETENTION_DAYS=30
```

The PDFs are a cache of the stored report. If `privatefiles/` is lost, nothing breaks: the
report shows "Regenerate PDF" instead of "Download PDF".
Put `privatefiles/` on a persistent volume to keep the PDFs after a redeploy. If you do not, each
report shows "Regenerate PDF" after each deploy.

#### Port Configuration (Optional)
```env
# Internal port for main application container
# Default: 8000 (usually no need to change)
PORT=8000

# Public nginx port (if using multi-container setup)
# Default: 80
NGINX_PORT=80
```

**Note:** Platforms like Dokploy/Railway handle port mapping automatically. Only change if you have port conflicts.

#### Stripe Settings (Optional - For SaaS Billing)

If you're running Blik as a SaaS product with Stripe billing, configure these:

```env
# Get from Stripe Dashboard > Developers > API keys
STRIPE_PUBLISHABLE_KEY=pk_live_your_key_here
STRIPE_SECRET_KEY=sk_live_your_key_here

# Get from Stripe Dashboard > Developers > Webhooks
# After creating webhook endpoint at: https://yourdomain.com/api/stripe/webhook/
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here

# Create products in Stripe Dashboard > Products
# Copy the Price ID for each product (starts with price_...)
STRIPE_PRICE_ID_SAAS=price_your_saas_price_id_here
STRIPE_PRICE_ID_ENTERPRISE=price_your_enterprise_price_id_here
STRIPE_PRICE_ID_SINGLE=price_your_single_round_price_id_here
```

See [docs/STRIPE_WEBHOOKS.md](STRIPE_WEBHOOKS.md) for complete Stripe setup instructions.

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

**SSL Termination Architecture**

Your load balancer or reverse proxy handles SSL termination:

- **External traffic:** HTTPS (encrypted) from users to load balancer
- **Internal traffic:** HTTP (unencrypted) from load balancer to your container

The container listens on HTTP (port 8000). SSL is terminated upstream.

**Security cookie settings:**
```env
SESSION_COOKIE_SECURE=True   # Safe: Django sees X-Forwarded-Proto: https
CSRF_COOKIE_SECURE=True      # Safe: Django sees X-Forwarded-Proto: https
```

These work because the load balancer forwards the `X-Forwarded-Proto: https` header, telling Django the original request was HTTPS.

**❌ Avoid infinite redirect loops:**

Do NOT force HTTPS at the application level when SSL is terminated upstream:
1. Load balancer terminates SSL, forwards HTTP to container
2. If container redirects to HTTPS, load balancer forwards HTTP again
3. Infinite loop

**✅ Correct configuration:**
- SSL termination at load balancer/proxy
- Set `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True`
- Do NOT set `SECURE_SSL_REDIRECT=True` in Django
- Do NOT add HTTPS redirects inside the container

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
- `SECRET_KEY` - Generate a new one (or leave blank for auto-generation)
- `ENCRYPTION_KEY` - Generate with cryptography.fernet (required!)
- `DEBUG=False`
- `ALLOWED_HOSTS` - Your domain(s)
- `CSRF_TRUSTED_ORIGINS` - Your domain(s) with https:// protocol
- `DATABASE_PASSWORD` - Secure password
- `EMAIL_*` - Your SMTP settings (these override the admin UI — see above)
- `SITE_DOMAIN` - Public hostname; every link in outgoing email is built from it
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

**SSL Termination**

SSL should be terminated at the reverse proxy, not in the application container.

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
        proxy_set_header X-Forwarded-Proto $scheme;  # CRITICAL: Tells Django request was HTTPS
    }

    location /static/ {
        alias /path/to/blik/staticfiles/;
    }
}
```

**Example Caddy Configuration (Simpler - SSL automatic):**

```
yourdomain.com {
    reverse_proxy localhost:8000
    # Caddy automatically sets X-Forwarded-Proto
}
```

**Required Headers:**

The `X-Forwarded-Proto` header tells Django the original request protocol, enabling secure cookies:

```env
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

Without this header, these settings will break (Django thinks all requests are HTTP).

**Do NOT set `SECURE_SSL_REDIRECT=True`** - it causes infinite loops when SSL is terminated upstream.

### Behind a reverse proxy or Cloudflare

Blik limits login and signup attempts by client IP. It also locks out an IP after repeated failed logins. Behind a proxy, Django sees the proxy's IP. All visitors then share one limit.

Set `TRUSTED_CLIENT_IP_HEADER` so Blik reads the visitor IP from a request header. Use the Django META form of the header name:

```env
# Cloudflare
TRUSTED_CLIENT_IP_HEADER=HTTP_CF_CONNECTING_IP

# A proxy that sets X-Real-IP from the connecting address
TRUSTED_CLIENT_IP_HEADER=HTTP_X_REAL_IP
```

Empty is the default. Blik then uses the direct connection address. An invalid header value also falls back to that address.

> **Warning:** Set this only when every request passes through that proxy. If the server is reachable directly, anyone can send the header with any IP. They can then get around the rate limits and lockouts.

**Check that the server is not reachable directly**

Run this from another machine:

```bash
curl -sI --max-time 5 -H 'Host: <your-domain>' http://<server-ip>/accounts/login/
```

Any HTTP response means the server is reachable without the proxy. Fix this before you set the header.

**Fix for Cloudflare**

- Allow ports 80 and 443 only from [Cloudflare's IP ranges](https://www.cloudflare.com/ips/). Set this in the firewall of your hosting provider (for example Hetzner Cloud Firewall or DigitalOcean Cloud Firewall).
- A host `ufw` rule alone does not protect the server. Ports that Docker publishes bypass the `ufw` and iptables INPUT rules.
- Alternative: add a Traefik `ipAllowList` middleware with Cloudflare's ranges.
- Alternative: use Cloudflare Tunnel. It needs no open ports.

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

### DigitalOcean

DigitalOcean offers two deployment options:

**App Platform (Recommended)** - Fully managed PaaS with auto-scaling and zero-downtime deployments:
- One-click deploy via "Deploy to DigitalOcean" button in README
- Automatic SSL certificates and GitHub integration
- Cost: ~$20/month (web + database)

**Droplet** - VPS with full control and lower cost:
- Docker Compose setup with automated deployment script
- Manual SSL setup with Let's Encrypt
- Cost: ~$7-15/month depending on configuration

See the comprehensive **[DigitalOcean Deployment Guide](DIGITALOCEAN.md)** for detailed instructions on both options, including:
- One-click App Platform deployment
- Droplet setup with automation scripts
- SSL configuration
- Database backups
- Troubleshooting guide

### AWS/GCP/Azure

Use the Docker Compose configuration with your platform's container orchestration:
- **AWS:** ECS with RDS PostgreSQL
- **GCP:** Cloud Run with Cloud SQL
- **Azure:** Container Instances with Azure Database for PostgreSQL

---

## Post-Deployment Checklist

### Security
- [ ] SSL/HTTPS is configured and working
- [ ] `DEBUG=False` in production
- [ ] Strong `SECRET_KEY` is set (or auto-generated)
- [ ] `ENCRYPTION_KEY` is set and unique
- [ ] Database password is secure
- [ ] `ALLOWED_HOSTS` includes your domain(s)
- [ ] `CSRF_TRUSTED_ORIGINS` includes your domain(s) with https://
- [ ] Security cookies enabled (`SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`)

### Application
- [ ] Email is configured and tested
- [ ] Admin account created (via /setup/ or env vars)
- [ ] Default questionnaires loaded
- [ ] Static files are being served correctly
- [ ] `docker compose exec web crontab -l` shows the `send_queued_invitations` line (invitation emails go out from a queue every 5 minutes; without it, no invitation or reminder is ever sent)

### Operations
- [ ] Database backups configured
- [ ] Monitoring/logging set up (optional)
- [ ] Port configuration correct (if customized)

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

### Upgrading to the report PDF release

This release adds system libraries (Pango, for WeasyPrint) and a Python dependency, so the image
must be rebuilt. In Dokploy, click **"Redeploy"** so it rebuilds the image. A `git pull` and a
container restart are not enough: every `manage.py` command then stops with check `reports.E001`.

Stop the old container before the migration runs. If you do not, a cycle that completes during the
redeploy can get its report email two times.

After the deploy, run once:

```bash
docker compose exec web python manage.py backfill_report_pdfs
```

It builds the report and the PDF for every cycle the migration already marked as finalised. It
sends no email. It exits with a non-zero status if a cycle failed, and it is safe to run again.
Add `--dry-run` to only count what is missing.
Add `--regenerate` to recalculate existing reports with the current scoring rules and questionnaire texts.
It sends the `report.generated` webhook only for reports that did not exist yet; a recalculated report
sends none. It keeps a report as it is when a new one would lose answers
(for example of a deleted question), prints a warning that names the cycle, and still stores its PDF.

After this release, run this once:

```bash
docker compose exec web python manage.py backfill_report_pdfs --regenerate
```

This release changes the definition of "others" (direct reports count in every others score). Without
`--regenerate`, stored reports mix the old and the new definition in one PDF.

The entrypoint now also installs a cron line that finalises reports every 5 minutes:

```cron
*/5 * * * * . /app/.env.cron && cd /app && flock -n /tmp/finalize_reports.lock python manage.py finalize_reports >> /var/log/cron.log 2>&1
```

Do not add it to your own crontab when the entrypoint runs. Without the entrypoint, add it to the crontab.

### Upgrading to the invitation outbox release

Invitation and reminder emails no longer go out inside the web request. An admin's "send" puts
them in a queue (timestamps on the reviewer tokens, see migration `reviews.0011_outbox`), and the
`send_queued_invitations` command sends them, one email per address, each in its own transaction.
The entrypoint installs its cron line next to `finalize_reports`:

```cron
*/5 * * * * . /app/.env.cron && cd /app && flock -n /tmp/send_queued_invitations.lock python manage.py send_queued_invitations >> /var/log/cron.log 2>&1
```

Without the entrypoint, add it to the crontab. **Without this job no invitation or reminder is
ever sent**; the admin sees the emails stay "Queued" on the cycle page.

A send that fails is written to the token (the admin sees the mail server's answer on the cycle
page) and tried again on the next runs, five attempts in all. The job records a `CronRun` row
(Django admin → Notifications → Cron runs) only for runs that sent something or hit an error, so
the table stays small.

Check after the deploy:

1. `docker compose exec web crontab -l` shows the `send_queued_invitations` line.
2. In a test organization, send an invitation from a cycle page. Within five minutes the row goes
   from **Queued** to **Sent**, and `docker compose exec web cat /var/log/cron.log` shows
   `Emails sent: 1`.

### Upgrading to the org chart and one-email release

This release ships with the report PDF release above, so do its steps first: redeploy so the image
is rebuilt, then run the PDF backfill once.

What is new for operators:

- **Migrations.** `accounts.0011_org_units` creates the `org_units` and `org_unit_memberships` tables.
  The entrypoint runs it.
- **No new environment variables.** `REPORT_PDF_RETENTION_DAYS` (default 30) is the only new
  setting, from the PDF release.
- **Signed links depend on `SECRET_KEY`.** The personal overview link in the bundled invitation email
  is a signed URL. If you rotate `SECRET_KEY`, every overview link that is out there stops working.
  Reviewers then see the "link expired" page and can request a new one. The form links themselves
  are not affected.
- **Translations compile on start.** The catalogues changed a lot. If a German, Spanish or Italian
  screen shows English after the deploy, run `docker compose exec web python manage.py compilemessages`
  and restart.

Check after the deploy:

1. `curl -sI https://<landing>/sample-report.pdf | head -1` returns `200`. The landing container
   renders this PDF with the current code every time it starts, so it is fresh after every landing
   deploy. The HR and FAQ pages link to it. A 404 means the render failed: look for "sample report"
   in the landing container's log.
2. The cron line for `finalize_reports` is installed: `docker compose exec web crontab -l`.
3. In a test organization: import a small CSV on **Organization → Org chart**, create a bulk round with
   **Derive from org chart**, and send. Every address gets one email. The overview link in it opens.
4. Organizations with small teams: set **Minimum responses for anonymity** to 2 in Settings → Reports,
   or the direct-report group stays hidden for a head with two reports.

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

### Infinite Redirect Loop (HTTPS)

**Symptom:** Browser shows "too many redirects" or "redirect loop" error.

**Cause:** Application is redirecting to HTTPS, but load balancer already terminated SSL and forwards HTTP to the container.

**Solution:**
1. Verify `X-Forwarded-Proto` header is set by your load balancer/proxy
2. Ensure Django settings do NOT include `SECURE_SSL_REDIRECT = True`
3. Remove any HTTPS redirects in application-level nginx/code
4. Keep only:
   ```env
   SESSION_COOKIE_SECURE=True
   CSRF_COOKIE_SECURE=True
   ```

### CSRF Verification Failed

**Symptom:** "CSRF verification failed" error on forms.

**Causes and solutions:**

1. **Missing CSRF_TRUSTED_ORIGINS:**
   ```env
   CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
   ```
   Must include the full protocol (https://) and domain.

2. **Load balancer not forwarding X-Forwarded-Proto:**
   - Verify your proxy includes: `proxy_set_header X-Forwarded-Proto $scheme;`
   - Most platforms/load balancers set this automatically

3. **Wrong ALLOWED_HOSTS:**
   ```env
   ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
   ```
   Must match the domain you're accessing.

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
4. Invitations and reminders stay **Queued** on the cycle page: the outbox cron is not running.
   `docker compose exec web crontab -l` must list `send_queued_invitations`; `docker compose exec web
   python manage.py send_queued_invitations` sends the queue by hand. A **Failed** state on the cycle
   page shows the mail server's answer; `/var/log/cron.log` in the container has the traceback.

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

2. **Generate unique keys for production**
   ```bash
   # SECRET_KEY (Django)
   python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

   # ENCRYPTION_KEY (for SMTP passwords)
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   **WARNING:** Never reuse the default `ENCRYPTION_KEY` from `.env.example` in production!

3. **Keep dependencies updated**
   ```bash
   uv pip list --outdated
   uv pip install --upgrade <package>
   ```

4. **Regular security audits**
   ```bash
   uv pip install safety
   safety check
   ```

5. **Use strong passwords**
   - Database password: 32+ characters
   - Admin password: 16+ characters
   - SECRET_KEY: Django's generated key (50+ characters)
   - ENCRYPTION_KEY: Fernet-generated key

6. **Enable fail2ban or similar**
   - Protect against brute force login attempts

7. **Regular backups**
   - Database: Daily automated backups
   - Retention: Keep 7-30 days of backups
   - Test restore process quarterly

8. **Monitor logs**
   - Set up centralized logging (e.g., Sentry, LogDNA)
   - Alert on errors and security events

9. **Review docker-compose.yml**
   - Remove the hardcoded `SECRET_KEY` line if present
   - Ensure all secrets come from environment variables

---

## Support

- **Documentation:** `/docs/` directory
- **Issues:** GitHub Issues
- **Setup Wizard:** Available at `/setup/` on first run
