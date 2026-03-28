# AWS Deployment - Step by Step Checklist

## Prerequisites
- [ ] AWS CLI installed and configured (`aws configure`)
- [ ] Docker installed locally
- [ ] Your Google API Key ready

---

## PHASE 1: Setup (15-20 minutes)

### Step 1: Get Your AWS Account ID
```bash
aws sts get-caller-identity --query Account --output text
```
Save this value: `_______________`

### Step 2: Set Environment Variables
```bash
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="YOUR_ACCOUNT_ID"
export APP_NAME="title-intelligence"
```

### Step 3: Create S3 Bucket
```bash
aws s3 mb s3://${APP_NAME}-storage-${AWS_ACCOUNT_ID} --region ${AWS_REGION}
```
- [ ] S3 bucket created

### Step 4: Create RDS PostgreSQL
```bash
# Generate secure password
DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9')
echo "Save this password: $DB_PASSWORD"

# Create RDS (takes 5-10 minutes)
aws rds create-db-instance \
    --db-instance-identifier ${APP_NAME}-db \
    --db-instance-class db.t3.medium \
    --engine postgres \
    --engine-version 15 \
    --master-username postgres \
    --master-user-password "$DB_PASSWORD" \
    --allocated-storage 100 \
    --db-name title_intelligence_hub \
    --no-publicly-accessible
```
- [ ] RDS instance created
- [ ] Password saved securely

### Step 5: Wait for RDS & Get Endpoint
```bash
aws rds wait db-instance-available --db-instance-identifier ${APP_NAME}-db

aws rds describe-db-instances \
    --db-instance-identifier ${APP_NAME}-db \
    --query 'DBInstances[0].Endpoint.Address' \
    --output text
```
RDS Endpoint: `_______________`

---

## PHASE 2: Store Secrets (5 minutes)

### Step 6: Store Secrets in AWS Secrets Manager
```bash
# Generate JWT secret
JWT_SECRET=$(openssl rand -base64 64 | tr -dc 'a-zA-Z0-9' | head -c 64)

# Store database URL
aws secretsmanager create-secret \
    --name ${APP_NAME}/database \
    --secret-string "{\"url\":\"postgresql+asyncpg://postgres:${DB_PASSWORD}@${RDS_ENDPOINT}:5432/title_intelligence_hub\"}"

# Store app secrets (replace YOUR_GOOGLE_API_KEY)
aws secretsmanager create-secret \
    --name ${APP_NAME}/app-secrets \
    --secret-string "{\"jwt_secret\":\"${JWT_SECRET}\",\"google_api_key\":\"YOUR_GOOGLE_API_KEY\"}"

# Store S3 config
aws secretsmanager create-secret \
    --name ${APP_NAME}/s3 \
    --secret-string "{\"bucket\":\"${APP_NAME}-storage-${AWS_ACCOUNT_ID}\",\"region\":\"${AWS_REGION}\"}"
```
- [ ] Secrets stored

---

## PHASE 3: Build & Push Docker Images (10-15 minutes)

### Step 7: Create ECR Repositories
```bash
aws ecr create-repository --repository-name ${APP_NAME}/backend
aws ecr create-repository --repository-name ${APP_NAME}/frontend
```
- [ ] ECR repos created

### Step 8: Login to ECR
```bash
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin \
    ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
```
- [ ] Logged in to ECR

### Step 9: Build & Push Backend
```bash
cd /path/to/your/app/backend

docker build -t ${APP_NAME}/backend .

docker tag ${APP_NAME}/backend:latest \
    ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest

docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest
```
- [ ] Backend image pushed

### Step 10: Build & Push Frontend
```bash
cd /path/to/your/app/frontend

# Replace YOUR_DOMAIN with your actual domain or ALB DNS
docker build \
    --build-arg NEXT_PUBLIC_API_URL=https://YOUR_DOMAIN \
    -t ${APP_NAME}/frontend .

docker tag ${APP_NAME}/frontend:latest \
    ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest

docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest
```
- [ ] Frontend image pushed

---

## PHASE 4: Deploy to ECS (15-20 minutes)

### Step 11: Create ECS Cluster
```bash
aws ecs create-cluster --cluster-name ${APP_NAME}-cluster
```
- [ ] ECS cluster created

### Step 12: Create IAM Roles
```bash
# See aws-deploy-part1.sh for full IAM setup
# Or use AWS Console: IAM → Roles → Create Role → ECS Task
```
- [ ] ecsTaskExecutionRole created
- [ ] ecsTaskRole created (with S3 access)

### Step 13: Create Load Balancer
```bash
# Use AWS Console: EC2 → Load Balancers → Create ALB
# Or run aws-deploy-part2.sh
```
- [ ] ALB created
- [ ] Target groups created
- [ ] Listener rules configured

ALB DNS: `_______________`

### Step 14: Register Task Definition
```bash
# Edit /app/scripts/task-definition.json with your values
aws ecs register-task-definition --cli-input-json file://task-definition.json
```
- [ ] Task definition registered

### Step 15: Create ECS Service
```bash
aws ecs create-service \
    --cluster ${APP_NAME}-cluster \
    --service-name ${APP_NAME}-service \
    --task-definition ${APP_NAME} \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=arn:xxx,containerName=backend,containerPort=8000"
```
- [ ] ECS service created

---

## PHASE 5: Initialize Database (5 minutes)

### Step 16: Run Migrations
```bash
# Connect to running container
TASK_ARN=$(aws ecs list-tasks --cluster ${APP_NAME}-cluster --query 'taskArns[0]' --output text)

aws ecs execute-command \
    --cluster ${APP_NAME}-cluster \
    --task ${TASK_ARN} \
    --container backend \
    --interactive \
    --command "/bin/bash"

# Inside container:
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.models import Base
from app.micro_apps.title_intelligence.models import *
from app.micro_apps.title_search.models import *
import os

async def migrate():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(migrate())
"

# Seed data
python scripts/seed.py
```
- [ ] Migrations complete
- [ ] Database seeded

---

## PHASE 6: Verify & Go Live

### Step 17: Test the Application
```bash
# Health check
curl http://YOUR_ALB_DNS/api/v1/health

# Open in browser
open http://YOUR_ALB_DNS
```
- [ ] Health check passes
- [ ] Login page loads
- [ ] Can login with admin@logikality.com / admin123

### Step 18: (Optional) Add SSL/HTTPS
```bash
# Request certificate in ACM
aws acm request-certificate \
    --domain-name your-domain.com \
    --validation-method DNS

# Add HTTPS listener to ALB (443)
# Update CORS_ORIGINS in task definition
```
- [ ] SSL certificate issued
- [ ] HTTPS working

---

## Summary of Created Resources

| Resource | Name/ID |
|----------|---------|
| S3 Bucket | |
| RDS Instance | |
| RDS Endpoint | |
| ECR Backend | |
| ECR Frontend | |
| ECS Cluster | |
| ALB | |
| ALB DNS | |

## Credentials to Change in Production
- [ ] admin@logikality.com password
- [ ] admin@societytitle.com password
- [ ] Database password (if needed)

## Monthly Cost Estimate
- RDS db.t3.medium: ~$50/month
- ECS Fargate (2 vCPU, 4GB): ~$70/month
- ALB: ~$20/month
- S3: ~$5-20/month (depends on usage)
- **Total: ~$145-160/month**
