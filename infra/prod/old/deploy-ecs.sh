#!/usr/bin/env bash
set -euo pipefail
export AWS_PAGER=""

# ============================================================================
# Title Intelligence Hub — Fast Deploy (Production)
# Usage: ./infra/prod/deploy.sh [backend|frontend|both]
# ============================================================================

PREFIX="ti-hub-prod"
REGION="us-east-1"
CLUSTER="${PREFIX}-cluster"
TARGET="${1:-both}"
MAX_WAIT=300  # 5 minute timeout for service stability

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
elapsed() { echo $(( $(date +%s) - START_TIME ))s; }

if [[ "$TARGET" != "backend" && "$TARGET" != "frontend" && "$TARGET" != "both" ]]; then
  err "Usage: $0 [backend|frontend|both]"
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

START_TIME=$(date +%s)

# ── 1. ECR Login ───────────────────────────────────────────────────────────
log "Logging into ECR... [$(elapsed)]"
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

  log "Building ${service} image... [$(elapsed)]"

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

  log "Build complete. Pushing ${service} image... [$(elapsed)]"
  docker push "${image}:latest"

  log "Forcing new ${service} deployment... [$(elapsed)]"
  aws ecs update-service --region "$REGION" \
    --cluster "$CLUSTER" \
    --service "${PREFIX}-${service}" \
    --force-new-deployment >/dev/null

  log "${service} deployed to ECS [$(elapsed)]"
}

if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  deploy_service "backend"
fi

if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "both" ]; then
  deploy_service "frontend"
fi

# ── 3. Wait for Stability (with progress) ────────────────────────────────
log "Waiting for service(s) to stabilize (timeout ${MAX_WAIT}s)... [$(elapsed)]"

SERVICES_TO_WAIT=()
if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  SERVICES_TO_WAIT+=("${PREFIX}-backend")
fi
if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "both" ]; then
  SERVICES_TO_WAIT+=("${PREFIX}-frontend")
fi

WAIT_START=$(date +%s)
STABLE=false

while true; do
  WAITED=$(( $(date +%s) - WAIT_START ))

  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    warn "Timed out after ${MAX_WAIT}s waiting for stability"
    break
  fi

  # Check each service
  ALL_STABLE=true
  for svc in "${SERVICES_TO_WAIT[@]}"; do
    RUNNING=$(aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" \
      --services "$svc" --query "services[0].runningCount" --output text 2>/dev/null || echo "0")
    DESIRED=$(aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" \
      --services "$svc" --query "services[0].desiredCount" --output text 2>/dev/null || echo "0")
    DEPLOYMENTS=$(aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" \
      --services "$svc" --query "length(services[0].deployments)" --output text 2>/dev/null || echo "0")

    if [ "$RUNNING" != "$DESIRED" ] || [ "$DEPLOYMENTS" != "1" ]; then
      ALL_STABLE=false
      log "  ${svc}: ${RUNNING}/${DESIRED} running, ${DEPLOYMENTS} deployment(s) — waited ${WAITED}s"
    fi
  done

  if [ "$ALL_STABLE" = true ]; then
    STABLE=true
    log "Services stabilized [$(elapsed)]"
    break
  fi

  sleep 15
done

# ── 4. Health Check ───────────────────────────────────────────────────────
ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" --names "${PREFIX}-alb" \
  --query "LoadBalancers[0].DNSName" --output text)

HEALTH_OK=true
if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  log "Health check: backend... [$(elapsed)]"
  for i in {1..5}; do
    if curl -sf "http://${ALB_DNS}/api/v1/health" >/dev/null 2>&1; then
      log "Backend health check passed"
      break
    fi
    if [ "$i" -eq 5 ]; then
      warn "Backend health check did not pass after 5 attempts"
      HEALTH_OK=false
    fi
    sleep 3
  done
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "============================================================"
if [ "$STABLE" = true ] && [ "$HEALTH_OK" = true ]; then
  echo -e "${GREEN}  READY — Deploy complete in ${ELAPSED}s${NC}"
elif [ "$STABLE" = true ]; then
  echo -e "${YELLOW}  DEPLOYED in ${ELAPSED}s (health check warning)${NC}"
else
  echo -e "${RED}  DEPLOYED in ${ELAPSED}s (services may still be starting)${NC}"
fi
echo "============================================================"
echo "  URL: http://${ALB_DNS}"
echo "  API: http://${ALB_DNS}/api/v1/health"
echo ""
echo -e "${GREEN}  You can test now.${NC}"
echo ""
