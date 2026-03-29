# Title Intelligence Platform - PRD

## Original Problem Statement
Build and refine the "Title Search and Abstracting" micro-app to process real US addresses via county portals. Generate PDF abstract reports matching Logikality branding. Support Full Search vs Current Owner Search workflows. Nationwide portal coverage with auto-discovery.

## Core Architecture
- **Frontend**: Next.js (port 3000)
- **Backend**: FastAPI (port 8001)
- **Database**: PostgreSQL (SQLAlchemy async)
- **AI**: Emergent LLM Key (Gemini/OpenAI/Claude)
- **Scraping**: Playwright (Headless)
- **PDF**: fpdf2

## What's Been Implemented

### Phase 1 - Core Pipeline (Done)
- ArcGIS geocoding for address → county resolution
- Phenix tax collector portal scraper (30+ FL counties)
- Duval County Property Appraiser scraper
- Acclaim Clerk of Court scraper (8 FL counties with Kendo UI)
- AI document classification and chain-of-title building
- Logikality-branded PDF generation (Full Search + Current Owner)

### Phase 2 - Data Quality (Done)
- Closed 7 major data gaps comparing to manual abstractor samples
- Full Search vs Current Owner scoping logic
- Document naming with doc_metadata
- UI redesign with status filters and data-testids

### Phase 3 - Cosmetic Polish (Done 03/29/2026)
- Orders list pagination (10/page, latest first, prev/next)
- PDF vertical borders removed (clean horizontal-only layout)
- PDF logo swapped to Logo_rev_no-tagline.svg

### Phase 4 - Nationwide Coverage (Done 03/29/2026)
- AI portal discovery via PortalDiscoveryAgent (finds property appraiser + clerk portals)
- TACountySource DB caching for discovered portals (no repeat discovery)
- GenericPortalScraper: Playwright-based scraper for any discovered portal URL
- AI data extraction from generic portal HTML (PropertyDataExtractorAgent)
- CAPTCHA-blocked portals flagged for review instead of failing pipeline
- Tested with FL, CA, TX, NY, DC addresses — all complete successfully
- Pre-configured FL portals unchanged (zero performance impact)

## Key Models
- `ta_orders`: id, org_id, status, property_address, county, state_code, search_scope
- `ta_documents`: id, order_id, doc_type, raw_content, doc_metadata
- `ta_chain_links`: id, order_id, grantor, grantee
- `ta_flags`: id, order_id, title, severity, flag_type
- `ta_county_sources`: county, state_code, source_type, portal_url, is_active (discovery cache)

## Key API Endpoints
- POST /api/v1/apps/title-search/orders
- POST /api/v1/apps/title-search/orders/{id}/process
- GET /api/v1/apps/title-search/orders/{id}/package/pdf

## Prioritized Backlog
### P1 - Next
- Batch order processing (CSV upload for bulk orders)
- Human-in-the-loop CAPTCHA fallback UI (manual document upload to resume pipeline)

### P2 - Future
- Improve generic scraper accuracy (multi-step navigation, address-specific result clicking)
- Expand pre-configured portals for high-volume counties (Miami-Dade, Broward, Palm Beach, Orange)
- AWS production re-deployment
