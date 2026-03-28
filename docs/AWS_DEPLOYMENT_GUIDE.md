# AWS Production Deployment Guide

## Title Intelligence Hub - AWS Deployment

This guide covers deploying the Title Intelligence Hub to AWS for production use.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         AWS Cloud                                │
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │ CloudFront  │────▶│    ALB      │────▶│    ECS      │       │
│  │    (CDN)    │     │(Load Balancer)    │  (Fargate)  │       │
│  └─────────────┘     └─────────────┘     └─────────────┘       │
│                                                │                 │
│                           ┌────────────────────┼────────────┐   │
│                           │                    │            │   │
│                           ▼                    ▼            ▼   │
│                    ┌─────────────┐     ┌─────────────┐ ┌──────┐│
│                    │    RDS      │     │     S3      │ │Secrets│
│                    │ PostgreSQL  │     │   Bucket    │ │Manager│
│                    └─────────────┘     └─────────────┘ └──────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

1. AWS Account with appropriate permissions
2. AWS CLI installed and configured
3. Docker installed locally
4. Domain name (optional, but recommended)

---

## Step 1: AWS Infrastructure Setup

### 1.1 Create S3 Bucket for Document Storage

```bash
# Create S3 bucket
aws s3 mb s3://your-title-intelligence-bucket --region us-east-1

# Enable versioning (recommended)
aws s3api put-bucket-versioning \
    --bucket your-title-intelligence-bucket \
    --versioning-configuration Status=Enabled

# Set CORS for the bucket
aws s3api put-bucket-cors --bucket your-title-intelligence-bucket --cors-configuration '{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
      "AllowedOrigins": ["https://your-domain.com"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}'
```

### 1.2 Create RDS PostgreSQL Database

```bash
# Create DB subnet group (use your VPC subnets)
aws rds create-db-subnet-group \
    --db-subnet-group-name title-intelligence-db-subnet \
    --db-subnet-group-description "Subnet group for Title Intelligence" \
    --subnet-ids subnet-xxx subnet-yyy

# Create PostgreSQL instance
aws rds create-db-instance \
    --db-instance-identifier title-intelligence-db \
    --db-instance-class db.t3.medium \
    --engine postgres \
    --engine-version 15 \
    --master-username postgres \
    --master-user-password YOUR_STRONG_PASSWORD \
    --allocated-storage 100 \
    --storage-type gp3 \
    --db-subnet-group-name title-intelligence-db-subnet \
    --vpc-security-group-ids sg-xxx \
    --backup-retention-period 7 \
    --multi-az \
    --storage-encrypted
```

### 1.3 Create Secrets in AWS Secrets Manager

```bash
# Store database credentials
aws secretsmanager create-secret \
    --name title-intelligence/database \
    --secret-string '{
      "username": "postgres",
      "password": "YOUR_DB_PASSWORD",
      "host": "your-rds-endpoint.region.rds.amazonaws.com",
      "port": 5432,
      "database": "title_intelligence_hub"
    }'

# Store API keys
aws secretsmanager create-secret \
    --name title-intelligence/api-keys \
    --secret-string '{
      "jwt_secret": "YOUR_64_CHAR_JWT_SECRET",
      "google_api_key": "YOUR_GOOGLE_API_KEY"
    }'

# Store S3 credentials (if using IAM user instead of roles)
aws secretsmanager create-secret \
    --name title-intelligence/s3 \
    --secret-string '{
      "access_key": "YOUR_AWS_ACCESS_KEY",
      "secret_key": "YOUR_AWS_SECRET_KEY",
      "bucket": "your-title-intelligence-bucket",
      "region": "us-east-1"
    }'
```

---

## Step 2: Create ECR Repositories

```bash
# Create backend repository
aws ecr create-repository \
    --repository-name title-intelligence/backend \
    --image-scanning-configuration scanOnPush=true

# Create frontend repository
aws ecr create-repository \
    --repository-name title-intelligence/frontend \
    --image-scanning-configuration scanOnPush=true

# Get login token
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
```

