#!/bin/bash
# Complete screenshot generation workflow for Blik
# Generates demo data, captures screenshots, and optimizes images

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Blik Screenshot Generation Workflow"
echo "=========================================="
echo ""

# Check if running in project directory
if [ ! -f "$PROJECT_DIR/manage.py" ]; then
    echo "Error: manage.py not found. Please run from project root or scripts directory."
    exit 1
fi

cd "$PROJECT_DIR"

# Detect if using Docker
USE_DOCKER=false
DOCKER_CONTAINER=""

if docker compose ps web 2>/dev/null | grep -q "Up"; then
    USE_DOCKER=true
    DOCKER_CONTAINER=$(docker compose ps -q web)
    echo "✓ Detected running Docker containers"
    echo "  Using Docker container: web"
    echo ""
elif docker ps --format '{{.Names}}' | grep -q "blik.*web"; then
    USE_DOCKER=true
    DOCKER_CONTAINER=$(docker ps --format '{{.Names}}' | grep "blik.*web" | head -n 1)
    echo "✓ Detected running Docker containers"
    echo "  Using Docker container: $DOCKER_CONTAINER"
    echo ""
else
    echo "Docker containers not detected, using local environment"
    echo ""

    # Check dependencies for local environment
    echo "Checking dependencies..."
    if ! python -c "import playwright" 2>/dev/null; then
        echo "Error: Playwright not installed."
        echo "Run: pip install -r requirements-screenshots.txt && playwright install chromium"
        exit 1
    fi

    if ! python -c "from PIL import Image" 2>/dev/null; then
        echo "Error: Pillow not installed."
        echo "Run: pip install -r requirements-screenshots.txt"
        exit 1
    fi

    echo "✓ Dependencies installed"
    echo ""
fi

# Check if server is running
echo "Checking if Django server is running..."
if ! curl -s http://localhost:8000 > /dev/null; then
    echo ""
    echo "Warning: Django server not responding on http://localhost:8000"
    echo "Please start the server:"
    if [ "$USE_DOCKER" = true ]; then
        echo "  docker compose up -d"
    else
        echo "  python manage.py runserver"
    fi
    echo ""
    read -p "Press Enter when server is running, or Ctrl+C to exit..."
fi

echo "✓ Server is running"
echo ""

# Helper function to run Django command
run_django_command() {
    if [ "$USE_DOCKER" = true ]; then
        docker compose exec web python manage.py "$@"
    else
        python manage.py "$@"
    fi
}

# Step 1: Generate demo data
echo "Step 1: Generating demo data..."
if [ "$USE_DOCKER" = true ]; then
    echo "  Running in Docker container..."
    run_django_command generate_screenshot_data --clear
else
    python manage.py generate_screenshot_data --clear
fi

# Check if config was created
# Note: Docker containers write to /tmp inside the container, we need to check differently
echo "✓ Demo data generated"
echo ""

# Step 2: Capture screenshots (always run locally since Playwright needs browser access)
echo "Step 2: Capturing screenshots..."
echo "  Note: Screenshot capture runs locally (requires browser access)"
echo ""

# Install playwright if needed
if ! python -c "import playwright" 2>/dev/null; then
    echo "Installing playwright locally for screenshot capture..."
    pip install playwright
    playwright install chromium
fi

python manage.py capture_screenshots

# Check if screenshots were created
SCREENSHOT_DIR="$PROJECT_DIR/static/img/screenshots"
if [ ! -d "$SCREENSHOT_DIR" ] || [ -z "$(ls -A "$SCREENSHOT_DIR" 2>/dev/null)" ]; then
    echo "Error: No screenshots were created"
    exit 1
fi

SCREENSHOT_COUNT=$(ls -1 "$SCREENSHOT_DIR"/*.png 2>/dev/null | wc -l)
echo "✓ Captured $SCREENSHOT_COUNT screenshots"
echo ""

# Step 3: Optimize screenshots (run locally)
echo "Step 3: Optimizing screenshots..."
echo "  Running image optimization locally..."

if ! python -c "from PIL import Image" 2>/dev/null; then
    echo "Installing Pillow locally for image optimization..."
    pip install Pillow
fi

python manage.py optimize_screenshots --webp

echo "✓ Screenshots optimized"
echo ""

# Show results
echo "=========================================="
echo "Screenshot Generation Complete!"
echo "=========================================="
echo ""
echo "Screenshots saved to: $SCREENSHOT_DIR"
echo ""
echo "Generated files:"
ls -lh "$SCREENSHOT_DIR" | tail -n +2
echo ""
echo "Next steps:"
echo "1. Review screenshots: open $SCREENSHOT_DIR"
echo "2. Test landing page: http://localhost:8000/landing/"
echo "3. Commit changes:"
echo "   git add static/img/screenshots/"
echo "   git commit -m 'Update landing page screenshots'"
echo ""
