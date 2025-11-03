#!/bin/bash
#
# Blik Test Runner
# Zero-config Docker-based testing
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}→${NC} $1"
}

# Default values
MODE="run"
KEEP_DB=""
VERBOSE=""
TEST_PATH=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        setup)
            MODE="setup"
            shift
            ;;
        run)
            MODE="run"
            shift
            ;;
        shell)
            MODE="shell"
            shift
            ;;
        clean)
            MODE="clean"
            shift
            ;;
        mailpit)
            MODE="mailpit"
            shift
            ;;
        --keepdb)
            KEEP_DB="--keepdb"
            shift
            ;;
        -v|--verbose)
            VERBOSE="--verbosity=2"
            shift
            ;;
        *)
            TEST_PATH="$1"
            shift
            ;;
    esac
done

# Mode: Setup
if [ "$MODE" = "setup" ]; then
    print_header "Setting up test environment"

    print_info "Building Docker images..."
    docker compose -f docker-compose.test.yml build

    print_info "Starting services..."
    docker compose -f docker-compose.test.yml up -d db mailpit

    print_info "Waiting for database..."
    sleep 3

    print_success "Test environment ready!"
    print_info "Database: PostgreSQL (blik_test)"
    print_info "Email UI: http://localhost:8125"
    exit 0
fi

# Mode: Clean
if [ "$MODE" = "clean" ]; then
    print_header "Cleaning test environment"

    print_info "Stopping services..."
    docker compose -f docker-compose.test.yml down -v

    print_success "Test environment cleaned!"
    exit 0
fi

# Mode: Mailpit
if [ "$MODE" = "mailpit" ]; then
    print_header "Opening Mailpit email UI"

    # Check if Mailpit is running
    if ! docker compose -f docker-compose.test.yml ps mailpit | grep -q "Up"; then
        print_info "Starting Mailpit..."
        docker compose -f docker-compose.test.yml up -d mailpit
        sleep 2
    fi

    print_success "Mailpit is running at http://localhost:8125"

    # Try to open in browser
    if command -v open &> /dev/null; then
        open http://localhost:8125
    elif command -v xdg-open &> /dev/null; then
        xdg-open http://localhost:8125
    else
        print_info "Please open http://localhost:8125 in your browser"
    fi
    exit 0
fi

# Mode: Shell
if [ "$MODE" = "shell" ]; then
    print_header "Starting test shell"

    print_info "Starting services..."
    docker compose -f docker-compose.test.yml up -d db mailpit

    print_info "Waiting for database..."
    sleep 3

    print_success "Launching shell..."
    docker compose -f docker-compose.test.yml run --rm web bash
    exit 0
fi

# Mode: Run tests (default)
print_header "Running Blik Tests"

# Ensure services are running
print_info "Starting test services..."
docker compose -f docker-compose.test.yml up -d db mailpit

print_info "Waiting for database..."
sleep 3

# Build test command
TEST_CMD="python manage.py test"

if [ -n "$KEEP_DB" ]; then
    TEST_CMD="$TEST_CMD $KEEP_DB"
fi

if [ -n "$VERBOSE" ]; then
    TEST_CMD="$TEST_CMD $VERBOSE"
else
    TEST_CMD="$TEST_CMD --verbosity=1"
fi

if [ -n "$TEST_PATH" ]; then
    TEST_CMD="$TEST_CMD $TEST_PATH"
fi

print_info "Running: $TEST_CMD"
echo ""

# Run tests
docker compose -f docker-compose.test.yml run --rm \
    -e DJANGO_SETTINGS_MODULE=blik.settings \
    web sh -c "$TEST_CMD"

TEST_EXIT_CODE=$?

# Print results
echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_header "Tests Passed!"
    print_success "All tests completed successfully"
    print_info "Email UI: http://localhost:8125 (check sent emails)"
else
    print_header "Tests Failed"
    print_error "Some tests failed (exit code: $TEST_EXIT_CODE)"
fi

echo ""
print_info "Useful commands:"
echo "  ./test.sh                    # Run all tests"
echo "  ./test.sh accounts           # Run specific app tests"
echo "  ./test.sh --keepdb           # Keep database between runs"
echo "  ./test.sh -v                 # Verbose output"
echo "  ./test.sh shell              # Open test shell"
echo "  ./test.sh mailpit            # Open email UI"
echo "  ./test.sh clean              # Clean up test environment"
echo ""

exit $TEST_EXIT_CODE
