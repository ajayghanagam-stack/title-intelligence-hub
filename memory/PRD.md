# Title Intelligence Hub - PRD

## Original Problem Statement
Deploy the existing Title Intelligence Hub application to AWS for production use, add new features, fix bugs, improve UI/UX, and integrate AI/LLM capabilities.

## Application Overview
Title Intelligence Hub is a multi-tenant SaaS platform for AI-powered title document analysis with two main micro apps:
1. **Title Intelligence** - Processes title commitment PDFs through AI pipeline
2. **Title Search & Abstracting** - Automated county record searches and chain-of-title construction

## Tech Stack
- **Backend**: FastAPI + SQLAlchemy (async) + SQLite (dev) / PostgreSQL (prod)
- **Frontend**: Next.js 14 + TypeScript + Tailwind CSS + shadcn/ui
- **AI**: Gemini via litellm (configurable)
- **Auth**: JWT-based local authentication
- **Cloud**: AWS (ECS EC2, ALB, RDS PostgreSQL, S3, Secrets Manager, ECR)

## User Personas
1. **Platform Admin** - Creates customer accounts, manages micro apps
2. **Processor** - Uploads title commitments, monitors processing
3. **Underwriter** - Reviews risk flags, makes decisions
4. **Attorney/Lender/Buyer** - Receives reports

## Core Requirements (Static)
- Multi-tenant architecture with org-based purchasing
- JWT authentication with role-based access control
- PDF upload and AI processing pipeline
- Risk flag detection and review workflow
- Report generation (PDF/JSON)

## Production AWS Deployment
- **ALB URL**: http://title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com
- **AWS Region**: us-east-1
- **EC2 Instance**: c6i.2xlarge (i-0ad64a5caf555cb58)
- **ECS Cluster**: title-intelligence-cluster
- **ECS Service**: title-intelligence-service (EC2 launch type)
- **RDS**: PostgreSQL (title-intelligence-db)
- **S3**: title-intelligence-storage-628913890897
- **ECR**: title-intelligence/backend, title-intelligence/frontend

## What's Been Implemented
- [2026-03-28] Full AWS production deployment completed
  - Fixed Docker architecture mismatch (ARM -> linux/amd64) in all Dockerfiles
  - Enabled ECS Exec with SSM permissions on task role
  - Ran database migrations and seeded RDS PostgreSQL
  - Created both admin accounts (Logikality platform admin + Society Title customer)
  - Reduced ALB target group draining timeout from 300s to 30s
  - Configured deployment config: minimumHealthyPercent=0 for single-instance rolling updates
  - Verified: Login, dashboard, and API health all working on production

- [Previous sessions] Local environment features
  - Configured SQLite database for preview environment
  - Google API key for Gemini extraction pipeline
  - Fixed missing fontTools dependency for PDF export
  - Fixed frontend filter state (UI flickering on Readiness Dashboard)
  - On-demand thumbnail generation and PDF memory caching
  - Replaced filename with Underwriter/Property Address in sidebar
  - Auto-refresh sidebar using Custom Events on pipeline completion
  - Reorganized UI logos (Society Title SVG)
  - Pagination on Current Analysis list

## Prioritized Backlog

### P0 - Critical
- None currently (production deployment completed)

### P1 - High Priority
- Add SSL/HTTPS via ACM certificate + ALB HTTPS listener
- Set up custom domain name
- Test full document processing pipeline on production (S3 storage)

### P2 - Medium Priority
- UI/UX improvements (as requested by user)
- Additional features (to be specified)
- CloudWatch monitoring and alarms setup
- Auto-scaling policy configuration

## Next Tasks
1. User to test the production application at the ALB URL
2. Set up SSL/HTTPS with a custom domain (optional)
3. Test document upload and AI processing pipeline on production
