#!/usr/bin/env bash
set -euo pipefail
export AWS_PAGER=""

# ============================================================================
# Title Intelligence Hub — Fast Deploy
# Usage: ./infra/deploy.sh [backend|frontend|both]
# ============================================================================

PREFIX="ti-hub-prod"
REGION="us-east-1"
CLUSTER="${PREFIX}-cluster"
TARGET="${1:-both}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

if [[ "$TARGET" != "backend" && "$TARGET" != "frontend" && "$TARGET" != "both" ]]; then
  err "Usage: $0 [backend|frontend|both]"
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

START_TIME=$(date +%s)

# ── 1. ECR Login ───────────────────────────────────────────────────────────
log "Logging into ECR..."
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY" 2>/dev/null

# ── 2. Build & Push ───────────────────────────────────────────────────────
deploy_service() {
  local service="$1"
  local image="${ECR_REGISTRY}/${PREFIX}-${service}"
  local dockerfile context

  if [ "$service" = "backend" ]; then
    dockerfile="$REPO_ROOT/backend/Dockerfile.prod"
    context="$REPO_ROOT/backend"
  else
    dockerfile="$REPO_ROOT/frontend/Dockerfile.prod"
    context="$REPO_ROOT/frontend"
  fi

  log "Building ${service} image..."

  # Get ALB URL for frontend build arg
  local build_args=""
  if [ "$service" = "frontend" ]; then
    ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" --names "${PREFIX}-alb" \
      --query "LoadBalancers[0].DNSName" --output text 2>/dev/null || echo "")
    if [ -n "$ALB_DNS" ] && [ "$ALB_DNS" != "None" ]; then
      build_args="--build-arg NEXT_PUBLIC_API_URL=http://${ALB_DNS}"
    fi
  fi

  docker build --platform linux/amd64 \
    -f "$dockerfile" \
    $build_args \
    -t "${image}:latest" \
    "$context"

  log "Pushing ${service} image..."
  docker push "${image}:latest"

  log "Forcing new ${service} deployment..."
  aws ecs update-service --region "$REGION" \
    --cluster "$CLUSTER" \
    --service "${PREFIX}-${service}" \
    --force-new-deployment >/dev/null

  log "${service} deployment initiated"
}

if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  deploy_service "backend"
fi

if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "both" ]; then
  deploy_service "frontend"
fi

# ── 3. Run Migrations (backend deploys only) ─────────────────────────────
if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  log "Running database migrations..."
  SUBNETS=$(aws ec2 describe-subnets --region "$REGION" \
    --filters "Name=default-for-az,Values=true" \
    --query "Subnets[0:2].SubnetId" --output text | tr '\t' ',')
  SG=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=${PREFIX}-ecs-sg" \
    --query "SecurityGroups[0].GroupId" --output text)
  MIGRATE_TASK=$(aws ecs run-task --region "$REGION" \
    --cluster "$CLUSTER" --task-definition "${PREFIX}-backend" --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=ENABLED}" \
    --overrides '{"containerOverrides":[{"name":"backend","command":["sh","-c","alembic upgrade head"]}]}' \
    --query "tasks[0].taskArn" --output text)
  aws ecs wait tasks-stopped --region "$REGION" --cluster "$CLUSTER" --tasks "$MIGRATE_TASK"
  EXIT_CODE=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$MIGRATE_TASK" \
    --query "tasks[0].containers[0].exitCode" --output text)
  if [ "$EXIT_CODE" = "0" ]; then
    log "Migrations complete"
  else
    err "Migration failed (exit code $EXIT_CODE). Check CloudWatch logs."
    exit 1
  fi
fi

# ── 4. Wait for Stability ─────────────────────────────────────────────────
log "Waiting for service(s) to stabilize..."

SERVICES_TO_WAIT=()
if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  SERVICES_TO_WAIT+=("${PREFIX}-backend")
fi
if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "both" ]; then
  SERVICES_TO_WAIT+=("${PREFIX}-frontend")
fi

aws ecs wait services-stable --region "$REGION" \
  --cluster "$CLUSTER" \
  --services "${SERVICES_TO_WAIT[@]}"

# ── 4. Health Check ───────────────────────────────────────────────────────
ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" --names "${PREFIX}-alb" \
  --query "LoadBalancers[0].DNSName" --output text)

if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  log "Health check: backend..."
  for i in {1..5}; do
    if curl -sf "http://${ALB_DNS}/api/v1/health" >/dev/null 2>&1; then
      log "Backend health check passed"
      break
    fi
    if [ "$i" -eq 5 ]; then
      warn "Backend health check did not pass after 5 attempts"
    fi
    sleep 3
  done
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "============================================================"
echo -e "${GREEN}Deploy complete in ${ELAPSED}s${NC}"
echo "============================================================"
echo "  URL: http://${ALB_DNS}"
echo "  API: http://${ALB_DNS}/api/v1/health"
echo ""
