#!/bin/bash
# Screenshot generation for Docker environment
# Runs Django commands inside Docker container, screenshots locally

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Blik Screenshot Generation (Docker)"
echo "=========================================="
echo ""

cd "$PROJECT_DIR"

# Check Docker is running
if ! docker compose ps web 2>/dev/null | grep -q "Up"; then
    echo "Error: Docker containers not running"
    echo "Start with: docker compose up -d"
    exit 1
fi

echo "✓ Docker containers running"
echo ""

# Check server
echo "Checking if Django server is running..."
if ! curl -s http://localhost:8000 > /dev/null; then
    echo "Error: Server not responding on http://localhost:8000"
    exit 1
fi
echo "✓ Server is running"
echo ""

# Step 1: Generate demo data in Docker
echo "Step 1: Generating demo data..."
docker compose exec web python manage.py generate_screenshot_data --clear

# Copy config from container to host
echo "  Copying configuration from container..."
docker compose exec web cat /tmp/blik_screenshot_config.json > /tmp/blik_screenshot_config.json

echo "✓ Demo data generated"
echo ""

# Step 2: Install dependencies locally if needed
echo "Step 2: Setting up local environment for screenshots..."

if ! python -c "import playwright" 2>/dev/null; then
    echo "  Installing playwright..."
    pip install playwright
    playwright install chromium
fi

if ! python -c "from PIL import Image" 2>/dev/null; then
    echo "  Installing Pillow..."
    pip install Pillow
fi

echo "✓ Screenshot dependencies ready"
echo ""

# Step 3: Capture screenshots (locally, but using Docker DB via localhost)
echo "Step 3: Capturing screenshots..."
python manage.py capture_screenshots

SCREENSHOT_DIR="$PROJECT_DIR/static/img/screenshots"
if [ ! -d "$SCREENSHOT_DIR" ] || [ -z "$(ls -A "$SCREENSHOT_DIR" 2>/dev/null)" ]; then
    echo "Error: No screenshots were created"
    exit 1
fi

SCREENSHOT_COUNT=$(ls -1 "$SCREENSHOT_DIR"/*.png 2>/dev/null | wc -l)
echo "✓ Captured $SCREENSHOT_COUNT screenshots"
echo ""

# Step 4: Optimize
echo "Step 4: Optimizing screenshots..."
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
ls -lh "$SCREENSHOT_DIR" | grep -E '\.(png|webp)$' | tail -20
echo ""
echo "Next steps:"
echo "1. Review: open $SCREENSHOT_DIR"
echo "2. Test: http://localhost:8000/landing/"
echo "3. Commit: git add static/img/screenshots/ && git commit -m 'Update screenshots'"
echo ""
