# Title Intelligence Hub - PRD

## Original Problem Statement
Deploy the existing Title Intelligence Hub application and share the URL for testing.

## Application Overview
Title Intelligence Hub is a multi-tenant SaaS platform for AI-powered title document analysis with two main micro apps:
1. **Title Intelligence** - Processes title commitment PDFs through AI pipeline
2. **Title Search & Abstracting** - Automated county record searches and chain-of-title construction

## Tech Stack
- **Backend**: FastAPI + SQLAlchemy (async) + SQLite (dev)
- **Frontend**: Next.js 14 + TypeScript + Tailwind CSS + shadcn/ui
- **AI**: Gemini via litellm (configurable)
- **Auth**: JWT-based local authentication

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

## What's Been Implemented
- [2026-03-28] Initial deployment to Emergent platform
  - Configured SQLite database for preview environment
  - Created backend server wrapper for supervisor compatibility
  - Built and deployed Next.js frontend
  - Seeded admin user and micro apps
  - Verified login and admin dashboard working

## Prioritized Backlog

### P0 - Critical
- None currently

### P1 - High Priority
- AI integration setup (requires GOOGLE_API_KEY for Gemini)
- Create test customer account with micro app subscription
- Test full document processing pipeline

### P2 - Medium Priority
- UI/UX improvements (as requested by user)
- Additional features (to be specified)

## Next Tasks
1. User to test the deployed application
2. Gather specific feature requests and bug reports
3. Set up AI integration (Gemini API key required for document processing)
