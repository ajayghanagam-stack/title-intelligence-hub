#!/bin/bash
# =============================================================================
# AWS DEPLOYMENT SCRIPT - Part 2: ECS Service Setup
# =============================================================================

set -e

# Load configuration (same as part 1)
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="YOUR_AWS_ACCOUNT_ID"
export APP_NAME="title-intelligence"

# -----------------------------------------------------------------------------
# STEP 9: CREATE CLOUDWATCH LOG GROUP
# -----------------------------------------------------------------------------

echo "Creating CloudWatch log group..."

aws logs create-log-group \
    --log-group-name /ecs/${APP_NAME} \
    --region ${AWS_REGION}

aws logs put-retention-policy \
    --log-group-name /ecs/${APP_NAME} \
    --retention-in-days 30

echo "Log group created."

# -----------------------------------------------------------------------------
# STEP 10: CREATE APPLICATION LOAD BALANCER
# -----------------------------------------------------------------------------

echo "Creating Application Load Balancer..."

# Get VPC and subnets
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=default-for-az,Values=true" \
    --query 'Subnets[*].SubnetId' \
    --output text)

# Create security group for ALB
ALB_SG_ID=$(aws ec2 create-security-group \
    --group-name ${APP_NAME}-alb-sg \
    --description "Security group for ${APP_NAME} ALB" \
    --vpc-id ${VPC_ID} \
    --query 'GroupId' --output text)

# Allow HTTP and HTTPS
aws ec2 authorize-security-group-ingress --group-id ${ALB_SG_ID} --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id ${ALB_SG_ID} --protocol tcp --port 443 --cidr 0.0.0.0/0

# Create ALB
ALB_ARN=$(aws elbv2 create-load-balancer \
    --name ${APP_NAME}-alb \
    --subnets ${SUBNETS} \
    --security-groups ${ALB_SG_ID} \
    --scheme internet-facing \
    --type application \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text)

echo "ALB ARN: ${ALB_ARN}"