---

## Step 3: Build and Push Docker Images

### 3.1 Build Backend Image

```bash
cd backend

# Build for production
docker build -t title-intelligence/backend:latest .

# Tag for ECR
docker tag title-intelligence/backend:latest \
    YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/title-intelligence/backend:latest

# Push to ECR
docker push YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/title-intelligence/backend:latest
```

### 3.2 Build Frontend Image

```bash
cd frontend

# Build for production with API URL
docker build \
    --build-arg NEXT_PUBLIC_API_URL=https://api.your-domain.com \
    -t title-intelligence/frontend:latest .

# Tag and push
docker tag title-intelligence/frontend:latest \
    YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/title-intelligence/frontend:latest

docker push YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/title-intelligence/frontend:latest
```

---

## Step 4: ECS Deployment

### 4.1 Create ECS Cluster

```bash
aws ecs create-cluster \
    --cluster-name title-intelligence-cluster \
    --capacity-providers FARGATE FARGATE_SPOT \
    --default-capacity-provider-strategy \
        capacityProvider=FARGATE,weight=1 \
        capacityProvider=FARGATE_SPOT,weight=3
```

### 4.2 Create Task Definition

Create `task-definition.json`:

```json
{
  "family": "title-intelligence",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "4096",
  "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/ecsTaskRole",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/title-intelligence/backend:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "DEBUG", "value": "false"},
        {"name": "STORAGE_PROVIDER", "value": "s3"},
        {"name": "S3_REGION", "value": "us-east-1"},
        {"name": "PIPELINE_BACKEND", "value": "background_tasks"},
        {"name": "PIPELINE_MODE", "value": "native_pdf"}
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT:secret:title-intelligence/database"
        },
        {
          "name": "JWT_SECRET",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT:secret:title-intelligence/api-keys:jwt_secret::"
        },
        {
          "name": "GOOGLE_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT:secret:title-intelligence/api-keys:google_api_key::"
        },
        {
          "name": "S3_BUCKET",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT:secret:title-intelligence/s3:bucket::"
        },
        {
          "name": "S3_ACCESS_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT:secret:title-intelligence/s3:access_key::"
        },
        {
          "name": "S3_SECRET_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:YOUR_ACCOUNT:secret:title-intelligence/s3:secret_key::"
        }
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
          "awslogs-group": "/ecs/title-intelligence",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "backend"
        }
      }
    },
    {
      "name": "frontend",
      "image": "YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/title-intelligence/frontend:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 3000,
          "protocol": "tcp"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/title-intelligence",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "frontend"
        }
      }
    }
  ]
}
```

Register the task:

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### 4.3 Create ECS Service

```bash
aws ecs create-service \
    --cluster title-intelligence-cluster \
    --service-name title-intelligence-service \
    --task-definition title-intelligence \
    --desired-count 2 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
    --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=backend,containerPort=8000"
```

---

## Step 5: Database Migration

Run migrations after deployment:

```bash
# Connect to a running container
aws ecs execute-command \
    --cluster title-intelligence-cluster \
    --task TASK_ID \
    --container backend \
    --interactive \
    --command "/bin/bash"

# Inside the container, run migrations
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.models import Base

async def migrate():
    engine = create_async_engine('YOUR_DATABASE_URL')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Migration complete')

asyncio.run(migrate())
"

# Seed initial data
python scripts/seed.py
```

---

