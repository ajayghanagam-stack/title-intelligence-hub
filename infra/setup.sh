#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Title Intelligence Hub — AWS Infrastructure Setup
# One-time script to create all AWS resources for ECS Fargate deployment.
# ============================================================================

PREFIX="ti-hub"
REGION="us-east-1"
DB_NAME="title_intelligence_hub"
DB_USER="tihubadmin"
DB_INSTANCE_CLASS="db.t4g.small"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
info() { echo -e "${CYAN}[i]${NC} $*"; }

# ── Pre-flight checks ──────────────────────────────────────────────────────
command -v aws >/dev/null 2>&1 || { err "AWS CLI not found. Install: https://aws.amazon.com/cli/"; exit 1; }
command -v jq  >/dev/null 2>&1 || { err "jq not found. Install: brew install jq"; exit 1; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "AWS Account: $ACCOUNT_ID"
log "Region: $REGION"

# ── Auto-discover default VPC & subnets ─────────────────────────────────────
VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=isDefault,Values=true" \
  --query "Vpcs[0].VpcId" --output text)

if [ "$VPC_ID" = "None" ] || [ -z "$VPC_ID" ]; then
  err "No default VPC found in $REGION. Create one or update this script."
  exit 1
fi
log "VPC: $VPC_ID"

SUBNET_IDS=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "Subnets[*].SubnetId" --output text)
SUBNET_ARRAY=($SUBNET_IDS)

if [ ${#SUBNET_ARRAY[@]} -lt 2 ]; then
  err "Need at least 2 subnets for ALB. Found ${#SUBNET_ARRAY[@]}."
  exit 1
fi
log "Subnets: ${SUBNET_ARRAY[*]}"

# Comma and JSON formats
SUBNETS_CSV=$(IFS=,; echo "${SUBNET_ARRAY[*]}")
SUBNETS_JSON=$(printf '%s\n' "${SUBNET_ARRAY[@]}" | jq -R . | jq -s .)

# ── 1. ECR Repositories ────────────────────────────────────────────────────
create_ecr_repo() {
  local name="$1"
  if aws ecr describe-repositories --region "$REGION" --repository-names "$name" >/dev/null 2>&1; then
    info "ECR repo '$name' already exists"
  else
    aws ecr create-repository --region "$REGION" --repository-name "$name" \
      --image-scanning-configuration scanOnPush=true \
      --encryption-configuration encryptionType=AES256 >/dev/null
    log "Created ECR repo: $name"
  fi
}

create_ecr_repo "${PREFIX}-backend"
create_ecr_repo "${PREFIX}-frontend"

ECR_BACKEND="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${PREFIX}-backend"
ECR_FRONTEND="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${PREFIX}-frontend"

# ── 2. S3 Bucket ───────────────────────────────────────────────────────────
S3_BUCKET="${PREFIX}-storage-${ACCOUNT_ID}"

if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
  info "S3 bucket '$S3_BUCKET' already exists"
else
  aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" >/dev/null
  aws s3api put-public-access-block --bucket "$S3_BUCKET" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null
  aws s3api put-bucket-encryption --bucket "$S3_BUCKET" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
  log "Created S3 bucket: $S3_BUCKET (public access blocked, encrypted)"
fi

# ── 3. Security Groups ─────────────────────────────────────────────────────
create_sg() {
  local name="$1" desc="$2"
  local sg_id
  sg_id=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=$name" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" --output text 2>/dev/null)
  if [ "$sg_id" != "None" ] && [ -n "$sg_id" ]; then
    info "SG '$name' already exists: $sg_id"
    echo "$sg_id"
    return
  fi
  sg_id=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$name" --description "$desc" --vpc-id "$VPC_ID" \
    --query "GroupId" --output text)
  log "Created SG: $name ($sg_id)"
  echo "$sg_id"
}

SG_ALB=$(create_sg "${PREFIX}-alb-sg" "ALB - HTTP/HTTPS from internet")
SG_ECS=$(create_sg "${PREFIX}-ecs-sg" "ECS tasks - traffic from ALB only")
SG_RDS=$(create_sg "${PREFIX}-rds-sg" "RDS - traffic from ECS only")

# ALB SG rules: allow 80 and 443 from anywhere
add_ingress() {
  local sg="$1" port="$2" source="$3" desc="$4"
  aws ec2 authorize-security-group-ingress --region "$REGION" \
    --group-id "$sg" --protocol tcp --port "$port" --cidr "$source" \
    --tag-specifications "ResourceType=security-group-rule,Tags=[{Key=Description,Value=$desc}]" \
    2>/dev/null || true
}

add_ingress_sg() {
  local sg="$1" port="$2" source_sg="$3"
  aws ec2 authorize-security-group-ingress --region "$REGION" \
    --group-id "$sg" --protocol tcp --port "$port" \
    --source-group "$source_sg" 2>/dev/null || true
}

add_ingress "$SG_ALB" 80 "0.0.0.0/0" "HTTP"
add_ingress "$SG_ALB" 443 "0.0.0.0/0" "HTTPS"
add_ingress_sg "$SG_ECS" 8000 "$SG_ALB"   # backend
add_ingress_sg "$SG_ECS" 3000 "$SG_ALB"   # frontend
add_ingress_sg "$SG_RDS" 5432 "$SG_ECS"   # postgres from ECS

# ── 4. RDS PostgreSQL ──────────────────────────────────────────────────────
DB_INSTANCE_ID="${PREFIX}-db"
RDS_ENDPOINT=""

if aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" >/dev/null 2>&1; then
  info "RDS instance '$DB_INSTANCE_ID' already exists"
  RDS_ENDPOINT=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --query "DBInstances[0].Endpoint.Address" --output text)
