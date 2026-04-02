#!/usr/bin/env bash
set -euo pipefail
export AWS_PAGER=""

# ============================================================================
# Title Intelligence Hub — AWS Infrastructure Teardown
# Removes all AWS resources created by setup.sh. Prompts before each step.
# ============================================================================

PREFIX="ti-hub-prod"
REGION="us-east-1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo ""
echo -e "${RED}============================================================${NC}"
echo -e "${RED}  WARNING: This will DELETE all AWS resources for ${PREFIX}${NC}"
echo -e "${RED}============================================================${NC}"
echo ""
echo "  Account:  $ACCOUNT_ID"
echo "  Region:   $REGION"
echo ""
read -p "Type 'destroy' to confirm: " CONFIRM

if [ "$CONFIRM" != "destroy" ]; then
  echo "Aborted."
  exit 0
fi

# ── 1. Delete ECS Services ────────────────────────────────────────────────
CLUSTER="${PREFIX}-cluster"

for svc in "${PREFIX}-backend" "${PREFIX}-frontend"; do
  if aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" \
    --services "$svc" --query "services[?status=='ACTIVE']" --output text 2>/dev/null | grep -q .; then
    log "Scaling down and deleting ECS service: $svc"
    aws ecs update-service --region "$REGION" --cluster "$CLUSTER" \
      --service "$svc" --desired-count 0 >/dev/null 2>&1 || true
    aws ecs delete-service --region "$REGION" --cluster "$CLUSTER" \
      --service "$svc" --force >/dev/null 2>&1 || true
  fi
done

# Wait for tasks to drain
log "Waiting for tasks to drain..."
sleep 15

# ── 2. Deregister Task Definitions ───────────────────────────────────────
for family in "${PREFIX}-backend" "${PREFIX}-frontend"; do
  REVISIONS=$(aws ecs list-task-definitions --region "$REGION" \
    --family-prefix "$family" --query "taskDefinitionArns" --output text 2>/dev/null)
  for rev in $REVISIONS; do
    aws ecs deregister-task-definition --region "$REGION" \
      --task-definition "$rev" >/dev/null 2>&1 || true
  done
  log "Deregistered task definitions: $family"
done

# ── 3. Remove Auto-scaling ───────────────────────────────────────────────
SCALING_TARGET="service/${CLUSTER}/${PREFIX}-backend"
aws application-autoscaling deregister-scalable-target --region "$REGION" \
  --service-namespace ecs \
  --resource-id "$SCALING_TARGET" \
  --scalable-dimension "ecs:service:DesiredCount" 2>/dev/null || true
log "Removed auto-scaling"

# ── 4. Delete ALB, Listeners, Target Groups ──────────────────────────────
ALB_ARN=$(aws elbv2 describe-load-balancers --region "$REGION" --names "${PREFIX}-alb" \
  --query "LoadBalancers[0].LoadBalancerArn" --output text 2>/dev/null || echo "None")

if [ "$ALB_ARN" != "None" ] && [ -n "$ALB_ARN" ]; then
  # Delete listeners first
  LISTENERS=$(aws elbv2 describe-listeners --region "$REGION" \
    --load-balancer-arn "$ALB_ARN" \
    --query "Listeners[*].ListenerArn" --output text 2>/dev/null)
  for l in $LISTENERS; do
    aws elbv2 delete-listener --region "$REGION" --listener-arn "$l" 2>/dev/null || true
  done

  aws elbv2 delete-load-balancer --region "$REGION" --load-balancer-arn "$ALB_ARN" 2>/dev/null || true
  log "Deleted ALB: ${PREFIX}-alb"

  # Wait for ALB to finish deleting before removing target groups
  sleep 10
fi

for tg_name in "${PREFIX}-backend-tg" "${PREFIX}-frontend-tg"; do
  TG_ARN=$(aws elbv2 describe-target-groups --region "$REGION" --names "$tg_name" \
    --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null || echo "None")
  if [ "$TG_ARN" != "None" ] && [ -n "$TG_ARN" ]; then
    aws elbv2 delete-target-group --region "$REGION" --target-group-arn "$TG_ARN" 2>/dev/null || true
    log "Deleted target group: $tg_name"
  fi
done

# ── 5. Delete ECS Cluster ────────────────────────────────────────────────
aws ecs delete-cluster --region "$REGION" --cluster "$CLUSTER" 2>/dev/null || true
log "Deleted ECS cluster: $CLUSTER"

