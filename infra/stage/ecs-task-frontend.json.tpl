{
  "family": "{{PREFIX}}-frontend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "{{TASK_EXEC_ROLE_ARN}}",
  "taskRoleArn": "{{TASK_ROLE_ARN}}",
  "containerDefinitions": [
    {
      "name": "frontend",
      "image": "{{ECR_FRONTEND}}:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 3000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "NEXT_PUBLIC_API_URL", "value": "http://{{ALB_DNS}}"},
        {"name": "NODE_ENV", "value": "production"},
        {"name": "NEXT_TELEMETRY_DISABLED", "value": "1"}
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "wget -q --spider http://localhost:3000 || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 30
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/{{PREFIX}}-frontend",
          "awslogs-region": "{{REGION}}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