else
  # Generate random password
  DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 32)

  # Create DB subnet group
  aws rds create-db-subnet-group --region "$REGION" \
    --db-subnet-group-name "${PREFIX}-db-subnet" \
    --db-subnet-group-description "Subnets for ${PREFIX} RDS" \
    --subnet-ids ${SUBNET_ARRAY[*]} 2>/dev/null || true

  aws rds create-db-instance --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --db-instance-class "$DB_INSTANCE_CLASS" \
    --engine postgres --engine-version "16" \
    --master-username "$DB_USER" \
    --master-user-password "$DB_PASSWORD" \
    --db-name "$DB_NAME" \
    --allocated-storage 20 \
    --storage-type gp3 \
    --storage-encrypted \
    --vpc-security-group-ids "$SG_RDS" \
    --db-subnet-group-name "${PREFIX}-db-subnet" \
    --no-publicly-accessible \
    --backup-retention-period 7 \
    --deletion-protection \
    --tags "Key=Project,Value=${PREFIX}" >/dev/null

  log "Created RDS instance: $DB_INSTANCE_ID (waiting for availability...)"
  aws rds wait db-instance-available --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID"
  log "RDS instance is available"

  RDS_ENDPOINT=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --query "DBInstances[0].Endpoint.Address" --output text)

  # Store DB password in SSM
  aws ssm put-parameter --region "$REGION" \
    --name "/${PREFIX}/db-password" \
    --type SecureString \
    --value "$DB_PASSWORD" \
    --overwrite >/dev/null
  log "Stored DB password in SSM: /${PREFIX}/db-password"
fi

log "RDS endpoint: $RDS_ENDPOINT"

# Construct DATABASE_URL and store in SSM
DB_PASSWORD_SSM=$(aws ssm get-parameter --region "$REGION" \
  --name "/${PREFIX}/db-password" --with-decryption \
  --query "Parameter.Value" --output text 2>/dev/null || echo "")

if [ -n "$DB_PASSWORD_SSM" ]; then
  DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD_SSM}@${RDS_ENDPOINT}:5432/${DB_NAME}"
  aws ssm put-parameter --region "$REGION" \
    --name "/${PREFIX}/database-url" \
    --type SecureString \
    --value "$DATABASE_URL" \
    --overwrite >/dev/null
  log "Stored DATABASE_URL in SSM: /${PREFIX}/database-url"
fi

# ── 5. JWT Secret ──────────────────────────────────────────────────────────
if aws ssm get-parameter --region "$REGION" --name "/${PREFIX}/jwt-secret" >/dev/null 2>&1; then
  info "JWT secret already exists in SSM"
else
  JWT_SECRET=$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 64)
  aws ssm put-parameter --region "$REGION" \
    --name "/${PREFIX}/jwt-secret" \
    --type SecureString \
    --value "$JWT_SECRET" \
    --overwrite >/dev/null
  log "Generated and stored JWT secret in SSM: /${PREFIX}/jwt-secret"
fi

