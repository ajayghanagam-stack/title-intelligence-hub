# Title Intelligence Platform - PRD

## Original Problem Statement
Build a title search and abstracting platform (Logikality / Society Title) that:
1. Integrates with real county portals to fetch property, tax, and clerk records
2. Uses AI to parse documents, build chain of title, and detect flags
3. Generates professional PDF abstract reports matching Logikality-branded sample formats
4. Provides a clean UI for order management, pipeline tracking, and report download

## Core Architecture
- **Frontend**: Next.js (React) with Tailwind CSS, Shadcn UI
- **Backend**: FastAPI (Python) with SQLAlchemy ORM
- **Database**: SQLite (preview) / PostgreSQL RDS (production)
- **Scraping**: Playwright (headless browser) for county portals
- **AI**: Emergent LLM Key for document parsing and chain analysis
- **Storage**: Local (preview) / AWS S3 (production)

## What's Been Implemented

### AWS Production Deployment (DONE - Shut Down)
- ECS/EC2 deployment with Docker
- RDS PostgreSQL with migrations
- S3 storage integration
- Shutdown/startup scripts for cost management

### Title Search Pipeline (DONE)
- Real county data fetching via Playwright + ArcGIS APIs
- **Hendry County, FL**: Phenix.net tax collector portal scraper
- **Duval County, FL**: COJ Property Appraiser scraper (paopropertysearch.coj.net)
- AI document parsing (source resolvers, chain builders)
- Chain-of-title construction with gap detection
- Flag generation (critical/medium severity)
- PDF abstract report generation (Logikality-branded format)

### PDF Report Sections (DONE)
- Property Information
- Vesting Deed Information
- Reference of Legal Description
- Chain of Title (Full Search only)
- Deed of Trust/Mortgage Information
- Judgment & Lien's Information
- Tax Information (with installment table)
- Exceptions/Easements Documents
- Miscellaneous Documents
- Legal Description
- Names Search
- Additional Comments

### Frontend UI (DONE)
- Order list with status filters (All, Pending, Processing, Review Required, Completed, Failed)
- New order creation form
- Order detail with tabbed navigation (Overview, Documents, Chain, Flags, Package)
- Live pipeline progress tracker (6 stages with real-time polling)
- Download PDF button on completed orders
- Breadcrumbs navigation
- data-testid attributes throughout

## Tested Counties
- **Hendry County, FL** (870 Friendship Cir, Labelle FL 33935) ✅
- **Duval County, FL** (4471 Sherman Hills Pkwy, Jacksonville FL 32210) ✅

## Prioritized Backlog

### P1 - Upcoming
- Full Search vs Current Owner Search differentiation in data fetching logic
- Expand portal registry to more Florida counties

### P2 - Future
- CAPTCHA handling / human-in-the-loop fallback for blocked clerk portals
- Batch order processing
- Admin portal configuration UI
- Expand to non-Florida counties

## Authentication
- Email/password login (admin@societytitle.com / admin123)
- JWT token-based auth with org context

## Key API Endpoints
- POST /api/v1/apps/title-search/orders (Create order)
- POST /api/v1/apps/title-search/orders/{id}/process (Start pipeline)
- GET /api/v1/apps/title-search/orders/{id}/pipeline (Pipeline status)
- GET /api/v1/apps/title-search/orders/{id}/package/pdf (Download PDF)
