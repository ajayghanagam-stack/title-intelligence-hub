from pathlib import Path

content = r"""# AWS Migration Plan for Current Application

## Purpose

This document is the working migration guide for moving the current application from Hetzner to AWS in controlled phases.

It is written for practical execution with Claude Code and is designed to help us:

- migrate safely without breaking the existing application
- avoid overengineering early
- keep each phase reviewable and testable
- maintain a clear rollback path
- document architecture, infra, risks, and validation steps

This plan assumes the current stack is:

### Backend
- Python 3.12
- FastAPI
- SQLAlchemy 2.0 async
- Pydantic
- PostgreSQL 16 using asyncpg
- Alembic migrations
- Tesseract OCR via pytesseract
- fpdf2
- LiteLLM with multi-provider AI support
- Temporal optional

### Frontend
- Next.js 14 App Router
- React 18
- TypeScript 5
- Tailwind CSS
- Zustand
- Lucide React

### Infrastructure
- Docker and Docker Compose
- Caddy reverse proxy
- GitHub Actions CI/CD
- GHCR
- Hetzner VPS

### Storage
- Local filesystem or S3-compatible storage through StorageProvider abstraction

---

## Migration Philosophy

We will not jump straight into a full AWS-native redesign.

We will migrate in phases:

1. **Phase 1: Lift and shift to AWS**
   - Keep architecture close to current setup
   - Deploy on EC2 with Docker Compose
   - Move database to RDS PostgreSQL
   - Move files to S3
   - Keep Caddy initially

2. **Phase 2: Secure and operationalize**
   - Move images to ECR
   - Use Secrets Manager
   - Add CloudWatch logs and monitoring
   - Use ACM and Route 53 for HTTPS and DNS

3. **Phase 3: Split frontend and backend cleanly**
   - Move Next.js frontend to Amplify Hosting
   - Move FastAPI backend to ECS Fargate
   - Reduce dependency on a single VM

4. **Phase 4: Harden for production AI and OCR workloads**
   - Add ALB
   - Add autoscaling
   - Separate long-running OCR and AI jobs from request-response traffic
   - Introduce workflow orchestration only where truly needed

---

## AWS Services in Layman Terms

### EC2
A virtual machine in AWS.  
Think of it like renting a cloud computer similar to a VPS.

### RDS PostgreSQL
A managed PostgreSQL database.  
AWS runs the database for us so we do not have to do backups and admin manually.

### S3
Cloud file storage.  
Used for uploaded documents, generated PDFs, OCR artifacts, and export files.

### ECR
AWS container registry.  
This stores Docker images inside AWS.

### ECS Fargate
Managed container hosting.  
Instead of logging into a server and running Docker ourselves, AWS runs the containers for us.

### Amplify Hosting
Easy hosting for frontend applications from GitHub.  
Good fit for the Next.js frontend.

### Route 53
AWS DNS.  
This maps our domain name to AWS-hosted services.

### ACM
Managed SSL certificates.  
Used for HTTPS.

### Secrets Manager
A safe place for API keys, passwords, and sensitive credentials.

### CloudWatch
Logs, dashboards, metrics, and alarms.  
Used for visibility and troubleshooting.

### Application Load Balancer
Traffic router in front of backend services.  
Sends incoming traffic to healthy backend targets.

---

## Phase Plan

## Phase 1: Lift and Shift to AWS

### Goal
Run the existing application on AWS with minimum architectural change.

### Target Architecture
- 1 EC2 instance
- Docker Compose running:
  - Caddy
  - frontend container
  - backend container
- RDS PostgreSQL
- S3 bucket for file storage
- GitHub Actions deploys to EC2

### What changes in the app
- database connection points to RDS
- storage provider points to S3 instead of local disk where possible
- environment variables updated for AWS deployment
- keep Caddy in front for reverse proxy and routing

### Deliverables
- infrastructure inventory of current app
- `.env.aws.example`
- updated Docker Compose for AWS deployment
- backend config changes for RDS and S3
- deployment runbook
- rollback plan
- smoke test checklist

### Risks
- networking/security group issues
- PostgreSQL connectivity issues
- S3 permissions misconfiguration
- OCR dependencies missing in container
- DNS and HTTPS setup confusion

### Done criteria
- app loads from AWS endpoint
- backend healthcheck passes
- DB migrations run successfully
- upload and download work
- OCR processing works
- AI provider calls work
- generated PDFs work
- no hardcoded Hetzner assumptions remain

---

## Phase 2: Secure and Operationalize

### Goal
Make the deployment safer and easier to manage.

### Target Architecture
- EC2 continues temporarily
- images pushed to ECR
- secrets moved to Secrets Manager
- logs shipped to CloudWatch
- domain managed with Route 53
- SSL managed by ACM where applicable

### What changes
- GitHub Actions updated to push images to ECR
- deployment process pulls from ECR
- secrets pulled securely
- CloudWatch log shipping enabled
- alerting and dashboards added
- documented operational checks added

### Deliverables
- ECR repositories
- GitHub Actions updates
- secrets inventory and secret migration plan
- CloudWatch logging setup
- basic alerting plan
- production deployment checklist

### Done criteria
- images are stored in ECR
- app no longer depends on plaintext secrets on server
- key logs are viewable centrally
- domain and HTTPS work cleanly
- deployment steps are documented and repeatable

---

## Phase 3: Split Frontend and Backend

### Goal
Move frontend and backend to the AWS services that best fit them.

### Target Architecture
- frontend on Amplify Hosting
- backend on ECS Fargate
- RDS PostgreSQL
- S3 storage
- DNS and HTTPS configured
- Caddy removed or minimized
- backend traffic fronted by ALB

### What changes
- frontend deployment decoupled from backend deployment
- backend container deployment moved from EC2 to ECS
- networking and service discovery updated
- CORS and API base URLs updated
- CI/CD split into frontend pipeline and backend pipeline

### Deliverables
- frontend deploy guide for Amplify
- backend deploy guide for ECS Fargate
- updated CI/CD pipelines
- environment and domain strategy
- cutover plan
- rollback plan

### Done criteria
- frontend builds and deploys from GitHub to Amplify
- backend runs on ECS Fargate
- frontend can call backend successfully
- auth, upload, OCR, AI calls, and PDF generation work
- production DNS points to AWS-managed services
- old EC2-based entrypoint can be retired

---

## Phase 4: Production Hardening for AI Native Workloads

### Goal
Make the platform reliable for real OCR, AI, and document-processing workloads.

### Target Architecture
- frontend on Amplify
- backend services on ECS Fargate
- ALB in front of backend
- async workers for OCR and heavy jobs
- autoscaling policies
- CloudWatch dashboards and alarms
- structured logging
- optional workflow orchestration only if needed

### What changes
- separate synchronous API traffic from async heavy workloads
- add job processing design for OCR and long-running AI tasks
- introduce better retry handling
- add scaling policies
- add operational dashboards and SLOs
- evaluate if Temporal remains needed

### Deliverables
- worker architecture design
- job queue or orchestration recommendation
- observability plan
- performance test plan
- capacity plan
- incident response notes

### Done criteria
- long-running jobs do not block user requests
- backend scales under load
- logs and metrics support debugging
- failure and retry behavior are defined
- system has a documented operating model

---

## Execution Rules for Claude Code

When working from this document, Claude Code must follow these rules:

1. Do not implement all phases at once.
2. Work on only one phase at a time.
3. Before making changes, inspect the current repository and summarize:
   - current architecture
   - deployment approach
   - environment assumptions
   - missing information
4. For each phase, first produce:
   - objective
   - scope
   - assumptions
   - risks
   - proposed file changes
   - validation plan
5. After that, implement only the approved scope for that phase.
6. Keep all changes modular, reviewable, and production-conscious.
7. Avoid overengineering the MVP migration.
8. Prefer minimal-change migration before AWS-native redesign.
9. At the end of each phase, update this document with:
   - what was completed
   - what remains
   - commands to run
   - known issues
   - rollback steps
10. Never silently change infrastructure assumptions. Always document them.

---

## Master Prompt for Claude Code

Use the following prompt in Claude Code.

```text
Act as a disciplined senior cloud architect, DevOps engineer, and application modernization lead.

You are helping migrate this application from Hetzner to AWS in controlled phases.

You must use AWS_Migration.md in the repository root as the source of truth for the migration plan and phase sequencing.

Important operating rules:
- Do not attempt all phases together.
- Work on only one phase at a time.
- Before changing anything, inspect the repository and summarize the current state relevant to the target phase.
- Keep migration low risk, reviewable, and production-conscious.
- Prefer minimal-change migration before AWS-native redesign.
- Do not overengineer the solution.
- Do not introduce services that are unnecessary for the current phase.
- At the end of each phase, update AWS_Migration.md with progress, commands, known limitations, and next steps.

For every phase, follow this exact sequence:
1. Read AWS_Migration.md and identify the current target phase.
2. Inspect the repository, deployment files, Docker setup, CI/CD, env handling, storage setup, backend config, frontend config, and any infrastructure docs.
3. Capture and structure the requirements for that phase.
4. Identify assumptions, risks, and unknowns.
5. Propose the architecture and deployment design for that phase only.
6. List files to create or update.
7. Implement only that phase.
8. Include:
   - files created or updated
   - explanation of design choices
   - environment variable changes
   - infrastructure assumptions
   - commands to run locally
   - commands to deploy
   - validation steps
   - smoke tests
   - rollback steps
   - known limitations
9. Add or update tests where applicable.
10. Update AWS_Migration.md with a completion checklist for that phase.

Current migration objective:
Start with Phase 1 only unless the repository already shows that Phase 1 is completed.

Phase 1 target:
- deploy the current application on AWS EC2 with minimal architectural change
- use RDS for PostgreSQL
- use S3 for storage
- keep Docker Compose and Caddy initially
- adapt GitHub Actions as needed
- document every assumption clearly

When you respond:
- first give a concise assessment of the current repo state for Phase 1
- then give a plan
- then implement in small reviewable steps
- do not skip documentation
