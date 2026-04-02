#!/usr/bin/env bash
set -euo pipefail
export AWS_PAGER=""

# ============================================================================
# Title Intelligence Hub — Full Infrastructure Setup (Production)
# Creates all AWS resources: S3, RDS, EC2, security groups, IAM, SSM secrets.
# Idempotent — safe to re-run (skips existing resources).
# ============================================================================

PREFIX="ti-hub-prod"
REGION="us-east-1"
INSTANCE_TYPE="t4g.xlarge"   # 4 vCPU, 16 GB RAM (ARM64)
KEY_NAME="${PREFIX}-key"
KEY_FILE="$HOME/.ssh/${KEY_NAME}.pem"
VOLUME_SIZE=30               # GB, gp3
DB_NAME="title_intelligence_hub"
DB_USER="tihubadmin"
DB_INSTANCE_CLASS="db.t4g.large"

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
log "Prefix: $PREFIX"

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
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=default-for-az,Values=true" \
  --query "Subnets[*].SubnetId" --output text)
SUBNET_ARRAY=($SUBNET_IDS)

if [ ${#SUBNET_ARRAY[@]} -lt 2 ]; then
  err "Need at least 2 subnets for RDS. Found ${#SUBNET_ARRAY[@]}."
  exit 1
fi
log "Subnets: ${SUBNET_ARRAY[*]}"

# ── 1. S3 Bucket ──────────────────────────────────────────────────────────
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

# ── 2. Security Groups ───────────────────────────────────────────────────
create_sg() {
  local name="$1" desc="$2"
  local sg_id
  sg_id=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=$name" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" --output text 2>/dev/null)
  if [ "$sg_id" != "None" ] && [ -n "$sg_id" ]; then
    info "SG '$name' already exists: $sg_id" >&2
    echo "$sg_id"
    return
  fi
  sg_id=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$name" --description "$desc" --vpc-id "$VPC_ID" \
    --query "GroupId" --output text)
  log "Created SG: $name ($sg_id)" >&2
  echo "$sg_id"
}

SG_EC2=$(create_sg "${PREFIX}-ec2-sg" "EC2 instance - SSH, HTTP, HTTPS")
SG_RDS=$(create_sg "${PREFIX}-rds-sg" "RDS - traffic from EC2 only")

# EC2 SG rules
aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_EC2" --protocol tcp --port 22 --cidr "0.0.0.0/0" 2>/dev/null || true
aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_EC2" --protocol tcp --port 80 --cidr "0.0.0.0/0" 2>/dev/null || true
aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_EC2" --protocol tcp --port 443 --cidr "0.0.0.0/0" 2>/dev/null || true

# RDS SG rule: allow EC2 → PostgreSQL
aws ec2 authorize-security-group-ingress --region "$REGION" \
  --group-id "$SG_RDS" --protocol tcp --port 5432 \
  --source-group "$SG_EC2" 2>/dev/null || true

log "Security group rules configured"

# ── 3. RDS PostgreSQL ─────────────────────────────────────────────────────
DB_INSTANCE_ID="${PREFIX}-db"
RDS_ENDPOINT=""

if aws rds describe-db-instances --region "$REGION" \
  --db-instance-identifier "$DB_INSTANCE_ID" >/dev/null 2>&1; then
  info "RDS instance '$DB_INSTANCE_ID' already exists"
  RDS_ENDPOINT=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --query "DBInstances[0].Endpoint.Address" --output text)
else
  DB_PASSWORD=$(openssl rand -hex 16)

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

  # Store secrets in SSM
  aws ssm put-parameter --region "$REGION" \
    --name "/${PREFIX}/db-password" \
    --type SecureString \
    --value "$DB_PASSWORD" \
    --overwrite >/dev/null
  log "Stored DB password in SSM"

  DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${RDS_ENDPOINT}:5432/${DB_NAME}"
  aws ssm put-parameter --region "$REGION" \
    --name "/${PREFIX}/database-url" \
    --type SecureString \
    --value "$DATABASE_URL" \
    --overwrite >/dev/null
  log "Stored DATABASE_URL in SSM"
fi

log "RDS endpoint: $RDS_ENDPOINT"

# Ensure DATABASE_URL is in SSM (even if RDS already existed)
if ! aws ssm get-parameter --region "$REGION" --name "/${PREFIX}/database-url" >/dev/null 2>&1; then
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
    log "Reconstructed and stored DATABASE_URL in SSM"
  else
    warn "Cannot reconstruct DATABASE_URL — DB password not in SSM. You'll need to reset the RDS password."
  fi
