#!/bin/bash
# =============================================================================
# SHUTDOWN SCRIPT - Title Intelligence Hub (AWS)
# =============================================================================
# Stops all expensive AWS resources to save costs when not in use.
# Estimated savings: ~$295/month
#
# Usage: ./shutdown-aws.sh
# =============================================================================

set -e

AWS_REGION="us-east-1"
APP_NAME="title-intelligence"
EC2_INSTANCE_ID="i-0ad64a5caf555cb58"
RDS_INSTANCE_ID="title-intelligence-db"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${RED}=============================================${NC}"
echo -e "${RED}  SHUTTING DOWN - Title Intelligence Hub${NC}"
echo -e "${RED}=============================================${NC}"
echo ""

# Step 1: Scale ECS service to 0
echo -e "${BLUE}[1/3] Stopping ECS tasks...${NC}"
aws ecs update-service \
    --cluster ${APP_NAME}-cluster \
    --service ${APP_NAME}-service \
    --desired-count 0 \
    --region ${AWS_REGION} > /dev/null 2>&1
echo -e "${GREEN}  ECS service scaled to 0 tasks${NC}"

# Step 2: Stop EC2 instance
echo -e "${BLUE}[2/3] Stopping EC2 instance (${EC2_INSTANCE_ID})...${NC}"
EC2_STATE=$(aws ec2 describe-instances --instance-ids ${EC2_INSTANCE_ID} --region ${AWS_REGION} --query 'Reservations[0].Instances[0].State.Name' --output text 2>&1)
if [ "$EC2_STATE" = "running" ]; then
    aws ec2 stop-instances --instance-ids ${EC2_INSTANCE_ID} --region ${AWS_REGION} > /dev/null 2>&1
    echo -e "${GREEN}  EC2 instance stopping (saves ~\$245/mo)${NC}"
else
    echo -e "${YELLOW}  EC2 instance already ${EC2_STATE}${NC}"
fi

# Step 3: Stop RDS instance
echo -e "${BLUE}[3/3] Stopping RDS instance (${RDS_INSTANCE_ID})...${NC}"
RDS_STATE=$(aws rds describe-db-instances --db-instance-identifier ${RDS_INSTANCE_ID} --region ${AWS_REGION} --query 'DBInstances[0].DBInstanceStatus' --output text 2>&1)
if [ "$RDS_STATE" = "available" ]; then
    aws rds stop-db-instance --db-instance-identifier ${RDS_INSTANCE_ID} --region ${AWS_REGION} > /dev/null 2>&1
    echo -e "${GREEN}  RDS instance stopping (saves ~\$50/mo)${NC}"
else
    echo -e "${YELLOW}  RDS instance already ${RDS_STATE}${NC}"
fi

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  SHUTDOWN COMPLETE${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo "Resources stopped:"
echo "  - ECS tasks: 0 running"
echo "  - EC2 (${EC2_INSTANCE_ID}): stopping"
echo "  - RDS (${RDS_INSTANCE_ID}): stopping"
echo ""
echo "Still running (minimal cost):"
echo "  - S3 bucket: ~\$1-5/mo (stores your documents)"
echo "  - ECR images: ~\$1/mo"
echo "  - Secrets Manager: ~\$1.20/mo"
echo "  - ALB: ~\$20/mo (delete manually if not needed)"
echo ""
echo -e "${YELLOW}NOTE: RDS auto-restarts after 7 days if stopped.${NC}"
echo -e "${YELLOW}Run this script again if that happens.${NC}"
echo ""
echo "To bring everything back up, run:"
echo "  ./startup-aws.sh"
echo ""