## Environment Variables Reference

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes | `postgresql+asyncpg://user:pass@host:5432/db` |
| `JWT_SECRET` | 64-char secret for JWT tokens | Yes | Generate with `secrets.token_urlsafe(64)` |
| `DEBUG` | Debug mode (must be false in prod) | Yes | `false` |
| `CORS_ORIGINS` | Allowed frontend origins | Yes | `["https://your-domain.com"]` |
| `STORAGE_PROVIDER` | Storage backend | Yes | `s3` |
| `S3_BUCKET` | S3 bucket name | Yes | `your-bucket-name` |
| `S3_ACCESS_KEY` | AWS access key | Yes | AWS access key ID |
| `S3_SECRET_KEY` | AWS secret key | Yes | AWS secret access key |
| `S3_REGION` | AWS region | Yes | `us-east-1` |
| `GOOGLE_API_KEY` | Gemini API key | Yes | Your Google API key |
| `AI_PROVIDER` | AI provider | No | `gemini` (default) |
| `PIPELINE_BACKEND` | Pipeline backend | No | `background_tasks` |
| `PIPELINE_MODE` | Pipeline processing mode | No | `native_pdf` |

---

## Performance Tuning for 100+ Packets (200-500 pages)

### Recommended ECS Configuration

```json
{
  "cpu": "4096",
  "memory": "8192"
}
```

### Environment Variables for High Volume

```bash
NATIVE_PDF_BATCH_SIZE=25
NATIVE_PDF_CONCURRENCY=16
TRIAGE_CONCURRENCY=6
EXAMINER_BATCH_SIZE=15
EXAMINER_BATCH_SIZE_TEXT=30
```

### Auto Scaling Policy

```bash
aws application-autoscaling register-scalable-target \
    --service-namespace ecs \
    --resource-id service/title-intelligence-cluster/title-intelligence-service \
    --scalable-dimension ecs:service:DesiredCount \
    --min-capacity 2 \
    --max-capacity 10

aws application-autoscaling put-scaling-policy \
    --service-namespace ecs \
    --resource-id service/title-intelligence-cluster/title-intelligence-service \
    --scalable-dimension ecs:service:DesiredCount \
    --policy-name cpu-scaling \
    --policy-type TargetTrackingScaling \
    --target-tracking-scaling-policy-configuration '{
      "TargetValue": 70.0,
      "PredefinedMetricSpecification": {
        "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
      },
      "ScaleOutCooldown": 60,
      "ScaleInCooldown": 300
    }'
```

---

## Monitoring & Logging

### CloudWatch Alarms

```bash
# CPU utilization alarm
aws cloudwatch put-metric-alarm \
    --alarm-name title-intelligence-high-cpu \
    --metric-name CPUUtilization \
    --namespace AWS/ECS \
    --statistic Average \
    --period 300 \
    --threshold 80 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --alarm-actions arn:aws:sns:us-east-1:YOUR_ACCOUNT:alerts

# Error rate alarm
aws cloudwatch put-metric-alarm \
    --alarm-name title-intelligence-errors \
    --metric-name 5XXError \
    --namespace AWS/ApplicationELB \
    --statistic Sum \
    --period 60 \
    --threshold 10 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 1 \
    --alarm-actions arn:aws:sns:us-east-1:YOUR_ACCOUNT:alerts
```

---

## Security Checklist

- [ ] JWT_SECRET is unique and stored in Secrets Manager
- [ ] DEBUG=false in production
- [ ] CORS_ORIGINS only includes your domain
- [ ] RDS is in private subnet with security group restrictions
- [ ] S3 bucket has proper IAM policies
- [ ] All secrets stored in AWS Secrets Manager
- [ ] HTTPS enforced via ALB/CloudFront
- [ ] Security groups restrict access appropriately
- [ ] Enable AWS WAF for additional protection

---

## Backup Strategy

1. **Database**: RDS automated backups (7-day retention)
2. **S3**: Enable versioning and cross-region replication
3. **Secrets**: Export secrets manager backup periodically

---

## Support

For issues with AWS deployment, contact your AWS Solutions Architect or refer to:
- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/)
- [AWS RDS Documentation](https://docs.aws.amazon.com/rds/)
- [AWS S3 Documentation](https://docs.aws.amazon.com/s3/)
