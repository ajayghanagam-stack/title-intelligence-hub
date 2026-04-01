#!/bin/bash
# =============================================================================
# AWS DEPLOYMENT SCRIPT - Title Intelligence Hub
# =============================================================================
# Run this script section by section, not all at once
# =============================================================================

set -e

# -----------------------------------------------------------------------------
# STEP 1: SET YOUR CONFIGURATION
# -----------------------------------------------------------------------------
# Edit these values before running!

export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="YOUR_AWS_ACCOUNT_ID"  # Get from: aws sts get-caller-identity
export APP_NAME="title-intelligence"
export DOMAIN="your-domain.com"  # Your domain (optional, can use ALB DNS)

# Database
export DB_PASSWORD="$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)"
export DB_NAME="title_intelligence_hub"
export DB_USER="postgres"

# JWT Secret (generate a strong one)
export JWT_SECRET="$(openssl rand -base64 64 | tr -dc 'a-zA-Z0-9' | head -c 64)"

# Your Google API Key for Gemini
export GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY"

echo "Configuration set. Save these values securely:"
echo "DB_PASSWORD: $DB_PASSWORD"
echo "JWT_SECRET: $JWT_SECRET"

# -----------------------------------------------------------------------------
# STEP 2: CREATE S3 BUCKET
# -----------------------------------------------------------------------------

echo "Creating S3 bucket..."
aws s3 mb s3://${APP_NAME}-storage-${AWS_ACCOUNT_ID} --region ${AWS_REGION}

# Enable versioning
aws s3api put-bucket-versioning \
    --bucket ${APP_NAME}-storage-${AWS_ACCOUNT_ID} \
    --versioning-configuration Status=Enabled

# Block public access
aws s3api put-public-access-block \
    --bucket ${APP_NAME}-storage-${AWS_ACCOUNT_ID} \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "S3 bucket created: ${APP_NAME}-storage-${AWS_ACCOUNT_ID}"

# -----------------------------------------------------------------------------
# STEP 3: CREATE RDS POSTGRESQL DATABASE
# -----------------------------------------------------------------------------

echo "Creating RDS PostgreSQL database..."

# Create DB subnet group (you need at least 2 subnets in different AZs)
# First, get your default VPC subnets
SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=default-for-az,Values=true" \
    --query 'Subnets[*].SubnetId' \
    --output text | tr '\t' ',')

aws rds create-db-subnet-group \
    --db-subnet-group-name ${APP_NAME}-db-subnet \
    --db-subnet-group-description "Subnet group for ${APP_NAME}" \
    --subnet-ids ${SUBNETS//,/ }

# Create security group for RDS
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text)

RDS_SG_ID=$(aws ec2 create-security-group \
    --group-name ${APP_NAME}-rds-sg \
    --description "Security group for ${APP_NAME} RDS" \
    --vpc-id ${VPC_ID} \
    --query 'GroupId' --output text)

# Allow PostgreSQL from within VPC
aws ec2 authorize-security-group-ingress \
    --group-id ${RDS_SG_ID} \
    --protocol tcp \
    --port 5432 \
    --cidr 10.0.0.0/8

# Create RDS instance
aws rds create-db-instance \
    --db-instance-identifier ${APP_NAME}-db \
    --db-instance-class db.t3.medium \
    --engine postgres \
    --engine-version 15 \
    --master-username ${DB_USER} \
    --master-user-password ${DB_PASSWORD} \
    --allocated-storage 100 \
    --storage-type gp3 \
    --db-subnet-group-name ${APP_NAME}-db-subnet \
    --vpc-security-group-ids ${RDS_SG_ID} \
    --db-name ${DB_NAME} \
    --backup-retention-period 7 \
    --storage-encrypted \
    --no-publicly-accessible

echo "RDS instance creating... This takes 5-10 minutes."
echo "Run: aws rds describe-db-instances --db-instance-identifier ${APP_NAME}-db --query 'DBInstances[0].DBInstanceStatus'"

# -----------------------------------------------------------------------------
# STEP 4: CREATE ECR REPOSITORIES
# -----------------------------------------------------------------------------

echo "Creating ECR repositories..."

aws ecr create-repository \
    --repository-name ${APP_NAME}/backend \
    --image-scanning-configuration scanOnPush=true \
    --region ${AWS_REGION}

aws ecr create-repository \
    --repository-name ${APP_NAME}/frontend \
    --image-scanning-configuration scanOnPush=true \
    --region ${AWS_REGION}

