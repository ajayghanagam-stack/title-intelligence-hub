#!/bin/bash
# =============================================================================
# STARTUP SCRIPT - Title Intelligence Hub (AWS)
# =============================================================================
# Restarts all AWS resources after a shutdown.
# Full startup takes approximately 5-7 minutes.
#
# Usage: ./startup-aws.sh
# =============================================================================

set -e

AWS_REGION="us-east-1"
APP_NAME="title-intelligence"
EC2_INSTANCE_ID="i-0ad64a5caf555cb58"
RDS_INSTANCE_ID="title-intelligence-db"
ALB_DNS="title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  STARTING UP - Title Intelligence Hub${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""

# Step 1: Start RDS (takes longest, start first)
echo -e "${BLUE}[1/4] Starting RDS instance...${NC}"
RDS_STATE=$(aws rds describe-db-instances --db-instance-identifier ${RDS_INSTANCE_ID} --region ${AWS_REGION} --query 'DBInstances[0].DBInstanceStatus' --output text 2>&1)
if [ "$RDS_STATE" = "stopped" ]; then
    aws rds start-db-instance --db-instance-identifier ${RDS_INSTANCE_ID} --region ${AWS_REGION} > /dev/null 2>&1
    echo -e "${GREEN}  RDS instance starting (takes 3-5 minutes)...${NC}"
elif [ "$RDS_STATE" = "available" ]; then
    echo -e "${GREEN}  RDS instance already running${NC}"
else
    echo -e "${YELLOW}  RDS instance is ${RDS_STATE}, waiting...${NC}"
fi

# Step 2: Start EC2 instance
echo -e "${BLUE}[2/4] Starting EC2 instance...${NC}"
EC2_STATE=$(aws ec2 describe-instances --instance-ids ${EC2_INSTANCE_ID} --region ${AWS_REGION} --query 'Reservations[0].Instances[0].State.Name' --output text 2>&1)
if [ "$EC2_STATE" = "stopped" ]; then
    aws ec2 start-instances --instance-ids ${EC2_INSTANCE_ID} --region ${AWS_REGION} > /dev/null 2>&1
    echo -e "${GREEN}  EC2 instance starting (takes 1-2 minutes)...${NC}"
elif [ "$EC2_STATE" = "running" ]; then
    echo -e "${GREEN}  EC2 instance already running${NC}"
else
    echo -e "${YELLOW}  EC2 instance is ${EC2_STATE}, waiting...${NC}"
fi

# Step 3: Wait for EC2 + RDS to be ready
echo ""
echo -e "${BLUE}[3/4] Waiting for instances to be ready...${NC}"
echo -e "${YELLOW}  This takes 3-5 minutes. Please be patient.${NC}"
echo ""

# Wait for EC2
echo -n "  EC2: waiting..."
aws ec2 wait instance-running --instance-ids ${EC2_INSTANCE_ID} --region ${AWS_REGION} 2>&1
echo -e "\r  EC2: ${GREEN}running${NC}         "

# Wait for ECS container instance to register
echo -n "  ECS agent: waiting..."
for i in $(seq 1 30); do
    REGISTERED=$(aws ecs describe-container-instances --cluster ${APP_NAME}-cluster --container-instances $(aws ecs list-container-instances --cluster ${APP_NAME}-cluster --region ${AWS_REGION} --query 'containerInstanceArns[0]' --output text 2>/dev/null) --region ${AWS_REGION} --query 'containerInstances[0].status' --output text 2>/dev/null)
    if [ "$REGISTERED" = "ACTIVE" ]; then
        break
    fi
    sleep 10
done
echo -e "\r  ECS agent: ${GREEN}registered${NC}     "

# Wait for RDS
echo -n "  RDS: waiting..."
aws rds wait db-instance-available --db-instance-identifier ${RDS_INSTANCE_ID} --region ${AWS_REGION} 2>&1
echo -e "\r  RDS: ${GREEN}available${NC}      "

# Step 4: Scale ECS service back up
echo ""
echo -e "${BLUE}[4/4] Starting ECS tasks...${NC}"
aws ecs update-service \
    --cluster ${APP_NAME}-cluster \
    --service ${APP_NAME}-service \
    --desired-count 1 \
    --region ${AWS_REGION} > /dev/null 2>&1
echo -e "${GREEN}  ECS service scaled to 1 task${NC}"

# Wait for task to be running
echo -n "  Task: starting..."
for i in $(seq 1 30); do
    RUNNING=$(aws ecs describe-services --cluster ${APP_NAME}-cluster --services ${APP_NAME}-service --region ${AWS_REGION} --query 'services[0].runningCount' --output text 2>/dev/null)
    if [ "$RUNNING" = "1" ]; then
        break
    fi
    sleep 10
done
echo -e "\r  Task: ${GREEN}running${NC}        "

# Health check
echo ""
echo -e "${BLUE}Running health check...${NC}"
sleep 15
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${ALB_DNS}/api/v1/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}  Health check: PASSED${NC}"
else
    echo -e "${YELLOW}  Health check returned ${HTTP_CODE} (may need another minute to warm up)${NC}"
    echo "  Try: curl http://${ALB_DNS}/api/v1/health"
fi

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  STARTUP COMPLETE${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo "Your application is available at:"
echo -e "  ${GREEN}http://${ALB_DNS}${NC}"
echo ""
echo "Login credentials:"
echo "  Platform Admin: admin@logikality.com / admin123"
echo "  Society Title:  admin@societytitle.com / admin123"
echo ""
echo "To shut down again, run:"
echo "  ./shutdown-aws.sh"
echo ""
