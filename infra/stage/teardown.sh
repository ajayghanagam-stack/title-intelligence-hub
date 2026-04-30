#!/usr/bin/env bash
set -euo pipefail
export AWS_PAGER=""

# ============================================================================
# Title Intelligence Hub — EC2 Infrastructure Teardown
# Removes EC2-specific resources. RDS + S3 + SSM are optionally kept.
# ============================================================================

PREFIX="ti-hub-stage"
# Region is env-overridable so the same script can target us-east-1 (legacy)
# or ap-south-1 (Mumbai migration). Default keeps existing callers untouched.
REGION="${REGION:-us-east-1}"

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
echo -e "${RED}  WARNING: This will DELETE EC2 resources for ${PREFIX}${NC}"
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

VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=isDefault,Values=true" \
  --query "Vpcs[0].VpcId" --output text 2>/dev/null)

# ── 1. Terminate EC2 Instance ─────────────────────────────────────────────
INSTANCE_NAME="${PREFIX}-server"
INSTANCE_ID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=$INSTANCE_NAME" \
            "Name=instance-state-name,Values=running,pending,stopped" \
  --query "Reservations[0].Instances[0].InstanceId" --output text 2>/dev/null)

if [ "$INSTANCE_ID" != "None" ] && [ -n "$INSTANCE_ID" ]; then
  log "Terminating EC2 instance: $INSTANCE_ID"
  aws ec2 terminate-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
  log "Waiting for instance to terminate..."
  aws ec2 wait instance-terminated --region "$REGION" --instance-ids "$INSTANCE_ID"
  log "Instance terminated"
else
  warn "No running EC2 instance found with name '$INSTANCE_NAME'"
fi

# ── 2. Elastic IP (KEPT — permanent reservation for DNS stability) ─────
EIP_INFO=$(aws ec2 describe-addresses --region "$REGION" \
  --filters "Name=tag:Project,Values=$PREFIX" \
  --query "Addresses[0].PublicIp" --output text 2>/dev/null)
if [ "$EIP_INFO" != "None" ] && [ -n "$EIP_INFO" ]; then
  warn "Elastic IP $EIP_INFO kept (permanent — DNS points here). Disassociated from terminated instance."
else
  warn "No Elastic IP found for $PREFIX"
fi

# ── 3. Delete EC2 Security Group ─────────────────────────────────────────
SG_NAME="${PREFIX}-ec2-sg"
SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query "SecurityGroups[0].GroupId" --output text 2>/dev/null)

if [ "$SG_ID" != "None" ] && [ -n "$SG_ID" ]; then
  # Remove EC2→RDS ingress rule from RDS security group
  SG_RDS=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=${PREFIX}-rds-sg" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" --output text 2>/dev/null)
  if [ "$SG_RDS" != "None" ] && [ -n "$SG_RDS" ]; then
    aws ec2 revoke-security-group-ingress --region "$REGION" \
      --group-id "$SG_RDS" --protocol tcp --port 5432 \
      --source-group "$SG_ID" 2>/dev/null || true
    log "Removed EC2 → RDS ingress rule"
  fi

  aws ec2 delete-security-group --region "$REGION" --group-id "$SG_ID" 2>/dev/null || true
  log "Deleted security group: $SG_NAME"
fi

# ── 4. Delete IAM Instance Profile & Role ────────────────────────────────
# IAM is a GLOBAL resource — deleting it here will break any EC2 in another
# region that still uses this same role/profile (e.g. during a cross-region
# migration where stage is briefly running in two regions). We scan every
# enabled region for active associations and skip IAM deletion if any exist.
# Override with FORCE_IAM_DELETE=1 only when you're certain no other region
# depends on this role.
EC2_ROLE="${PREFIX}-ec2-role"
INSTANCE_PROFILE="${PREFIX}-ec2-profile"
PROFILE_ARN="arn:aws:iam::${ACCOUNT_ID}:instance-profile/${INSTANCE_PROFILE}"

