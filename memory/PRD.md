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

### Title Search Pipeline (DONE)
- Real county data fetching via Playwright + ArcGIS APIs
- **Hendry County, FL**: Phenix.net tax collector portal
- **Duval County, FL**: COJ Property Appraiser + Acclaim Clerk of Court
- AI document parsing, chain-of-title construction, flag detection

### Acclaim Clerk Scraper (DONE — Enhanced)
- Handles full Kendo UI workflow: disclaimer → name search → checkbox tree → Done → results
- Extracts: grantor/grantee names, instrument numbers, book/page, consideration, doc types, legal descriptions
- CAPTCHA detection with retry logic and fallback flagging
- Supports 8 Florida counties: Duval, Hillsborough, Volusia, Bay, Nassau, St. Johns, Clay, Putnam

### Full Search vs Current Owner Search (DONE)
- **Current Owner**: Tax/property data only, skips clerk (~9s)
- **Full Search**: Tax + full clerk records, builds chain (~30s)

### PDF Report (DONE — All Gaps Closed)
- Logikality orange branding (RGB 230,126,34) with white text headers
- SVG-sourced logo (Logo_withTagline.svg)
- 12 sections matching sample exactly
- ALL data populated from real sources:
  - Vesting deed with grantor (D R HORTON INC) and grantee names
  - Full Book/Page and Instrument numbers
  - Tax Year 2025, Assessment Year 2025, Status "Paid"
  - Full legal description from clerk records
  - Mortgage details: Borrower, Lender, Loan Amount, Book/Page
  - Names Search with all parties from chain
  - Plat reference in Miscellaneous Documents
- Proper page break handling (no field-per-page overflow)

### Frontend (DONE)
- Order list with status filters
- New order form with product type selection
- Order detail: tabbed navigation, live pipeline progress, PDF download
- Documents tab with meaningful names (deed type + party + consideration)
- "Download the Generated Report as PDF" text
- data-testid attributes throughout

## Portal Registry
- 30+ Phenix.net tax portals (FL counties)
- 8 Acclaim clerk portals (Duval, Hillsborough, Volusia, Bay, Nassau, St. Johns, Clay, Putnam)
- 1 Property Appraiser portal (Duval COJ)

## Tested Counties
- **Hendry County, FL** (870 Friendship Cir, Labelle FL 33935)
- **Duval County, FL** (4471 Sherman Hills Pkwy, Jacksonville FL 32210) — Full + COS

## Authentication
- Email/password login (admin@societytitle.com / admin123)

## Prioritized Backlog
### P0 - Completed
- Orders list pagination (10/page, latest first, prev/next) — Done 03/29/2026
- PDF vertical borders removed (clean layout) — Done 03/29/2026
- PDF logo swapped to Logo_rev_no-tagline.svg (PNG) — Done 03/29/2026

### P2 - Future
- Batch order processing (CSV upload for bulk orders)
- Human-in-the-loop CAPTCHA fallback UI (manual document upload)
- Expand scraper coverage to more FL county portal systems (Miami-Dade, Broward, Palm Beach, Orange)
- Non-Florida county support
- AWS production re-deployment
