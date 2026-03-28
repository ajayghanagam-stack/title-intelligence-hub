#!/bin/bash
# =============================================================================
# RUN THIS SCRIPT ON YOUR LOCAL MACHINE
# =============================================================================
# This script builds and pushes Docker images to AWS ECR
# 
# Prerequisites:
# 1. Docker installed and running
# 2. AWS CLI configured with your credentials
# 3. Clone/download the project to your local machine
# =============================================================================

set -e

# Configuration (already set up in AWS)
export AWS_REGION="us-east-1"
export AWS_ACCOUNT_ID="628913890897"
export APP_NAME="title-intelligence"
export ALB_DNS="title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com"

echo "================================================"
echo "Building and Pushing Docker Images to AWS ECR"
echo "================================================"

# Step 1: Login to ECR
echo ""
echo "Step 1: Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | \
    docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

echo "✅ Logged in to ECR"

# Step 2: Build Backend Image
echo ""
echo "Step 2: Building Backend Image..."
cd backend
docker build -t ${APP_NAME}/backend:latest .
docker tag ${APP_NAME}/backend:latest \
    ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest

echo "✅ Backend image built"

# Step 3: Push Backend Image
echo ""
echo "Step 3: Pushing Backend Image to ECR..."
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/backend:latest

echo "✅ Backend image pushed"

# Step 4: Build Frontend Image
echo ""
echo "Step 4: Building Frontend Image..."
cd ../frontend

# Build with the ALB DNS as the API URL
docker build \
    --build-arg NEXT_PUBLIC_API_URL=http://${ALB_DNS} \
    -t ${APP_NAME}/frontend:latest .

docker tag ${APP_NAME}/frontend:latest \
    ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest

echo "✅ Frontend image built"

# Step 5: Push Frontend Image
echo ""
echo "Step 5: Pushing Frontend Image to ECR..."
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${APP_NAME}/frontend:latest

echo "✅ Frontend image pushed"

echo ""
echo "================================================"
echo "✅ ALL IMAGES PUSHED SUCCESSFULLY!"
echo "================================================"
echo ""
echo "Next step: Come back to the Emergent chat to continue"
echo "with ECS service creation."