OTHER_REGION_USERS=""
if [ "${FORCE_IAM_DELETE:-0}" != "1" ] && \
   aws iam get-instance-profile --instance-profile-name "$INSTANCE_PROFILE" >/dev/null 2>&1; then
  ENABLED_REGIONS=$(aws ec2 describe-regions --region "$REGION" \
    --query "Regions[?OptInStatus!='not-opted-in'].RegionName" --output text 2>/dev/null)
  for r in $ENABLED_REGIONS; do
    [ "$r" = "$REGION" ] && continue
    HITS=$(aws ec2 describe-iam-instance-profile-associations --region "$r" \
      --filters "Name=iam-instance-profile-arn,Values=${PROFILE_ARN}" \
      --query "IamInstanceProfileAssociations[?State=='associated'].InstanceId" \
      --output text 2>/dev/null)
    if [ -n "$HITS" ] && [ "$HITS" != "None" ]; then
      OTHER_REGION_USERS="${OTHER_REGION_USERS}${r}: ${HITS}\n"
    fi
  done
fi

if [ -n "$OTHER_REGION_USERS" ]; then
  warn "Skipping IAM deletion — instance profile is still attached to EC2 in:"
  echo -e "$OTHER_REGION_USERS" >&2
  warn "Delete those instances first, or set FORCE_IAM_DELETE=1 to override (will break them)."
elif aws iam get-instance-profile --instance-profile-name "$INSTANCE_PROFILE" >/dev/null 2>&1; then
  aws iam remove-role-from-instance-profile \
    --instance-profile-name "$INSTANCE_PROFILE" \
    --role-name "$EC2_ROLE" 2>/dev/null || true
  aws iam delete-instance-profile --instance-profile-name "$INSTANCE_PROFILE" 2>/dev/null || true
  log "Deleted instance profile: $INSTANCE_PROFILE"

  if aws iam get-role --role-name "$EC2_ROLE" >/dev/null 2>&1; then
    INLINE=$(aws iam list-role-policies --role-name "$EC2_ROLE" \
      --query "PolicyNames" --output text 2>/dev/null)
    for p in $INLINE; do
      aws iam delete-role-policy --role-name "$EC2_ROLE" --policy-name "$p" 2>/dev/null || true
    done
    aws iam delete-role --role-name "$EC2_ROLE" 2>/dev/null || true
    log "Deleted IAM role: $EC2_ROLE"
  fi
fi

# ── 5. Delete SSH Key Pair ───────────────────────────────────────────────
KEY_NAME="${PREFIX}-key"
aws ec2 delete-key-pair --region "$REGION" --key-name "$KEY_NAME" 2>/dev/null || true
log "Deleted key pair: $KEY_NAME"
warn "Local key file at ~/.ssh/${KEY_NAME}.pem was NOT deleted (do so manually if desired)"

# ── 6. Optional: Delete RDS ─────────────────────────────────────────────
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
    log "Deleting RDS instance (takes several minutes)..."
  else
    warn "Skipped RDS deletion (kept for reuse)"
  fi
fi

# ── 7. Optional: Delete S3 ──────────────────────────────────────────────
# Region-aware bucket name — must match the suffix logic in setup.sh.
case "$REGION" in
  us-east-1)  BUCKET_REGION_SUFFIX="" ;;
  ap-south-1) BUCKET_REGION_SUFFIX="-aps1" ;;
  *)          BUCKET_REGION_SUFFIX="-${REGION//-/}" ;;
esac
S3_BUCKET="${PREFIX}-storage-${ACCOUNT_ID}${BUCKET_REGION_SUFFIX}"
if aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
  echo ""
  read -p "Delete S3 bucket '$S3_BUCKET' and ALL its contents? (yes/no): " CONFIRM_S3
  if [ "$CONFIRM_S3" = "yes" ]; then
    aws s3 rb "s3://${S3_BUCKET}" --force 2>/dev/null || true
    log "Deleted S3 bucket: $S3_BUCKET"
  else
    warn "Skipped S3 bucket deletion (kept for reuse)"
  fi
fi

echo ""
echo -e "${GREEN}EC2 teardown complete.${NC}"
echo ""
echo "Resources removed: EC2 instance, security group, IAM role, key pair"
echo "Resources kept: Elastic IP (permanent), RDS, S3, SSM parameters (unless you chose to delete them)"
echo ""
