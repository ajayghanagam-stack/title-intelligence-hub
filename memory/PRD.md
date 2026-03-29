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
- ECS/EC2 deployment with Docker, RDS PostgreSQL, S3 storage
- Shutdown/startup scripts for cost management

### Title Search Pipeline (DONE)
- Real county data fetching via Playwright + ArcGIS APIs
- **Hendry County, FL**: Phenix.net tax collector portal
- **Duval County, FL**: COJ Property Appraiser (paopropertysearch.coj.net)
- AI document parsing, chain-of-title construction, flag detection

### Full Search vs Current Owner Search (DONE)
- **Current Owner**: Tax/property data only, skips clerk (~9s)
- **Full Search**: Tax + clerk records, builds full chain (~22s)

### PDF Report (DONE — Logikality Branded)
- **Orange headers** (RGB 230,126,34) with white text
- **Logo**: SVG-sourced high-res PNG (Logo_withTagline.svg)
- 12 sections matching sample: Property Info, Vesting Deed, Reference of Legal Description, Chain of Title, Mortgage, Judgment & Liens, Tax Info (installment table), Exceptions/Easements, Miscellaneous, Legal Description, Names Search, Additional Comments
- Tax Year / Assessment Year populated (e.g. 2025)
- Tax Status populated (e.g. "Paid")
- Total/Just Market Value shown
- Chain entries have Book/Page numbers
- Plat references in Miscellaneous section
- Names Search includes all parties + subdivision

### Portal Registry (DONE)
- 30+ Phenix.net tax portals (FL counties)
- 8 Acclaim clerk portals (Duval, Hillsborough, Volusia, Bay, Nassau, St. Johns, Clay, Putnam)
- 1 Property Appraiser portal (Duval COJ)

### CAPTCHA Handling (DONE)
- Detection for Cloudflare, reCAPTCHA, hCaptcha, Turnstile
- Retry logic with exponential backoff
- Auto-flag generation for blocked portals

### Frontend (DONE)
- Order list with status filters
- New order form with product type selection
- Order detail: tabbed navigation, live pipeline progress, PDF download
- Documents tab: meaningful names (e.g. "Special Warranty Deed — to PITTS DERRICK R — ($259,000)")
- data-testid attributes throughout

## Known PDF Gaps (Data Source Limitations)
These require clerk deed text which property appraisers don't provide:
- Grantor names on vesting/chain deeds (property appraiser only has grantee/current owner)
- Full legal description in deed language (only raw parcel format available)
- Mortgage details (borrower, lender, loan amount — recorded at clerk only)

## Prioritized Backlog
### P2 - Future
- Batch order processing (CSV upload)
- Human-in-the-loop CAPTCHA fallback UI (manual document upload)
- Expand scraper coverage to more FL county portal systems
- Non-Florida county support
