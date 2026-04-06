#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Title Intelligence Hub — EC2 Deploy
# Usage: EC2_HOST=<ip> ./infra/stage/deploy.sh [backend|frontend|both]
# Deploys via SSH: pulls code, builds images on EC2, restarts containers.
# ============================================================================

PREFIX="ti-hub"
REGION="us-east-1"
TARGET="${1:-both}"
KEY_FILE="${EC2_KEY_FILE:-$HOME/.ssh/${PREFIX}-key.pem}"
EC2_USER="ec2-user"
APP_DIR="/opt/ti-hub"
COMPOSE_FILE="infra/stage/docker-compose.prod.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }

if [[ "$TARGET" != "backend" && "$TARGET" != "frontend" && "$TARGET" != "both" ]]; then
  err "Usage: EC2_HOST=<ip> $0 [backend|frontend|both]"
  exit 1
fi

if [ -z "${EC2_HOST:-}" ]; then
  err "EC2_HOST not set. Usage: EC2_HOST=<ip> $0 [backend|frontend|both]"
  exit 1
fi

if [ ! -f "$KEY_FILE" ]; then
  err "SSH key not found at $KEY_FILE. Set EC2_KEY_FILE or run setup-ec2.sh first."
  exit 1
fi

SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o ConnectTimeout=10"
SSH_CMD="ssh $SSH_OPTS ${EC2_USER}@${EC2_HOST}"

START_TIME=$(date +%s)

# ── 0. Ensure local and remote are in sync ────────────────────────────────
log "Checking local/remote sync..."
git fetch origin main --quiet
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse origin/main)
if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
  err "Local ($LOCAL_SHA) and remote ($REMOTE_SHA) are out of sync."
  err "Commit and push your changes before deploying: git push origin main"
  exit 1
fi
if [ -n "$(git status --porcelain -- ':!backend/test.db' ':!backend/storage/' ':!backend/eval_reports/' ':!docs/')" ]; then
  warn "You have uncommitted changes in tracked files:"
  git status --short -- ':!backend/test.db' ':!backend/storage/' ':!backend/eval_reports/' ':!docs/'
  err "Commit and push before deploying."
  exit 1
fi
log "Local and remote are in sync ($LOCAL_SHA)"

# ── 1. Fetch secrets from SSM and build .env.prod ─────────────────────────
log "Fetching secrets from SSM..."
DATABASE_URL=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/database-url" --with-decryption \
  --query "Parameter.Value" --output text)
JWT_SECRET=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/jwt-secret" --with-decryption \
  --query "Parameter.Value" --output text)
GOOGLE_API_KEY=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/google-api-key" --with-decryption \
  --query "Parameter.Value" --output text 2>/dev/null || echo "")
ANTHROPIC_API_KEY=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/anthropic-api-key" --with-decryption \
  --query "Parameter.Value" --output text 2>/dev/null || echo "")

# Vertex AI credentials (optional — if set, uses Vertex AI instead of AI Studio)
GCP_PROJECT=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/gcp-project-id" --with-decryption \
  --query "Parameter.Value" --output text 2>/dev/null || echo "")
GCP_SA_JSON=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/gcp-sa-json" --with-decryption \
  --query "Parameter.Value" --output text 2>/dev/null || echo "")
GCP_REGION="${GCP_REGION:-us-east1}"

S3_BUCKET="${PREFIX}-storage-$(aws sts get-caller-identity --query Account --output text)"

# Determine Vertex AI settings
VERTEX_AI_ENABLED="false"
VERTEX_ENV=""
if [ -n "$GCP_PROJECT" ] && [ -n "$GCP_SA_JSON" ]; then
  VERTEX_AI_ENABLED="true"
  VERTEX_ENV="VERTEX_AI=true
GOOGLE_CLOUD_PROJECT=${GCP_PROJECT}
GOOGLE_CLOUD_REGION=${GCP_REGION}
GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-sa-key.json"
  log "Vertex AI enabled (project: ${GCP_PROJECT}, region: ${GCP_REGION})"
else
  log "Using AI Studio (GOOGLE_API_KEY)"
fi

