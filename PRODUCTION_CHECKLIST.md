# Production Deployment Checklist

Use this checklist before deploying Blik to production.

## Pre-Deployment

### Security Configuration

- [ ] Generate a new `SECRET_KEY` (don't use the example key!)
  ```bash
  python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
  ```
- [ ] Set `DEBUG=False` in production environment
- [ ] Configure `ALLOWED_HOSTS` with your actual domain(s)
- [ ] Set `SESSION_COOKIE_SECURE=True` (requires HTTPS)
- [ ] Set `CSRF_COOKIE_SECURE=True` (requires HTTPS)
- [ ] Use a strong database password (32+ characters recommended)
- [ ] Never commit `.env` or `.env.production` to version control

### Database

- [ ] PostgreSQL 15+ configured and accessible
- [ ] Database credentials set correctly in environment variables
- [ ] Database has adequate storage and backup strategy
- [ ] Connection pooling configured if needed for high load

### Email (SMTP)

- [ ] SMTP server configured (Gmail, SendGrid, AWS SES, etc.)
- [ ] Email credentials set in environment variables
- [ ] `DEFAULT_FROM_EMAIL` set to appropriate sender address
- [ ] Test email sending works:
  ```bash
  docker compose exec web python manage.py shell
  >>> from django.core.mail import send_mail
  >>> send_mail('Test', 'Body', 'from@domain.com', ['to@domain.com'])
  ```

### SSL/HTTPS

- [ ] SSL certificate obtained (Let's Encrypt recommended)
- [ ] HTTPS configured via reverse proxy (Nginx/Caddy) or platform (Dokploy)
- [ ] HTTP redirects to HTTPS
- [ ] Security headers configured (HSTS, etc.)

### Infrastructure

- [ ] Server has adequate resources:
  - Minimum: 1GB RAM, 1 CPU core, 10GB storage
  - Recommended: 2GB+ RAM, 2+ CPU cores, 20GB+ storage
- [ ] Docker and Docker Compose installed
- [ ] Firewall configured (allow ports 80, 443; block port 8000 from external)
- [ ] Reverse proxy configured (Nginx, Caddy, or Traefik)

## Deployment

### Initial Deploy

- [ ] Clone repository or connect to deployment platform
- [ ] Copy `.env.production` to `.env` and customize all values
- [ ] Build and start containers: `docker compose up -d --build`
- [ ] Verify containers are running: `docker compose ps`
- [ ] Check logs for errors: `docker compose logs`

### Setup Application

- [ ] Visit `https://yourdomain.com/setup/` for first-time setup wizard
- [ ] Create admin account with strong password (16+ characters)
- [ ] Configure organization name and details
- [ ] Configure email settings (or skip and set in environment variables)
- [ ] Load default questionnaires (Professional Skills & Software Engineering)
- [ ] Optionally generate test data to explore features

### Verification

- [ ] Admin dashboard accessible at `/dashboard/`
- [ ] Static files loading correctly (CSS, images)
- [ ] Can create a test review cycle
- [ ] Can access feedback form via token
- [ ] Email notifications working (test with reminder)
- [ ] Reports generate successfully
- [ ] All pages load over HTTPS with valid certificate

## Post-Deployment

### Monitoring

- [ ] Set up log monitoring (check `docker compose logs -f`)
- [ ] Configure uptime monitoring (e.g., UptimeRobot, Pingdom)
- [ ] Set up error tracking (e.g., Sentry) - optional
- [ ] Monitor disk space usage

### Backups

- [ ] Database backup configured (daily recommended)
  ```bash
  # Manual backup
  docker compose exec db pg_dump -U blik blik > backup.sql
  ```
- [ ] Backup retention policy defined (7-30 days)
- [ ] Test restore procedure
- [ ] Store backups off-server (S3, Backblaze, etc.)
- [ ] Document backup/restore procedures

### Maintenance

- [ ] Document update procedure for team
- [ ] Schedule regular security updates
- [ ] Plan for scaling if user base grows
- [ ] Set up monitoring for:
  - Database size
  - Disk space
  - Memory usage
  - Response times

### Documentation

- [ ] Admin credentials stored securely (password manager)
- [ ] Database credentials documented and secured
- [ ] SMTP credentials documented
- [ ] Deployment procedures documented for team
- [ ] Recovery procedures documented

## Security Hardening (Optional but Recommended)

- [ ] Configure fail2ban for brute force protection
- [ ] Set up automated security updates
- [ ] Regular dependency updates: `uv pip list --outdated`
- [ ] Enable database connection encryption
- [ ] Configure rate limiting at reverse proxy level
- [ ] Set up Web Application Firewall (WAF) - optional
- [ ] Regular security audits with `safety check`

## Performance Optimization (For High Load)

- [ ] Enable database query caching
- [ ] Configure CDN for static files - optional
- [ ] Set up database connection pooling (pgBouncer)
- [ ] Scale web workers: `docker compose up -d --scale web=3`
- [ ] Enable Gzip compression at reverse proxy
- [ ] Optimize database indexes if needed

## Compliance (If Applicable)

- [ ] Privacy policy created and linked
- [ ] Terms of service created
- [ ] GDPR compliance verified (if serving EU users)
- [ ] Data retention policy defined
- [ ] User data export capability tested
- [ ] Data deletion procedures documented

## Final Checks

- [ ] All team members have access to necessary credentials
- [ ] Deployment is documented in team wiki/docs
- [ ] Support/incident response plan in place
- [ ] Users notified of system availability
- [ ] Monitoring alerts configured and tested

---

## Quick Reference

### Generate Secure Passwords

```bash
# SECRET_KEY
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# Database password
openssl rand -base64 32

# Admin password
openssl rand -base64 24
```

### Common Commands

```bash
# View logs
docker compose logs -f web

# Restart application
docker compose restart web

# Database backup
docker compose exec db pg_dump -U blik blik | gzip > backup_$(date +%Y%m%d).sql.gz

# Update application
git pull && docker compose up -d --build

# Access Django shell
docker compose exec web python manage.py shell

# Create additional superuser
docker compose exec web python manage.py createsuperuser
```

### Support Resources

- **Documentation:** `/docs/` directory
- **Deployment Guide:** `docs/DEPLOYMENT.md`
- **User Guides:** `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`
- **GitHub Issues:** Report bugs and request features