fi

# ── 4. JWT Secret ─────────────────────────────────────────────────────────
if aws ssm get-parameter --region "$REGION" --name "/${PREFIX}/jwt-secret" >/dev/null 2>&1; then
  info "JWT secret already exists in SSM"
else
  JWT_SECRET=$(openssl rand -hex 32)
  aws ssm put-parameter --region "$REGION" \
    --name "/${PREFIX}/jwt-secret" \
    --type SecureString \
    --value "$JWT_SECRET" \
    --overwrite >/dev/null
  log "Generated and stored JWT secret in SSM"
fi

# ── 5. SSH Key Pair ───────────────────────────────────────────────────────
if aws ec2 describe-key-pairs --region "$REGION" --key-names "$KEY_NAME" >/dev/null 2>&1; then
  info "Key pair '$KEY_NAME' already exists"
  if [ ! -f "$KEY_FILE" ]; then
    warn "Key file not found at $KEY_FILE — you may need to use an existing copy"
  fi
else
  log "Creating SSH key pair: $KEY_NAME"
  aws ec2 create-key-pair --region "$REGION" --key-name "$KEY_NAME" \
    --key-type ed25519 \
    --query "KeyMaterial" --output text > "$KEY_FILE"
  chmod 400 "$KEY_FILE"
  log "Saved private key to $KEY_FILE"
fi

# ── 6. IAM Instance Profile ──────────────────────────────────────────────
EC2_ROLE="${PREFIX}-ec2-role"
INSTANCE_PROFILE="${PREFIX}-ec2-profile"

if aws iam get-role --role-name "$EC2_ROLE" >/dev/null 2>&1; then
  info "IAM role '$EC2_ROLE' already exists"
else
  aws iam create-role --role-name "$EC2_ROLE" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "ec2.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' >/dev/null

  aws iam put-role-policy --role-name "$EC2_ROLE" \
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

  aws iam put-role-policy --role-name "$EC2_ROLE" \
    --policy-name "${PREFIX}-ssm-read" \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": [\"ssm:GetParameters\", \"ssm:GetParameter\"],
        \"Resource\": \"arn:aws:ssm:${REGION}:${ACCOUNT_ID}:parameter/${PREFIX}/*\"
      }]
    }"

  log "Created IAM role: $EC2_ROLE (S3 + SSM access)"
fi

if aws iam get-instance-profile --instance-profile-name "$INSTANCE_PROFILE" >/dev/null 2>&1; then
  info "Instance profile '$INSTANCE_PROFILE' already exists"
else
  aws iam create-instance-profile --instance-profile-name "$INSTANCE_PROFILE" >/dev/null
  aws iam add-role-to-instance-profile \
    --instance-profile-name "$INSTANCE_PROFILE" \
    --role-name "$EC2_ROLE"
  log "Created instance profile: $INSTANCE_PROFILE"
  log "Waiting for IAM propagation (15s)..."
  sleep 15
fi

# ── 7. Find latest Amazon Linux 2023 ARM64 AMI ───────────────────────────
AMI_ID=$(aws ec2 describe-images --region "$REGION" \
  --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023*-arm64" \
            "Name=state,Values=available" \
            "Name=architecture,Values=arm64" \
  --query "sort_by(Images, &CreationDate)[-1].ImageId" --output text)

if [ -z "$AMI_ID" ] || [ "$AMI_ID" = "None" ]; then
  err "Could not find Amazon Linux 2023 ARM64 AMI"
  exit 1
fi
log "AMI: $AMI_ID (Amazon Linux 2023 ARM64)"

# ── 8. User Data (cloud-init) ────────────────────────────────────────────
USER_DATA=$(cat <<'USERDATA'
#!/bin/bash
set -e

# Install Docker
dnf update -y
dnf install -y docker git
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

# Install Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep '"tag_name"' | head -1 | cut -d'"' -f4)
curl -SL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Clone repository
git clone git@github.com:ajayghanagam-stack/title-intelligence-hub.git /opt/ti-hub
chown -R ec2-user:ec2-user /opt/ti-hub

echo "Cloud-init complete" > /var/log/cloud-init-done
USERDATA
)

# ── 9. Launch EC2 Instance ────────────────────────────────────────────────
INSTANCE_NAME="${PREFIX}-server"

EXISTING_INSTANCE=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=$INSTANCE_NAME" \
            "Name=instance-state-name,Values=running,pending,stopped" \
  --query "Reservations[0].Instances[0].InstanceId" --output text 2>/dev/null)

if [ "$EXISTING_INSTANCE" != "None" ] && [ -n "$EXISTING_INSTANCE" ]; then
  info "EC2 instance '$INSTANCE_NAME' already exists: $EXISTING_INSTANCE"
  INSTANCE_ID="$EXISTING_INSTANCE"
else
  INSTANCE_ID=$(aws ec2 run-instances --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_EC2" \
    --subnet-id "${SUBNET_ARRAY[0]}" \
    --iam-instance-profile "Name=$INSTANCE_PROFILE" \
    --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":$VOLUME_SIZE,\"VolumeType\":\"gp3\",\"Encrypted\":true}}]" \
    --user-data "$USER_DATA" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME},{Key=Project,Value=$PREFIX}]" \
    --query "Instances[0].InstanceId" --output text)
  log "Launched EC2 instance: $INSTANCE_ID"

  log "Waiting for instance to be running..."
  aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"
  log "Instance is running"