# ── 6. CloudWatch Log Groups ───────────────────────────────────────────────
for svc in backend frontend; do
  LOG_GROUP="/ecs/${PREFIX}-${svc}"
  if aws logs describe-log-groups --region "$REGION" \
    --log-group-name-prefix "$LOG_GROUP" \
    --query "logGroups[?logGroupName=='$LOG_GROUP']" --output text | grep -q "$LOG_GROUP"; then
    info "Log group '$LOG_GROUP' already exists"
  else
    aws logs create-log-group --region "$REGION" --log-group-name "$LOG_GROUP" >/dev/null
    aws logs put-retention-policy --region "$REGION" \
      --log-group-name "$LOG_GROUP" --retention-in-days 30 >/dev/null
    log "Created log group: $LOG_GROUP (30-day retention)"
  fi
done

# ── 7. IAM Roles ───────────────────────────────────────────────────────────
TASK_EXEC_ROLE="${PREFIX}-task-execution-role"
TASK_ROLE="${PREFIX}-task-role"

# Task Execution Role (ECR pull + SSM read + CloudWatch logs)
if aws iam get-role --role-name "$TASK_EXEC_ROLE" >/dev/null 2>&1; then
  info "IAM role '$TASK_EXEC_ROLE' already exists"
else
  aws iam create-role --role-name "$TASK_EXEC_ROLE" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' >/dev/null
  aws iam attach-role-policy --role-name "$TASK_EXEC_ROLE" \
    --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"

  # SSM read access for secrets
  aws iam put-role-policy --role-name "$TASK_EXEC_ROLE" \
    --policy-name "${PREFIX}-ssm-read" \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": [\"ssm:GetParameters\", \"ssm:GetParameter\"],
        \"Resource\": \"arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter/${PREFIX}/*\"
      }]
    }"
  log "Created IAM role: $TASK_EXEC_ROLE"
fi

TASK_EXEC_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${TASK_EXEC_ROLE}"

# Task Role (S3 access for file storage)
if aws iam get-role --role-name "$TASK_ROLE" >/dev/null 2>&1; then
  info "IAM role '$TASK_ROLE' already exists"
else
  aws iam create-role --role-name "$TASK_ROLE" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' >/dev/null

  aws iam put-role-policy --role-name "$TASK_ROLE" \
    --policy-name "${PREFIX}-s3-access" \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": [\"s3:GetObject\", \"s3:PutObject\", \"s3:DeleteObject\", \"s3:ListBucket\"],
        \"Resource\": [
          \"arn:aws:s3:::${S3_BUCKET}\",
          \"arn:aws:s3:::${S3_BUCKET}/*\"
        ]
      }]
    }"
  log "Created IAM role: $TASK_ROLE"
fi

TASK_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${TASK_ROLE}"

# ── 8. ALB ─────────────────────────────────────────────────────────────────
ALB_NAME="${PREFIX}-alb"
ALB_ARN=""

if aws elbv2 describe-load-balancers --region "$REGION" --names "$ALB_NAME" >/dev/null 2>&1; then
  info "ALB '$ALB_NAME' already exists"
  ALB_ARN=$(aws elbv2 describe-load-balancers --region "$REGION" --names "$ALB_NAME" \
    --query "LoadBalancers[0].LoadBalancerArn" --output text)
else
  ALB_ARN=$(aws elbv2 create-load-balancer --region "$REGION" \
    --name "$ALB_NAME" \
    --subnets ${SUBNET_ARRAY[*]} \
    --security-groups "$SG_ALB" \
    --scheme internet-facing \
    --type application \
    --query "LoadBalancers[0].LoadBalancerArn" --output text)
  log "Created ALB: $ALB_NAME"
fi

ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" --names "$ALB_NAME" \
  --query "LoadBalancers[0].DNSName" --output text)

# Target Groups
create_tg() {
  local name="$1" port="$2" health_path="$3"
  local tg_arn
  tg_arn=$(aws elbv2 describe-target-groups --region "$REGION" --names "$name" \
    --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null)
  if [ "$tg_arn" != "None" ] && [ -n "$tg_arn" ]; then
    info "Target group '$name' already exists"
    echo "$tg_arn"
    return
  fi
  tg_arn=$(aws elbv2 create-target-group --region "$REGION" \
    --name "$name" \
    --protocol HTTP --port "$port" \
    --vpc-id "$VPC_ID" \
    --target-type ip \
    --health-check-protocol HTTP \
    --health-check-path "$health_path" \
    --health-check-interval-seconds 30 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --query "TargetGroups[0].TargetGroupArn" --output text)
  log "Created target group: $name"
  echo "$tg_arn"
}

