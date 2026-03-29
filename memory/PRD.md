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

### Full Search vs Current Owner Search Differentiation (DONE)
- **Current Owner Search**: Fetches tax/property appraiser data only, skips deep clerk search (~9s)
- **Full Search**: Fetches tax data + full clerk record search (~22s)
- PDF reports: Full Search includes Chain of Title section, Current Owner doesn't

### PDF Report Generation (DONE)
- Logikality orange branding (RGB 230,126,34) with white text headers
- Logo from SVG source (Logo_withTagline.svg converted to high-res PNG)
- 12 sections: Property Info, Vesting Deed, Reference of Legal Description, Chain of Title, Mortgage, Judgment & Liens, Tax Info (with installment table), Exceptions/Easements, Miscellaneous, Legal Description, Names Search, Additional Comments

### Portal Registry (DONE)
- **30+ Phenix.net tax portals**: Hendry, Lee, Collier, Charlotte, Sarasota, Manatee, etc.
- **8 Acclaim clerk portals**: Duval, Hillsborough, Volusia, Bay, Nassau, St. Johns, Clay, Putnam
- **1 Property Appraiser portal**: Duval (COJ paopropertysearch.coj.net)

### CAPTCHA Handling (DONE)
- CAPTCHA detection for Cloudflare, reCAPTCHA, hCaptcha, Turnstile
- Retry logic with exponential backoff (2 retries)
- Automatic flag generation when CAPTCHA blocks clerk access
- Sources marked with `captcha_blocked: true` and `manual_retrieval: true`

### Frontend UI (DONE)
- Order list with readable status filters (All, Pending, Processing, Review Required, Completed, Failed)
- New order form with Product Type dropdown (Full Search / Current Owner Search)
- Order detail with tabbed navigation (Overview, Documents, Chain, Flags, Package)
- Live pipeline progress tracker with auto-refresh
- Download PDF button for completed orders
- data-testid attributes throughout

## Tested Counties
- **Hendry County, FL** (870 Friendship Cir, Labelle FL 33935) - Full Search ✅
- **Duval County, FL** (4471 Sherman Hills Pkwy, Jacksonville FL 32210) - Full + COS ✅

## Authentication
- Email/password login (admin@societytitle.com / admin123)
- JWT token-based auth with org context

## Key API Endpoints
- POST /api/v1/apps/title-search/orders (Create order)
- POST /api/v1/apps/title-search/orders/{id}/process (Start pipeline)
- GET /api/v1/apps/title-search/orders/{id}/pipeline (Pipeline status)
- GET /api/v1/apps/title-search/orders/{id}/package/pdf (Download PDF)
- GET /api/v1/apps/title-search/orders/{id}/documents (Documents list)
- GET /api/v1/apps/title-search/orders/{id}/chain (Chain of title)
- GET /api/v1/apps/title-search/orders/{id}/flags (Flags list)

## Prioritized Backlog
### P2 - Future
- Batch order processing
- Admin portal configuration UI for adding new county portals
- Expand to non-Florida counties
- Human-in-the-loop UI for CAPTCHA-blocked portals (manual upload)
