#!/bin/bash
# =============================================================================
# DEPLOY SCRIPT - Title Intelligence Hub
# =============================================================================
# Usage:
#   ./deploy.sh          - Deploy both backend and frontend
#   ./deploy.sh backend  - Deploy backend only
#   ./deploy.sh frontend - Deploy frontend only
#   ./deploy.sh --help   - Show help
# =============================================================================

set -e

# Configuration
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="628913890897"
APP_NAME="title-intelligence"
ALB_DNS="title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com"
ECR_URL="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_header() {
    echo ""
    echo -e "${BLUE}=============================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}=============================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Show help
show_help() {
    echo ""
    echo "Title Intelligence Hub - Deploy Script"
    echo ""
    echo "Usage:"
    echo "  ./deploy.sh              Deploy both backend and frontend"
    echo "  ./deploy.sh backend      Deploy backend only"
    echo "  ./deploy.sh frontend     Deploy frontend only"
    echo "  ./deploy.sh --help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh              # Full deployment"
    echo "  ./deploy.sh backend      # After fixing a backend bug"
    echo "  ./deploy.sh frontend     # After UI changes"
    echo ""
}

# Check prerequisites
check_prerequisites() {
    print_header "Checking Prerequisites"
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    print_success "Docker is installed"
    
    # Check if Docker is running
    if ! docker info &> /dev/null; then
        print_error "Docker is not running. Please start Docker."
        exit 1
    fi
    print_success "Docker is running"
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    print_success "AWS CLI is installed"
    
    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS credentials not configured. Run 'aws configure' first."
        exit 1
    fi
    print_success "AWS credentials configured"
}

# Pull latest code
pull_latest_code() {
    print_header "Pulling Latest Code"
    
    if [ -d ".git" ]; then
        git pull origin main
        print_success "Code updated from GitHub"
    else
        print_warning "Not a git repository. Skipping git pull."
    fi
}

# Login to ECR
login_ecr() {
    print_header "Logging into AWS ECR"
    
    aws ecr get-login-password --region ${AWS_REGION} | \
        docker login --username AWS --password-stdin ${ECR_URL}
    
    print_success "Logged into ECR"
}

# Build and push backend
deploy_backend() {
    print_header "Deploying Backend"
    
    cd backend
    
    print_info "Building backend image..."
    docker build -t ${ECR_URL}/${APP_NAME}/backend:latest .
    
    print_info "Pushing backend image to ECR..."
    docker push ${ECR_URL}/${APP_NAME}/backend:latest
    
    cd ..
    
    print_success "Backend deployed to ECR"
}

# Build and push frontend
deploy_frontend() {
    print_header "Deploying Frontend"
    
    cd frontend
    
    print_info "Building frontend image..."
    docker build \
        --build-arg NEXT_PUBLIC_API_URL=http://${ALB_DNS} \
        -t ${ECR_URL}/${APP_NAME}/frontend:latest .
    
    print_info "Pushing frontend image to ECR..."
    docker push ${ECR_URL}/${APP_NAME}/frontend:latest
    
    cd ..
    
    print_success "Frontend deployed to ECR"
}

# Restart ECS service
restart_ecs_service() {
    print_header "Restarting ECS Service"
    
    print_info "Forcing new deployment..."
    aws ecs update-service \
        --cluster ${APP_NAME}-cluster \
        --service ${APP_NAME}-service \
        --force-new-deployment \
        --region ${AWS_REGION} \
        > /dev/null
    
    print_success "ECS service restart initiated"
    print_info "New containers will be live in 2-3 minutes"
}

# Show deployment summary
show_summary() {
    print_header "Deployment Complete!"
    
    echo ""
    echo "Your application is available at:"
    echo -e "${GREEN}  http://${ALB_DNS}${NC}"
    echo ""
    echo "To check deployment status:"
    echo "  aws ecs describe-services --cluster ${APP_NAME}-cluster --services ${APP_NAME}-service --query 'services[0].deployments'"
    echo ""
    echo "To view logs:"
    echo "  aws logs tail /ecs/${APP_NAME} --follow"
    echo ""
}

# Main execution
main() {
    DEPLOY_TARGET="${1:-all}"
    
    case "$DEPLOY_TARGET" in
        --help|-h)
            show_help
            exit 0
            ;;
        backend)
            print_header "BACKEND DEPLOYMENT"
            check_prerequisites
            pull_latest_code
            login_ecr
            deploy_backend
            restart_ecs_service
            show_summary
            ;;
        frontend)
            print_header "FRONTEND DEPLOYMENT"
            check_prerequisites
            pull_latest_code
            login_ecr
            deploy_frontend
            restart_ecs_service
            show_summary
            ;;
        all|"")
            print_header "FULL DEPLOYMENT"
            check_prerequisites
            pull_latest_code
            login_ecr
            deploy_backend
            deploy_frontend
            restart_ecs_service
            show_summary
            ;;
        *)
            print_error "Unknown option: $DEPLOY_TARGET"
            show_help
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