TG_BACKEND=$(create_tg "${PREFIX}-backend-tg" 8000 "/api/v1/health")
TG_FRONTEND=$(create_tg "${PREFIX}-frontend-tg" 3000 "/")

# Listener — default to frontend, /api/* to backend
LISTENER_ARN=$(aws elbv2 describe-listeners --region "$REGION" \
  --load-balancer-arn "$ALB_ARN" \
  --query "Listeners[?Port==\`80\`].ListenerArn" --output text 2>/dev/null)

if [ "$LISTENER_ARN" = "None" ] || [ -z "$LISTENER_ARN" ]; then
  LISTENER_ARN=$(aws elbv2 create-listener --region "$REGION" \
    --load-balancer-arn "$ALB_ARN" \
    --protocol HTTP --port 80 \
    --default-actions "Type=forward,TargetGroupArn=$TG_FRONTEND" \
    --query "Listeners[0].ListenerArn" --output text)
  log "Created HTTP listener"
fi

# Add /api/* rule to route to backend
EXISTING_RULES=$(aws elbv2 describe-rules --region "$REGION" \
  --listener-arn "$LISTENER_ARN" \
  --query "Rules[?Conditions[?Field=='path-pattern' && Values[0]=='/api/*']].RuleArn" \
  --output text 2>/dev/null)

if [ "$EXISTING_RULES" = "None" ] || [ -z "$EXISTING_RULES" ]; then
  aws elbv2 create-rule --region "$REGION" \
    --listener-arn "$LISTENER_ARN" \
    --priority 10 \
    --conditions "Field=path-pattern,Values=/api/*" \
    --actions "Type=forward,TargetGroupArn=$TG_BACKEND" >/dev/null
  log "Created ALB rule: /api/* -> backend"
fi

# ── 9. ECS Cluster ─────────────────────────────────────────────────────────
CLUSTER_NAME="${PREFIX}-cluster"

if aws ecs describe-clusters --region "$REGION" --clusters "$CLUSTER_NAME" \
  --query "clusters[?status=='ACTIVE'].clusterName" --output text | grep -q "$CLUSTER_NAME"; then
  info "ECS cluster '$CLUSTER_NAME' already exists"
else
  aws ecs create-cluster --region "$REGION" --cluster-name "$CLUSTER_NAME" \
    --setting "name=containerInsights,value=enabled" >/dev/null
  log "Created ECS cluster: $CLUSTER_NAME"
fi

# ── 10. Register Task Definitions ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Backend task definition
BACKEND_TASK_DEF=$(cat "$SCRIPT_DIR/ecs-task-backend.json.tpl" \
  | sed "s|{{ACCOUNT_ID}}|${ACCOUNT_ID}|g" \
  | sed "s|{{REGION}}|${REGION}|g" \
  | sed "s|{{PREFIX}}|${PREFIX}|g" \
  | sed "s|{{ECR_BACKEND}}|${ECR_BACKEND}|g" \
  | sed "s|{{S3_BUCKET}}|${S3_BUCKET}|g" \
  | sed "s|{{TASK_EXEC_ROLE_ARN}}|${TASK_EXEC_ROLE_ARN}|g" \
  | sed "s|{{TASK_ROLE_ARN}}|${TASK_ROLE_ARN}|g" \
  | sed "s|{{ALB_DNS}}|${ALB_DNS}|g")

echo "$BACKEND_TASK_DEF" > /tmp/ti-hub-backend-task.json
aws ecs register-task-definition --region "$REGION" \
  --cli-input-json file:///tmp/ti-hub-backend-task.json >/dev/null
log "Registered backend task definition"

# Frontend task definition
FRONTEND_TASK_DEF=$(cat "$SCRIPT_DIR/ecs-task-frontend.json.tpl" \
  | sed "s|{{ACCOUNT_ID}}|${ACCOUNT_ID}|g" \
  | sed "s|{{REGION}}|${REGION}|g" \
  | sed "s|{{PREFIX}}|${PREFIX}|g" \
  | sed "s|{{ECR_FRONTEND}}|${ECR_FRONTEND}|g" \
  | sed "s|{{TASK_EXEC_ROLE_ARN}}|${TASK_EXEC_ROLE_ARN}|g" \
  | sed "s|{{TASK_ROLE_ARN}}|${TASK_ROLE_ARN}|g" \
  | sed "s|{{ALB_DNS}}|${ALB_DNS}|g")

