#!/bin/bash
# =============================================================================
# AWS DEPLOYMENT SCRIPT - Part 3: Database Migration & Final Setup
# =============================================================================

set -e

export AWS_REGION="us-east-1"
export APP_NAME="title-intelligence"

# -----------------------------------------------------------------------------
# STEP 13: RUN DATABASE MIGRATIONS
# -----------------------------------------------------------------------------

echo "Running database migrations..."

# Get the running task
TASK_ARN=$(aws ecs list-tasks \
    --cluster ${APP_NAME}-cluster \
    --service-name ${APP_NAME}-service \
    --query 'taskArns[0]' \
    --output text)

echo "Task ARN: ${TASK_ARN}"

# Execute migration command in the container
aws ecs execute-command \
    --cluster ${APP_NAME}-cluster \
    --task ${TASK_ARN} \
    --container backend \
    --interactive \
    --command "python -c \"
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
    print('Migration complete')

asyncio.run(migrate())
\""

echo "Migrations complete."

# -----------------------------------------------------------------------------
# STEP 14: SEED INITIAL DATA
# -----------------------------------------------------------------------------

echo "Seeding initial data..."

aws ecs execute-command \
    --cluster ${APP_NAME}-cluster \
    --task ${TASK_ARN} \
    --container backend \
    --interactive \
    --command "python scripts/seed.py"

echo "Database seeded."

# -----------------------------------------------------------------------------
# STEP 15: VERIFY DEPLOYMENT
# -----------------------------------------------------------------------------

echo "Verifying deployment..."

ALB_DNS=$(aws elbv2 describe-load-balancers \
    --names ${APP_NAME}-alb \
    --query 'LoadBalancers[0].DNSName' \
    --output text)

echo "Testing health endpoint..."
curl -s http://${ALB_DNS}/api/v1/health

echo ""
echo "=========================================="
echo "DEPLOYMENT VERIFICATION COMPLETE!"
echo "=========================================="
echo ""
echo "Your application is live at:"
echo "URL: http://${ALB_DNS}"
echo ""
echo "Login credentials (from seed):"
echo "Platform Admin: admin@logikality.com / admin123"
echo "Customer Admin: admin@societytitle.com / admin123"
echo ""
echo "IMPORTANT: Change these passwords in production!"
