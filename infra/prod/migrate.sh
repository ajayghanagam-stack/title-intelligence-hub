#!/usr/bin/env bash
set -euo pipefail
export AWS_PAGER=""

# ============================================================================
# Title Intelligence Hub — Run Migrations & Seed
# Usage: ./infra/migrate.sh
# Runs alembic migrations then seeds admin users (idempotent).
# ============================================================================

PREFIX="ti-hub-prod"
REGION="us-east-1"
CLUSTER="${PREFIX}-cluster"
CMD="alembic upgrade head && python scripts/seed.py"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $*"; }
err() { echo -e "${RED}[x]${NC} $*" >&2; }

log "Running migrations + seed..."

# Get network config
SUBNETS=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=default-for-az,Values=true" \
  --query "Subnets[0:2].SubnetId" --output text | tr '\t' ',')
SG=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=${PREFIX}-ecs-sg" \
  --query "SecurityGroups[0].GroupId" --output text)

# Run as one-off ECS task
TASK_ARN=$(aws ecs run-task --region "$REGION" \
  --cluster "$CLUSTER" --task-definition "${PREFIX}-backend" --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SG}],assignPublicIp=ENABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"backend\",\"command\":[\"sh\",\"-c\",\"${CMD}\"]}]}" \
  --query "tasks[0].taskArn" --output text)

TASK_ID=$(echo "$TASK_ARN" | awk -F'/' '{print $NF}')
log "Task started: $TASK_ID"
log "Waiting for completion..."

aws ecs wait tasks-stopped --region "$REGION" --cluster "$CLUSTER" --tasks "$TASK_ARN"

EXIT_CODE=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query "tasks[0].containers[0].exitCode" --output text)

# Show logs
log "Task logs:"
aws logs get-log-events --region "$REGION" \
  --log-group-name "/ecs/${PREFIX}-backend" \
  --log-stream-name "ecs/backend/${TASK_ID}" \
  --query "events[*].message" --output text 2>/dev/null | tr '\t' '\n'

if [ "$EXIT_CODE" = "0" ]; then
  echo ""
  log "Done (exit code 0)"
else
  echo ""
  err "Failed (exit code $EXIT_CODE)"
  exit 1
fi