echo "ECR repositories created."

# -----------------------------------------------------------------------------
# STEP 5: CREATE SECRETS IN SECRETS MANAGER
# -----------------------------------------------------------------------------

echo "Storing secrets in AWS Secrets Manager..."

# Wait for RDS to be available and get endpoint
echo "Waiting for RDS to be available..."
aws rds wait db-instance-available --db-instance-identifier ${APP_NAME}-db

RDS_ENDPOINT=$(aws rds describe-db-instances \
    --db-instance-identifier ${APP_NAME}-db \
    --query 'DBInstances[0].Endpoint.Address' \
    --output text)

echo "RDS Endpoint: ${RDS_ENDPOINT}"

# Create secrets
aws secretsmanager create-secret \
    --name ${APP_NAME}/database \
    --secret-string "{\"url\":\"postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${RDS_ENDPOINT}:5432/${DB_NAME}\"}"

aws secretsmanager create-secret \
    --name ${APP_NAME}/app-secrets \
    --secret-string "{\"jwt_secret\":\"${JWT_SECRET}\",\"google_api_key\":\"${GOOGLE_API_KEY}\"}"

aws secretsmanager create-secret \
    --name ${APP_NAME}/s3 \
    --secret-string "{\"bucket\":\"${APP_NAME}-storage-${AWS_ACCOUNT_ID}\",\"region\":\"${AWS_REGION}\"}"

echo "Secrets stored in Secrets Manager."

# -----------------------------------------------------------------------------
# STEP 6: BUILD AND PUSH DOCKER IMAGES
# -----------------------------------------------------------------------------

echo "Building and pushing Docker images..."

# Login to ECR
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Build and push backend
cd backend
docker build -t ${APP_NAME}/backend:latest .
docker tag ${APP_NAME}/backend:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest
cd ..

# Build and push frontend
cd frontend
docker build \
    --build-arg NEXT_PUBLIC_API_URL=https://api.${DOMAIN} \
    -t ${APP_NAME}/frontend:latest .
docker tag ${APP_NAME}/frontend:latest ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest
cd ..

echo "Docker images pushed to ECR."

# -----------------------------------------------------------------------------
# STEP 7: CREATE ECS CLUSTER
# -----------------------------------------------------------------------------

echo "Creating ECS cluster..."

aws ecs create-cluster \
    --cluster-name ${APP_NAME}-cluster \
    --capacity-providers FARGATE \
    --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1

echo "ECS cluster created."

# -----------------------------------------------------------------------------
# STEP 8: CREATE IAM ROLES FOR ECS
# -----------------------------------------------------------------------------

echo "Creating IAM roles..."

# ECS Task Execution Role
cat > /tmp/ecs-trust-policy.json << 'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
POLICY

aws iam create-role \
    --role-name ${APP_NAME}-ecs-execution-role \
    --assume-role-policy-document file:///tmp/ecs-trust-policy.json

aws iam attach-role-policy \
    --role-name ${APP_NAME}-ecs-execution-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Add Secrets Manager access
cat > /tmp/secrets-policy.json << POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:${APP_NAME}/*"
    }
  ]
}
POLICY

aws iam put-role-policy \
    --role-name ${APP_NAME}-ecs-execution-role \
    --policy-name SecretsAccess \
    --policy-document file:///tmp/secrets-policy.json

# ECS Task Role (for S3 access)
aws iam create-role \
    --role-name ${APP_NAME}-ecs-task-role \
    --assume-role-policy-document file:///tmp/ecs-trust-policy.json

cat > /tmp/s3-policy.json << POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${APP_NAME}-storage-${AWS_ACCOUNT_ID}",
        "arn:aws:s3:::${APP_NAME}-storage-${AWS_ACCOUNT_ID}/*"
      ]
    }
  ]
}
POLICY

aws iam put-role-policy \
    --role-name ${APP_NAME}-ecs-task-role \
    --policy-name S3Access \
    --policy-document file:///tmp/s3-policy.json

echo "IAM roles created."

echo ""
echo "=========================================="
echo "DEPLOYMENT PREPARATION COMPLETE!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Create CloudWatch log group"
echo "2. Create ALB and target groups"
echo "3. Register ECS task definition"
echo "4. Create ECS service"
echo "5. Run database migrations"
echo ""
echo "See aws-deploy-part2.sh for remaining steps"
