# Title Intelligence Hub - PRD

## Original Problem Statement
Build a multi-tenant SaaS platform with two micro apps:
1. **Title Intelligence** — AI-powered title commitment analysis from uploaded PDFs
2. **Title Search & Abstracting** — Automated property record retrieval from county portals, AI parsing, chain-of-title construction, and report generation

## Tech Stack
- **Backend**: FastAPI + SQLAlchemy (async) + SQLite (dev) / PostgreSQL (prod)
- **Frontend**: Next.js 14 + TypeScript + Tailwind CSS + shadcn/ui
- **AI**: Gemini via litellm
- **Cloud**: AWS (ECS, ALB, RDS, S3, ECR)
- **Scraping**: Playwright (county portal automation)

## What's Been Implemented

### Title Intelligence (COMPLETE)
- PDF upload and AI processing pipeline
- Document viewer with on-demand thumbnails
- Risk flag detection and review
- Readiness dashboard
- Report generation

### Title Search & Abstracting (IN PROGRESS)
- [2026-03-29] Real county portal integration built:
  - US Census Geocoder API (address → county + FIPS code)
  - Hendry County FL tax collector (Phenix.net) — real Playwright scraping
  - Florida clerk portal detection (CAPTCHA-blocked portals flagged for manual retrieval)
  - Acclaim/OnCore clerk scrapers (Duval County etc.)
- [2026-03-29] Pipeline working end-to-end with real data:
  - order → geocode → retrieve (real portal data) → parse → chain (AI) → package → complete
  - Tested with 870 Friendship Cir, Labelle, FL 33935
  - Returns: owner (WJHFL LLC), parcel (2084329-01000000440), legal description, tax data, chain analysis
- [2026-03-29] Fixed UUID handling in chain stage, made county/state optional (geocoded automatically)

### AWS Deployment (COMPLETE - currently shut down to save costs)
- ALB: title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com
- Shutdown/Startup scripts at /app/scripts/

## Prioritized Backlog

### P0 - Critical (Title Search)
- PDF report generation matching sample format (Logikality branding)
- UI redesign for Title Search pages (order creation, pipeline progress, report preview)
- Support more tax collector portals (currently Hendry FL only)

### P1 - High Priority
- Add more county portal adapters (expand portal registry)
- Support Current Owner Search scope (vs Full Search)
- Manual retrieval workflow for CAPTCHA-blocked portals
- SSL/HTTPS + custom domain for AWS

### P2 - Medium
- Admin UI for managing county portal configurations
- Batch order processing
- Export functionality
- CloudWatch monitoring

## Architecture Notes
- County portal integration uses API-first approach (REST APIs when available)
- Falls back to Playwright scraping for portals without APIs
- CAPTCHA-blocked portals flagged as "manual_retrieval_needed" with TAFlag
- County registry expandable: add portal URL + platform type per county
- Phenix.net adapter covers many Florida tax collectors
- Acclaim/OnCore adapter covers many US clerk portals