echo "$FRONTEND_TASK_DEF" > /tmp/ti-hub-frontend-task.json
aws ecs register-task-definition --region "$REGION" \
  --cli-input-json file:///tmp/ti-hub-frontend-task.json >/dev/null
log "Registered frontend task definition"

# ── 11. ECS Services ──────────────────────────────────────────────────────
create_ecs_service() {
  local name="$1" task_family="$2" tg_arn="$3" container_name="$4" container_port="$5"

  if aws ecs describe-services --region "$REGION" --cluster "$CLUSTER_NAME" \
    --services "$name" --query "services[?status=='ACTIVE'].serviceName" \
    --output text 2>/dev/null | grep -q "$name"; then
    info "ECS service '$name' already exists"
    return
  fi

  aws ecs create-service --region "$REGION" \
    --cluster "$CLUSTER_NAME" \
    --service-name "$name" \
    --task-definition "$task_family" \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS_CSV}],securityGroups=[${SG_ECS}],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=${tg_arn},containerName=${container_name},containerPort=${container_port}" \
    --deployment-configuration "minimumHealthyPercent=100,maximumPercent=200" \
    --enable-execute-command >/dev/null
  log "Created ECS service: $name"
}

create_ecs_service "${PREFIX}-backend" "${PREFIX}-backend" "$TG_BACKEND" "backend" 8000
create_ecs_service "${PREFIX}-frontend" "${PREFIX}-frontend" "$TG_FRONTEND" "frontend" 3000

# ── 12. Auto-scaling (backend only) ────────────────────────────────────────
SCALING_TARGET="service/${CLUSTER_NAME}/${PREFIX}-backend"

# Register scalable target
aws application-autoscaling register-scalable-target --region "$REGION" \
  --service-namespace ecs \
  --resource-id "$SCALING_TARGET" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --min-capacity 1 --max-capacity 4 2>/dev/null || true

# CPU-based scaling
aws application-autoscaling put-scaling-policy --region "$REGION" \
  --service-namespace ecs \
  --resource-id "$SCALING_TARGET" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --policy-name "${PREFIX}-cpu-scaling" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 60.0,
    "PredefinedMetricSpecification": {"PredefinedMetricType": "ECSServiceAverageCPUUtilization"},
    "ScaleInCooldown": 300,
    "ScaleOutCooldown": 60
  }' >/dev/null 2>&1 || true

# Memory-based scaling
aws application-autoscaling put-scaling-policy --region "$REGION" \
  --service-namespace ecs \
  --resource-id "$SCALING_TARGET" \
  --scalable-dimension "ecs:service:DesiredCount" \
  --policy-name "${PREFIX}-memory-scaling" \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 70.0,
    "PredefinedMetricSpecification": {"PredefinedMetricType": "ECSServiceAverageMemoryUtilization"},
    "ScaleInCooldown": 300,
    "ScaleOutCooldown": 60
  }' >/dev/null 2>&1 || true

log "Configured auto-scaling: 1-4 tasks (CPU 60% / Memory 70%)"

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo -e "${GREEN}AWS Infrastructure Setup Complete${NC}"
echo "============================================================"
echo ""
echo "Resources created:"
echo "  ECR Backend:  $ECR_BACKEND"
echo "  ECR Frontend: $ECR_FRONTEND"
echo "  S3 Bucket:    $S3_BUCKET"
echo "  RDS Endpoint: $RDS_ENDPOINT"
echo "  ECS Cluster:  $CLUSTER_NAME"
echo "  ALB URL:      http://$ALB_DNS"
echo ""
echo "============================================================"
echo -e "${YELLOW}ACTION REQUIRED: Store your API keys in SSM${NC}"
echo "============================================================"
echo ""
echo "  aws ssm put-parameter --region $REGION \\"
echo "    --name /${PREFIX}/google-api-key \\"
echo "    --type SecureString \\"
echo "    --value '<your-google-api-key>'"
echo ""
echo "  aws ssm put-parameter --region $REGION \\"
echo "    --name /${PREFIX}/anthropic-api-key \\"
echo "    --type SecureString \\"
echo "    --value '<your-anthropic-api-key>'"
echo ""
echo "Then deploy with: ./infra/deploy.sh"
echo ""
