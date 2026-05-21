#!/bin/bash

# ==================== MalogBot v2.0 Deployment Script ====================
# Usage: ./deploy.sh [command]
# Commands:
#   start       - Start all services
#   stop        - Stop all services
#   restart     - Restart all services
#   build       - Build Docker images
#   logs        - Show logs
#   status      - Show service status
#   monitor     - Start with monitoring (Prometheus + Grafana)
#   init-db     - Initialize database tables
#   clean       - Remove all containers and volumes
#   help        - Show this help message

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env exists
check_env() {
    if [ ! -f .env ]; then
        print_warning ".env file not found, creating from .env.example"
        cp .env.example .env
        print_warning "Please edit .env file with your API keys before starting"
        print_info "Required keys: DEEPSEEK_API_KEY, DASHSCOPE_API_KEY"
        exit 1
    fi
}

# Check Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
}

# Docker compose command (handle both v1 and v2)
docker_compose() {
    if docker compose version &> /dev/null; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

# Start services
start_services() {
    print_info "Starting MalogBot services..."
    check_env
    docker_compose up -d
    print_success "Services started!"
    print_info "Application: http://localhost:${APP_PORT:-5000}"
    print_info "Database: localhost:${POSTGRES_PORT:-5433}"
    print_info "Redis: localhost:${REDIS_PORT:-6379}"
}

# Start with monitoring
start_with_monitoring() {
    print_info "Starting MalogBot services with monitoring..."
    check_env
    docker_compose --profile monitoring up -d
    print_success "Services started with monitoring!"
    print_info "Application: http://localhost:${APP_PORT:-5000}"
    print_info "Prometheus: http://localhost:${PROMETHEUS_PORT:-9090}"
    print_info "Grafana: http://localhost:${GRAFANA_PORT:-3000} (admin/admin123)"
}

# Stop services
stop_services() {
    print_info "Stopping MalogBot services..."
    docker_compose down
    print_success "Services stopped!"
}

# Restart services
restart_services() {
    stop_services
    start_services
}

# Build images
build_images() {
    print_info "Building Docker images..."
    docker_compose build --no-cache
    print_success "Images built!"
}

# Show logs
show_logs() {
    local service=$1
    if [ -z "$service" ]; then
        docker_compose logs -f
    else
        docker_compose logs -f "$service"
    fi
}

# Show status
show_status() {
    print_info "Service Status:"
    docker_compose ps
}

# Clean up
clean_up() {
    print_warning "This will remove all containers, volumes, and data!"
    read -p "Are you sure? (y/N): " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        print_info "Cleaning up..."
        docker_compose down -v --remove-orphans
        print_success "Cleanup complete!"
    else
        print_info "Cancelled."
    fi
}

# Initialize database
init_db() {
    print_info "Initializing database tables..."
    docker_compose exec malogbot python scripts/migrations/init_db.py
    print_info "Initializing agent knowledge tables..."
    docker_compose exec malogbot python scripts/migrations/init_agent_knowledge_tables.py
    print_info "Initializing knowledge base tables..."
    docker_compose exec malogbot python scripts/migrations/init_kb_tables.py
    print_info "Initializing MCP tables..."
    docker_compose exec malogbot python scripts/migrations/init_mcp_tables.py
    print_info "Initializing research tables..."
    docker_compose exec malogbot python scripts/migrations/init_research_tables.py
    print_info "Running incremental migrations..."
    docker_compose exec malogbot python scripts/migrations/migrate_context_tables.py
    docker_compose exec malogbot python scripts/migrations/migrate_memory_chunks.py
    docker_compose exec malogbot python scripts/migrations/migrate_add_onboarding.py
    print_success "Database initialized!"
}

# Show help
show_help() {
    echo "MalogBot v2.0 Deployment Script"
    echo ""
    echo "Usage: ./deploy.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start       - Start all services"
    echo "  stop        - Stop all services"
    echo "  restart     - Restart all services"
    echo "  build       - Build Docker images"
    echo "  logs [svc]  - Show logs (optional: specify service name)"
    echo "  status      - Show service status"
    echo "  monitor     - Start with monitoring (Prometheus + Grafana)"
    echo "  init-db     - Initialize database tables"
    echo "  clean       - Remove all containers and volumes"
    echo "  help        - Show this help message"
    echo ""
    echo "Services: malogbot, postgres, redis, prometheus, grafana"
}

# Main
check_docker

case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    build)
        build_images
        ;;
    logs)
        show_logs "$2"
        ;;
    status)
        show_status
        ;;
    monitor)
        start_with_monitoring
        ;;
    init-db)
        init_db
        ;;
    clean)
        clean_up
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