# Build .env.stage content
ENV_CONTENT="DATABASE_URL=${DATABASE_URL}
JWT_SECRET=${JWT_SECRET}
GOOGLE_API_KEY=${GOOGLE_API_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
${VERTEX_ENV}
STORAGE_PROVIDER=s3
S3_BUCKET=${S3_BUCKET}
S3_REGION=${REGION}
PIPELINE_BACKEND=background_tasks
AI_PROVIDER=gemini
NATIVE_PDF_CONCURRENCY=12
NATIVE_PDF_BATCH_SIZE=20
TRIAGE_CONCURRENCY=4
EXAMINER_MAX_OUTPUT_TOKENS=65536
CORS_ORIGINS=[\"https://platform.logikality.ai\"]
DEBUG=false"

log "Uploading .env.stage to EC2..."
echo "$ENV_CONTENT" | $SSH_CMD "cat > ${APP_DIR}/infra/stage/.env.stage"

# Upload GCP service account JSON (or create empty placeholder for docker-compose mount)
if [ "$VERTEX_AI_ENABLED" = "true" ]; then
  log "Uploading GCP service account credentials..."
  echo "$GCP_SA_JSON" | $SSH_CMD "cat > ${APP_DIR}/infra/stage/gcp-sa-key.json"
else
  $SSH_CMD "touch ${APP_DIR}/infra/stage/gcp-sa-key.json"
fi

# ── 2. Pull latest code ───────────────────────────────────────────────────
log "Pulling latest code on EC2..."
$SSH_CMD "cd ${APP_DIR} && git fetch origin main && git reset --hard origin/main"

# ── 3. Build and start containers ─────────────────────────────────────────
SERVICES=""
if [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; then
  SERVICES="$SERVICES backend"
fi
if [ "$TARGET" = "frontend" ] || [ "$TARGET" = "both" ]; then
  SERVICES="$SERVICES frontend"
fi
# Always include caddy when deploying both or any service
SERVICES="$SERVICES caddy"

log "Building and starting: $SERVICES"
$SSH_CMD "cd ${APP_DIR} && \
  NEXT_PUBLIC_API_URL=https://platform.logikality.ai \
  docker compose -f ${COMPOSE_FILE} up -d --build $SERVICES"

# ── 4. Run migrations (skip with --no-migrate) ──────────────────────────
if [ "${NO_MIGRATE:-}" != "1" ] && { [ "$TARGET" = "backend" ] || [ "$TARGET" = "both" ]; }; then
  log "Running database migrations..."
  $SSH_CMD "cd ${APP_DIR} && \
    docker compose -f ${COMPOSE_FILE} exec -T backend \
    alembic upgrade head"

  log "Running seed script..."
  $SSH_CMD "cd ${APP_DIR} && \
    docker compose -f ${COMPOSE_FILE} exec -T backend \
    python scripts/seed.py" || warn "Seed script returned non-zero (may be OK if already seeded)"
else
  log "Skipping migrations (NO_MIGRATE=1)"
fi

# ── 5. Health check ──────────────────────────────────────────────────────
log "Running health check..."
HEALTH_OK=false
for i in {1..10}; do
  if $SSH_CMD "curl -sf http://localhost/api/v1/health" >/dev/null 2>&1; then
    HEALTH_OK=true
    log "Health check passed"
    break
  fi
  if [ "$i" -lt 10 ]; then
    log "  Attempt $i/10 — waiting 5s..."
    sleep 5
  fi
done

if ! $HEALTH_OK; then
  warn "Health check did not pass after 10 attempts"
  warn "Check logs: ssh -i $KEY_FILE ${EC2_USER}@${EC2_HOST} 'cd ${APP_DIR} && docker compose -f ${COMPOSE_FILE} logs'"
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "============================================================"
if $HEALTH_OK; then
  echo -e "${GREEN}  READY — Deploy complete in ${ELAPSED}s${NC}"
else
  echo -e "${YELLOW}  DEPLOYED in ${ELAPSED}s (health check warning)${NC}"
fi
echo "============================================================"
echo "  URL: https://platform.logikality.ai"
echo "  API: https://platform.logikality.ai/api/v1/health"
echo "  SSH: ssh -i $KEY_FILE ${EC2_USER}@${EC2_HOST}"
echo ""