fi

# ── 10. Elastic IP ────────────────────────────────────────────────────────
EXISTING_EIP=$(aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=instance-id,Values=$INSTANCE_ID" \
  --query "Addresses[0].PublicIp" --output text 2>/dev/null)

if [ "$EXISTING_EIP" != "None" ] && [ -n "$EXISTING_EIP" ]; then
  info "Elastic IP already associated: $EXISTING_EIP"
  PUBLIC_IP="$EXISTING_EIP"
else
  ALLOC_ID=$(aws ec2 describe-addresses --region "$REGION" \
    --filters "Name=tag:Project,Values=$PREFIX" \
    --query "Addresses[?AssociationId==null].AllocationId" --output text 2>/dev/null | head -1)

  if [ -z "$ALLOC_ID" ] || [ "$ALLOC_ID" = "None" ]; then
    ALLOC_ID=$(aws ec2 allocate-address --region "$REGION" \
      --domain vpc \
      --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=${PREFIX}-eip},{Key=Project,Value=$PREFIX}]" \
      --query "AllocationId" --output text)
    log "Allocated Elastic IP"
  fi

  aws ec2 associate-address --region "$REGION" \
    --instance-id "$INSTANCE_ID" \
    --allocation-id "$ALLOC_ID" >/dev/null
  PUBLIC_IP=$(aws ec2 describe-addresses --region "$REGION" \
    --allocation-ids "$ALLOC_ID" \
    --query "Addresses[0].PublicIp" --output text)
  log "Associated Elastic IP: $PUBLIC_IP"
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo -e "${GREEN}Infrastructure Setup Complete${NC}"
echo "============================================================"
echo ""
echo "  S3 Bucket:    $S3_BUCKET"
echo "  RDS Endpoint: $RDS_ENDPOINT"
echo "  EC2 Instance: $INSTANCE_ID ($INSTANCE_TYPE)"
echo "  Public IP:    $PUBLIC_IP"
echo "  Key File:     $KEY_FILE"
echo ""
echo "  SSH: ssh -i $KEY_FILE ec2-user@$PUBLIC_IP"
echo ""
echo "============================================================"
echo -e "${YELLOW}Next Steps${NC}"
echo "============================================================"
echo ""
echo "  1. Store your API keys in SSM (if not already done):"
echo ""
echo "     aws ssm put-parameter --region $REGION \\"
echo "       --name /${PREFIX}/google-api-key \\"
echo "       --type SecureString --value '<your-key>' --overwrite"
echo ""
echo "     aws ssm put-parameter --region $REGION \\"
echo "       --name /${PREFIX}/anthropic-api-key \\"
echo "       --type SecureString --value '<your-key>' --overwrite"
echo ""
echo "  2. Wait ~2 minutes for cloud-init to finish installing Docker"
echo ""
echo "  3. SSH in and verify:"
echo "     ssh -i $KEY_FILE ec2-user@$PUBLIC_IP"
echo "     docker --version && docker compose version"
echo ""
echo "  4. Deploy: EC2_HOST=$PUBLIC_IP ./infra/prod/deploy.sh"
echo ""
echo "  5. Update GitHub secrets:"
echo "     EC2_HOST=$PUBLIC_IP"
echo "     EC2_SSH_KEY=<contents of $KEY_FILE>"
echo ""
