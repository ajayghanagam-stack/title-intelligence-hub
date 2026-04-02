{
  "family": "{{PREFIX}}-backend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "2048",
  "memory": "4096",
  "executionRoleArn": "{{TASK_EXEC_ROLE_ARN}}",
  "taskRoleArn": "{{TASK_ROLE_ARN}}",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "{{ECR_BACKEND}}:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "STORAGE_PROVIDER", "value": "s3"},
        {"name": "S3_BUCKET", "value": "{{S3_BUCKET}}"},
        {"name": "S3_REGION", "value": "{{REGION}}"},
        {"name": "PIPELINE_BACKEND", "value": "background_tasks"},
        {"name": "AI_PROVIDER", "value": "gemini"},
        {"name": "CORS_ORIGINS", "value": "[\"http://{{ALB_DNS}}\"]"},
        {"name": "DEBUG", "value": "false"}
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:ssm:{{REGION}}:{{ACCOUNT_ID}}:parameter/{{PREFIX}}/database-url"
        },
        {
          "name": "JWT_SECRET",
          "valueFrom": "arn:aws:ssm:{{REGION}}:{{ACCOUNT_ID}}:parameter/{{PREFIX}}/jwt-secret"
        },
        {
          "name": "GOOGLE_API_KEY",
          "valueFrom": "arn:aws:ssm:{{REGION}}:{{ACCOUNT_ID}}:parameter/{{PREFIX}}/google-api-key"
        },
        {
          "name": "ANTHROPIC_API_KEY",
          "valueFrom": "arn:aws:ssm:{{REGION}}:{{ACCOUNT_ID}}:parameter/{{PREFIX}}/anthropic-api-key"
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
          "awslogs-group": "/ecs/{{PREFIX}}-backend",
          "awslogs-region": "{{REGION}}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
