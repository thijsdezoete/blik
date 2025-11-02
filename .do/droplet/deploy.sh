#!/bin/bash
#
# Blik Deployment Script for DigitalOcean Droplet
# This script automates the deployment process on a fresh DigitalOcean Droplet
#
# Usage:
#   ./deploy.sh [command]
#
# Commands:
#   setup     - Initial server setup (install Docker, configure firewall)
#   deploy    - Deploy or update the application
#   ssl       - Set up Let's Encrypt SSL certificate
#   backup    - Create database backup
#   restore   - Restore database from backup
#   logs      - View application logs
#   status    - Check service status

set -e  # Exit on error

# Configuration
PROJECT_DIR="/opt/blik"
COMPOSE_FILE="${PROJECT_DIR}/.do/droplet/docker-compose.production.yml"
ENV_FILE="${PROJECT_DIR}/.env.production"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Please run as root (use sudo)"
        exit 1
    fi
}

# Initial server setup
setup() {
    check_root
    log_info "Starting initial server setup..."

    # Update system
    log_info "Updating system packages..."
    apt-get update
    apt-get upgrade -y

    # Install Docker
    if ! command -v docker &> /dev/null; then
        log_info "Installing Docker..."
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
        rm get-docker.sh
        systemctl enable docker
        systemctl start docker
    else
        log_info "Docker already installed"
    fi

    # Install Docker Compose
    if ! command -v docker compose &> /dev/null; then
        log_info "Docker Compose plugin should be installed with Docker"
    else
        log_info "Docker Compose already installed"
    fi

    # Configure firewall
    log_info "Configuring firewall..."
    ufw --force enable
    ufw allow 22/tcp    # SSH
    ufw allow 80/tcp    # HTTP
    ufw allow 443/tcp   # HTTPS
    ufw reload

    # Create project directory
    log_info "Creating project directory..."
    mkdir -p "$PROJECT_DIR"

    # Install Git if not present
    if ! command -v git &> /dev/null; then
        log_info "Installing Git..."
        apt-get install -y git
    fi

    log_info "Server setup complete!"
    log_warn "Next steps:"
    echo "  1. Clone your repository to $PROJECT_DIR"
    echo "  2. Copy .env.digitalocean.template to .env.production and configure it"
    echo "  3. Run: sudo ./deploy.sh deploy"
}

# Deploy application
deploy() {
    check_root
    log_info "Starting deployment..."

    # Check if .env.production exists
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env.production not found at $ENV_FILE"
        log_warn "Please copy .env.digitalocean.template to .env.production and configure it"
        exit 1
    fi

    # Pull latest changes (if git repo)
    if [ -d "${PROJECT_DIR}/.git" ]; then
        log_info "Pulling latest changes..."
        cd "$PROJECT_DIR"
        git pull
    fi

    # Build and start containers
    log_info "Building and starting containers..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" build --no-cache
    docker compose -f "$COMPOSE_FILE" up -d

    # Wait for services to be healthy
    log_info "Waiting for services to be ready..."
    sleep 10

    # Check service status
    docker compose -f "$COMPOSE_FILE" ps

    log_info "Deployment complete!"
    log_warn "Don't forget to set up SSL with: sudo ./deploy.sh ssl"
}

# Set up SSL certificate
ssl() {
    check_root
    log_info "Setting up Let's Encrypt SSL certificate..."

    # Check if .env.production exists and get domain
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env.production not found"
        exit 1
    fi

    # Prompt for domain and email
    read -p "Enter your domain name (e.g., example.com): " DOMAIN
    read -p "Enter your email address: " EMAIL

    if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
        log_error "Domain and email are required"
        exit 1
    fi

    # Update nginx.conf with domain
    log_info "Updating nginx configuration..."
    sed -i "s/yourdomain.com/$DOMAIN/g" "${PROJECT_DIR}/.do/droplet/nginx.conf"

    # Restart nginx to pick up HTTP config
    log_info "Restarting nginx..."
    docker compose -f "$COMPOSE_FILE" restart nginx

    # Obtain certificate
    log_info "Obtaining SSL certificate..."
    docker compose -f "$COMPOSE_FILE" run --rm certbot certonly \
        --webroot \
        --webroot-path /var/www/certbot \
        -d "$DOMAIN" \
        --email "$EMAIL" \
        --agree-tos \
        --no-eff-email

    # Restart nginx to use SSL
    log_info "Restarting nginx with SSL..."
    docker compose -f "$COMPOSE_FILE" restart nginx

    log_info "SSL certificate installed successfully!"
    log_info "Certificate will auto-renew via the certbot container"
}

# Create database backup
backup() {
    check_root
    log_info "Creating database backup..."

    BACKUP_DIR="${PROJECT_DIR}/backups"
    mkdir -p "$BACKUP_DIR"

    BACKUP_FILE="${BACKUP_DIR}/blik_$(date +%Y%m%d_%H%M%S).sql.gz"

    docker compose -f "$COMPOSE_FILE" exec -T db \
        pg_dump -U blik blik | gzip > "$BACKUP_FILE"

    log_info "Backup created: $BACKUP_FILE"

    # Keep only last 7 days of backups
    find "$BACKUP_DIR" -name "blik_*.sql.gz" -mtime +7 -delete
}

# Restore database from backup
restore() {
    check_root
    log_warn "This will restore the database from a backup file"
    log_warn "ALL CURRENT DATA WILL BE LOST!"
    read -p "Are you sure? (yes/no): " CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        log_info "Restore cancelled"
        exit 0
    fi

    # List available backups
    BACKUP_DIR="${PROJECT_DIR}/backups"
    log_info "Available backups:"
    ls -lh "$BACKUP_DIR"

    read -p "Enter backup filename: " BACKUP_FILE

    if [ ! -f "${BACKUP_DIR}/${BACKUP_FILE}" ]; then
        log_error "Backup file not found"
        exit 1
    fi

    log_info "Restoring database..."
    gunzip < "${BACKUP_DIR}/${BACKUP_FILE}" | \
        docker compose -f "$COMPOSE_FILE" exec -T db \
        psql -U blik blik

    log_info "Database restored successfully"
}

# View logs
logs() {
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100 "$@"
}

# Check service status
status() {
    log_info "Service status:"
    docker compose -f "$COMPOSE_FILE" ps

    log_info "\nRecent logs:"
    docker compose -f "$COMPOSE_FILE" logs --tail=20
}

# Main command handler
case "${1:-}" in
    setup)
        setup
        ;;
    deploy)
        deploy
        ;;
    ssl)
        ssl
        ;;
    backup)
        backup
        ;;
    restore)
        restore
        ;;
    logs)
        shift
        logs "$@"
        ;;
    status)
        status
        ;;
    *)
        echo "Blik Deployment Script"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  setup     - Initial server setup (install Docker, configure firewall)"
        echo "  deploy    - Deploy or update the application"
        echo "  ssl       - Set up Let's Encrypt SSL certificate"
        echo "  backup    - Create database backup"
        echo "  restore   - Restore database from backup"
        echo "  logs      - View application logs"
        echo "  status    - Check service status"
        echo ""
        echo "Example:"
        echo "  sudo $0 setup    # First time setup"
        echo "  sudo $0 deploy   # Deploy application"
        echo "  sudo $0 ssl      # Set up SSL"
        exit 1
        ;;
esac