# ── 6. Delete RDS (requires removing deletion protection first) ──────────
DB_INSTANCE_ID="${PREFIX}-db"
if aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" >/dev/null 2>&1; then
  echo ""
  read -p "Delete RDS instance '$DB_INSTANCE_ID'? This destroys all data. (yes/no): " CONFIRM_RDS
  if [ "$CONFIRM_RDS" = "yes" ]; then
    aws rds modify-db-instance --region "$REGION" \
      --db-instance-identifier "$DB_INSTANCE_ID" \
      --no-deletion-protection --apply-immediately >/dev/null
    sleep 5
    aws rds delete-db-instance --region "$REGION" \
      --db-instance-identifier "$DB_INSTANCE_ID" \
      --skip-final-snapshot >/dev/null
    log "Deleting RDS instance (this takes several minutes)..."
  else
    warn "Skipped RDS deletion"
  fi
fi

# Delete DB subnet group
aws rds delete-db-subnet-group --region "$REGION" \
  --db-subnet-group-name "${PREFIX}-db-subnet" 2>/dev/null || true

# ── 7. Delete S3 Bucket ─────────────────────────────────────────────────
S3_BUCKET="${PREFIX}-storage-${ACCOUNT_ID}"
if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
  echo ""
  read -p "Delete S3 bucket '$S3_BUCKET' and ALL its contents? (yes/no): " CONFIRM_S3
  if [ "$CONFIRM_S3" = "yes" ]; then
    aws s3 rb "s3://${S3_BUCKET}" --force 2>/dev/null || true
    log "Deleted S3 bucket: $S3_BUCKET"
  else
    warn "Skipped S3 bucket deletion"
  fi
fi

# ── 8. Delete ECR Repositories ──────────────────────────────────────────
for repo in "${PREFIX}-backend" "${PREFIX}-frontend"; do
  if aws ecr describe-repositories --region "$REGION" --repository-names "$repo" >/dev/null 2>&1; then
    aws ecr delete-repository --region "$REGION" --repository-name "$repo" --force >/dev/null
    log "Deleted ECR repo: $repo"
  fi
done

# ── 9. Delete IAM Roles ────────────────────────────────────────────────
delete_role() {
  local role="$1"
  if ! aws iam get-role --role-name "$role" >/dev/null 2>&1; then
    return
  fi

  # Detach managed policies
  POLICIES=$(aws iam list-attached-role-policies --role-name "$role" \
    --query "AttachedPolicies[*].PolicyArn" --output text 2>/dev/null)
  for p in $POLICIES; do
    aws iam detach-role-policy --role-name "$role" --policy-arn "$p" 2>/dev/null || true
  done

  # Delete inline policies
  INLINE=$(aws iam list-role-policies --role-name "$role" \
    --query "PolicyNames" --output text 2>/dev/null)
  for p in $INLINE; do
    aws iam delete-role-policy --role-name "$role" --policy-name "$p" 2>/dev/null || true
  done

  aws iam delete-role --role-name "$role" 2>/dev/null || true
  log "Deleted IAM role: $role"
}

delete_role "${PREFIX}-task-execution-role"
delete_role "${PREFIX}-task-role"

# ── 10. Delete Security Groups ──────────────────────────────────────────
VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=isDefault,Values=true" \
  --query "Vpcs[0].VpcId" --output text 2>/dev/null)

for sg_name in "${PREFIX}-ecs-sg" "${PREFIX}-rds-sg" "${PREFIX}-alb-sg"; do
  SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=$sg_name" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" --output text 2>/dev/null)
  if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
    aws ec2 delete-security-group --region "$REGION" --group-id "$SG_ID" 2>/dev/null || true
    log "Deleted security group: $sg_name"
  fi
done

# ── 11. Delete CloudWatch Log Groups ────────────────────────────────────
for svc in backend frontend; do
  LOG_GROUP="/ecs/${PREFIX}-${svc}"
  aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null || true
  log "Deleted log group: $LOG_GROUP"
done

# ── 12. Delete SSM Parameters ──────────────────────────────────────────
for param in "/${PREFIX}/db-password" "/${PREFIX}/database-url" "/${PREFIX}/jwt-secret" \
  "/${PREFIX}/google-api-key" "/${PREFIX}/anthropic-api-key"; do
  aws ssm delete-parameter --region "$REGION" --name "$param" 2>/dev/null || true
done
log "Deleted SSM parameters"

echo ""
echo -e "${GREEN}Teardown complete.${NC}"
echo ""
echo "Note: RDS deletion takes several minutes to complete in the background."
echo "Verify in the AWS Console that all resources are cleaned up."
echo ""