# Create target groups
BACKEND_TG_ARN=$(aws elbv2 create-target-group \
    --name ${APP_NAME}-backend-tg \
    --protocol HTTP \
    --port 8000 \
    --vpc-id ${VPC_ID} \
    --target-type ip \
    --health-check-path /api/v1/health \
    --health-check-interval-seconds 30 \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

FRONTEND_TG_ARN=$(aws elbv2 create-target-group \
    --name ${APP_NAME}-frontend-tg \
    --protocol HTTP \
    --port 3000 \
    --vpc-id ${VPC_ID} \
    --target-type ip \
    --health-check-path / \
    --health-check-interval-seconds 30 \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text)

# Create HTTP listener (redirects to HTTPS in production)
aws elbv2 create-listener \
    --load-balancer-arn ${ALB_ARN} \
    --protocol HTTP \
    --port 80 \
    --default-actions Type=forward,TargetGroupArn=${FRONTEND_TG_ARN}

# Add rule for /api/* to route to backend
LISTENER_ARN=$(aws elbv2 describe-listeners \
    --load-balancer-arn ${ALB_ARN} \
    --query 'Listeners[0].ListenerArn' \
    --output text)

aws elbv2 create-rule \
    --listener-arn ${LISTENER_ARN} \
    --priority 10 \
    --conditions Field=path-pattern,Values='/api/*' \
    --actions Type=forward,TargetGroupArn=${BACKEND_TG_ARN}

ALB_DNS=$(aws elbv2 describe-load-balancers \
    --load-balancer-arns ${ALB_ARN} \
    --query 'LoadBalancers[0].DNSName' \
    --output text)

echo "ALB DNS: ${ALB_DNS}"
echo "Backend Target Group: ${BACKEND_TG_ARN}"
echo "Frontend Target Group: ${FRONTEND_TG_ARN}"

# Create security group for ECS tasks
ECS_SG_ID=$(aws ec2 create-security-group \
    --group-name ${APP_NAME}-ecs-sg \
    --description "Security group for ${APP_NAME} ECS tasks" \
    --vpc-id ${VPC_ID} \
    --query 'GroupId' --output text)

# Allow traffic from ALB
aws ec2 authorize-security-group-ingress \
    --group-id ${ECS_SG_ID} \
    --protocol tcp \
    --port 8000 \
    --source-group ${ALB_SG_ID}

aws ec2 authorize-security-group-ingress \
    --group-id ${ECS_SG_ID} \
    --protocol tcp \
    --port 3000 \
    --source-group ${ALB_SG_ID}

# Allow ECS to access RDS
RDS_SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${APP_NAME}-rds-sg" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)

aws ec2 authorize-security-group-ingress \
    --group-id ${RDS_SG_ID} \
    --protocol tcp \
    --port 5432 \
    --source-group ${ECS_SG_ID}

echo "Security groups configured."

# -----------------------------------------------------------------------------
# STEP 11: CREATE ECS TASK DEFINITION
# -----------------------------------------------------------------------------

echo "Creating ECS task definition..."

# Get secrets ARNs
DB_SECRET_ARN=$(aws secretsmanager describe-secret --secret-id ${APP_NAME}/database --query 'ARN' --output text)
APP_SECRET_ARN=$(aws secretsmanager describe-secret --secret-id ${APP_NAME}/app-secrets --query 'ARN' --output text)
S3_SECRET_ARN=$(aws secretsmanager describe-secret --secret-id ${APP_NAME}/s3 --query 'ARN' --output text)

cat > /tmp/task-definition.json << EOF
{
  "family": "${APP_NAME}",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "4096",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${APP_NAME}-ecs-execution-role",
  "taskRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${APP_NAME}-ecs-task-role",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest",
      "essential": true,
      "portMappings": [
        {"containerPort": 8000, "protocol": "tcp"}
      ],
      "environment": [
        {"name": "DEBUG", "value": "false"},
        {"name": "STORAGE_PROVIDER", "value": "s3"},
        {"name": "S3_REGION", "value": "${AWS_REGION}"},
        {"name": "PIPELINE_BACKEND", "value": "background_tasks"},
        {"name": "PIPELINE_MODE", "value": "native_pdf"},
        {"name": "CORS_ORIGINS", "value": "[\"http://${ALB_DNS}\",\"https://${ALB_DNS}\"]"}
      ],
      "secrets": [
        {"name": "DATABASE_URL", "valueFrom": "${DB_SECRET_ARN}:url::"},
        {"name": "JWT_SECRET", "valueFrom": "${APP_SECRET_ARN}:jwt_secret::"},
        {"name": "GOOGLE_API_KEY", "valueFrom": "${APP_SECRET_ARN}:google_api_key::"},
        {"name": "S3_BUCKET", "valueFrom": "${S3_SECRET_ARN}:bucket::"}
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/${APP_NAME}",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "backend"
        }
      }
    },
    {
      "name": "frontend",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest",
      "essential": true,
      "portMappings": [
        {"containerPort": 3000, "protocol": "tcp"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/${APP_NAME}",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "frontend"
        }
      }
    }
  ]
}
EOF

aws ecs register-task-definition --cli-input-json file:///tmp/task-definition.json

echo "Task definition registered."

# -----------------------------------------------------------------------------
# STEP 12: CREATE ECS SERVICE
# -----------------------------------------------------------------------------

echo "Creating ECS service..."

SUBNET_ARRAY=$(echo ${SUBNETS} | tr ' ' ',')

aws ecs create-service \
    --cluster ${APP_NAME}-cluster \
    --service-name ${APP_NAME}-service \
    --task-definition ${APP_NAME} \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_ARRAY}],securityGroups=[${ECS_SG_ID}],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=${BACKEND_TG_ARN},containerName=backend,containerPort=8000" "targetGroupArn=${FRONTEND_TG_ARN},containerName=frontend,containerPort=3000"

echo "ECS service created."

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "Your application is deploying to:"
echo "URL: http://${ALB_DNS}"
echo ""
echo "Next steps:"
echo "1. Wait for ECS service to stabilize (5-10 minutes)"
echo "2. Run database migrations"
echo "3. Add SSL certificate (optional)"
echo ""
echo "Monitor deployment:"
echo "aws ecs describe-services --cluster ${APP_NAME}-cluster --services ${APP_NAME}-service"
