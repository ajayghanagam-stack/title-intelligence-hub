# PRD — Title Search & Abstracting Micro App

> **Classification**: Internal — Engineering Reference
> **Last Updated**: 2026-03-23
> **Status**: v1.0 — Draft

---

## 1. Overview

Title Search & Abstracting automates the process of searching county recorder, clerk of courts, and assessor databases to pull deeds, mortgages, judgments, liens, HOA records, and easements. AI agents parse documents, identify chain-of-title gaps, flag anomalies, and generate structured abstract/search packages summarizing full ownership history. Counties lacking digital records are routed for ground abstractor deployment.

**Target metric**: Reduce average title search from 3–7 business days (manual) to under 2 hours for digitally-available counties, with 90%+ accuracy on chain-of-title construction.

### Core Value Proposition

| Without Title Search & Abstracting | With Title Search & Abstracting |
|---|---|
| Manual searches across multiple county systems | AI agents auto-pull from digital county sources |
| Days spent reading and summarizing deeds/liens | LLMs parse and summarize documents in minutes |
| Chain-of-title gaps discovered late in closing | Gaps flagged immediately during search |
| No standardized abstract format | Consistent structured search packages every time |
| All counties require same manual effort | Digital counties automated; manual effort reserved for non-digital only |
| Abstractor availability bottlenecks | Ground abstractors dispatched only when needed |

### User Roles & Workflows

| Role | What They Do |
|---|---|
| **Title Officer** | Orders searches, reviews abstract packages, approves chain-of-title |
| **Abstractor** | Reviews AI-generated abstracts, handles exception documents, verifies chain |
| **Ground Abstractor** | Dispatched to non-digital counties, uploads physical records |
| **Admin** | Manages county source configs, monitors search throughput, assigns ground abstractors |

---

## 2. User Stories & Acceptance Criteria

### 2.1 Order Management

#### US-TA-001: Create a title search order

**As a** title officer,
**I want to** create a search order by entering property details and selecting a search scope,
**so that** the system can begin retrieving public records for the property.

**Acceptance Criteria:**
1. User can enter property address, county, and state code (all required).
2. User can optionally provide parcel number, legal description, and search years (default 60).
3. User can select search scope: `full` (default), `current_owner`, or `limited`.
4. User can optionally link the order to an existing TI pack via `linked_pack_id`.
5. System validates state code is a valid 2-letter US abbreviation.
6. System returns 400 with descriptive error if required fields are missing.
7. Order is created with status `pending` and scoped to the user's `org_id`.
8. API returns 201 with the full `OrderResponse` including generated UUID.

#### US-TA-002: View and filter search orders

**As a** title officer,
**I want to** see all search orders for my organization with status filters,
**so that** I can track progress and prioritize my workload.

**Acceptance Criteria:**
1. List endpoint returns only orders belonging to the user's `org_id`.
2. Orders can be filtered by status: `pending`, `processing`, `awaiting_abstractor`, `review_required`, `completed`, `failed`.
3. Results are paginated with `page` and `size` parameters (default page=1, size=20).
4. Each order in the list shows: property address, county/state, status, pipeline stage, created date.
5. Orders are sorted by `created_at` descending (newest first).
6. Response includes total count for pagination UI.

#### US-TA-003: Delete a pending order

**As a** title officer,
**I want to** delete an order that hasn't started processing yet,
**so that** I can cancel mistaken or duplicate orders.

**Acceptance Criteria:**
1. Orders with status `pending` can be deleted; returns 204.
2. Orders with any other status cannot be deleted; returns 400 with message "Only pending orders can be deleted".
3. Deleting an order removes all related `ta_source_assignments` (cascade).
4. Deletion is scoped to the user's `org_id` — cannot delete another org's orders.

---

### 2.2 Pipeline & Processing

#### US-TA-004: Trigger processing on an order

**As a** title officer,
**I want to** start the search pipeline on a pending order,
**so that** AI agents begin retrieving and analyzing records.

**Acceptance Criteria:**
1. `POST /orders/{orderId}/process` transitions order from `pending` to `processing`.
2. Returns 202 with `{ message: "Processing started" }`.
3. Returns 400 if order is not in `pending` status.
4. Pipeline begins asynchronously (BackgroundTasks or Temporal).
5. Order's `pipeline_stage` updates as each stage completes.

#### US-TA-005: Monitor pipeline progress

**As a** title officer,
**I want to** see which pipeline stage my order is currently in and whether any stages failed,
**so that** I know when results are ready or if intervention is needed.

**Acceptance Criteria:**
1. `GET /orders/{orderId}/pipeline` returns status of each stage: `pending`, `in_progress`, `completed`, `failed`, `skipped`.
2. Each stage includes `started_at`, `completed_at`, and `error` (if failed).
3. Frontend can poll this endpoint every 3 seconds to update a progress bar.
4. If a stage fails after all retries, `pipeline_error` contains a human-readable message.
5. Overall order status reflects pipeline outcome: `completed` or `failed`.

#### US-TA-006: Pipeline handles non-digital counties

**As a** title officer,
**I want to** be notified when a county requires a ground abstractor instead of automated retrieval,
**so that** I can assign someone to visit the courthouse.

**Acceptance Criteria:**
1. During the `order` stage, if any source is classified `non_digital`, order status becomes `awaiting_abstractor`.
2. Pipeline pauses at the `retrieve` stage for those sources.
3. Source assignments with `availability = non_digital` have `assigned_to` set to NULL (unassigned).
4. The order detail response clearly shows which sources are awaiting manual retrieval.
5. Pipeline resumes automatically when all non-digital sources have uploads (status `completed`).

---

### 2.3 County Sources & Ground Abstractor

#### US-TA-007: View source assignments for an order

**As a** title officer,
**I want to** see which county sources (recorder, clerk, assessor) were identified and their availability,
**so that** I understand what data is being pulled and from where.

**Acceptance Criteria:**
1. `GET /orders/{orderId}/sources` returns all `ta_source_assignments` for the order.
2. Each source shows: `source_type`, `availability`, `status`, `assigned_to` (if ground abstractor).
3. Digital sources show the portal URL used.
4. Non-digital sources show `assigned_to` name or "Unassigned".

#### US-TA-008: Upload documents for non-digital sources

**As a** ground abstractor,
**I want to** upload scanned documents from a courthouse visit,
**so that** the pipeline can continue processing with my findings.

**Acceptance Criteria:**
1. `POST /orders/{orderId}/sources/{sourceId}/upload` accepts multipart PDF or image files.
2. Only PDF, JPG, PNG, and TIFF files accepted; other types return 400.
3. File size limit enforced (configurable, default 100MB).
4. Upload creates a `ta_raw_documents` entry linked to the source assignment.
5. Source assignment status transitions to `completed` after successful upload.
6. If all sources for the order are now `completed`, pipeline resumes from `parse` stage.
7. Upload is scoped to the user's `org_id`.

#### US-TA-009: Manage county source configurations

**As a** platform admin,
**I want to** add, update, and view county source configurations,
**so that** the system knows how to query each county's databases.

**Acceptance Criteria:**
1. Only users with `is_platform_admin = true` can access these endpoints; others get 403.
2. `POST /admin/county-sources` creates a new source config with required fields: county, state_code, source_type, portal_type, search_config.
3. Unique constraint on (county, state_code, source_type) — duplicate returns 400.
4. `PATCH /admin/county-sources/{id}` allows partial updates (e.g., updating `search_config` without changing other fields).
5. `GET /admin/county-sources` supports filtering by `state_code`, `source_type`, and `availability`.
6. `search_config` JSONB is never returned in full via API if it contains auth credentials — sensitive fields are masked.

---

### 2.4 Document Retrieval & Parsing

#### US-TA-010: AI retrieves documents from county portals

**As a** title officer,
**I want** AI agents to automatically search county recorder, clerk, and assessor databases,
**so that** I don't have to manually navigate each portal.

**Acceptance Criteria:**
1. `DocumentRetrievalAgent` uses portal config to query each source by parcel number or property address.
2. Agent retrieves all documents within the configured `search_years` range.
3. Raw responses (HTML, PDF, JSON) are stored in `ta_raw_documents` with `fetched_at` timestamp.
4. Each raw document records the `source_url` and `document_ref` (recording number).
5. If a portal returns an error or timeout, the agent retries up to 3 times with exponential backoff.
6. After all retries fail, the source assignment is marked `failed` and the order continues with available sources.

#### US-TA-011: AI parses documents into structured data

**As a** title officer,
**I want** each retrieved document to be parsed into structured fields (parties, dates, amounts),
**so that** I can review extracted data without reading raw documents.

**Acceptance Criteria:**
1. `DocumentParserAgent` produces a `ta_documents` record for each raw document.
2. Extracted fields include: `doc_type`, `recording_date`, `recording_ref`, `grantor`, `grantee`, `legal_description`, `consideration`, `summary`.
3. Each parsed document has a `confidence` score between 0.0 and 1.0.
4. Documents with confidence < 0.70 have `needs_review = true`.
5. `doc_type` is one of: deed, mortgage, lien, judgment, easement, hoa, satisfaction, release, assignment, other.
6. `grantor` and `grantee` are stored as JSONB with `{names: [string], entity_type: string}`.
7. `summary` is an AI-generated 1–3 sentence description of the document.

#### US-TA-012: View and filter parsed documents

**As an** abstractor,
**I want to** see all parsed documents for an order, filtered by type or review status,
**so that** I can focus on documents that need attention.

**Acceptance Criteria:**
1. `GET /orders/{orderId}/documents` returns all `ta_documents` for the order.
2. Filter by `doc_type` (e.g., `?doc_type=deed`).
3. Filter by `needs_review` (e.g., `?needs_review=true`) to see only low-confidence parses.
4. Each document shows: type, recording date, parties, consideration, confidence, summary.
5. Documents are sorted by `recording_date` ascending (oldest first).

#### US-TA-013: Correct a parsed document

**As an** abstractor,
**I want to** edit the extracted fields of a parsed document when the AI got something wrong,
**so that** the chain-of-title uses accurate data.

**Acceptance Criteria:**
1. `PATCH /orders/{orderId}/documents/{docId}` accepts partial updates to any extracted field.
2. Updating a document creates a `ta_reviews` entry capturing `original_value` and `corrected_value`.
3. After correction, `needs_review` is set to `false` and `confidence` is set to 1.0.
4. The reviewer's `user_id` is recorded on the review.
5. Corrections are scoped to the user's `org_id`.

---

### 2.5 Chain-of-Title

#### US-TA-014: AI constructs chain-of-title

**As a** title officer,
**I want** AI to assemble all parsed documents into a chronological chain of ownership,
**so that** I can verify an unbroken transfer of title from past to present.

**Acceptance Criteria:**
1. `ChainBuilderAgent` orders conveyance documents (deeds) chronologically and links grantor → grantee across each transfer.
2. Each link in the chain is stored as a `ta_chain_links` record with `position`, `from_party`, `to_party`, `effective_date`.
3. Encumbrances (mortgages, liens, easements) are included in the chain as `link_type = encumbrance`.
4. Satisfactions and releases are linked as `link_type = release` and matched to their corresponding encumbrance.
5. If a grantee in one deed does not match the grantor of the next deed, the link is marked `is_gap = true` with a `gap_description`.
6. The chain covers the full `search_years` range specified on the order.

#### US-TA-015: View chain-of-title

**As a** title officer,
**I want to** see the chain-of-title as a timeline showing every transfer, encumbrance, and gap,
**so that** I can quickly assess whether title is clear.

**Acceptance Criteria:**
1. `GET /orders/{orderId}/chain` returns all `ta_chain_links` ordered by `position`.
2. Each link includes: position, link type, from/to parties, effective date, associated document ID, is_gap flag.
3. Gap links are visually distinguishable in the frontend (highlighted in red/yellow).
4. Links include the referenced `ta_documents.id` so the user can click through to the source document.

---

### 2.6 Flags & Anomaly Detection

#### US-TA-016: AI flags chain anomalies and risks

**As a** title officer,
**I want** AI to automatically flag problems like gaps, unreleased mortgages, and judgment matches,
**so that** I can address them before issuing title insurance.

**Acceptance Criteria:**
1. `AnomalyDetectorAgent` produces `ta_flags` with the following `flag_type` values:
   - `chain_gap` — missing conveyance between two owners (severity: `critical`)
   - `name_mismatch` — grantor/grantee name doesn't match across deeds (severity: `high`)
   - `unreleased_mortgage` — mortgage found without a corresponding satisfaction (severity: `high`)
   - `unsatisfied_lien` — lien or judgment without a release (severity: `high`)
   - `judgment_match` — judgment against a name in the chain (severity: `high`)
   - `easement_conflict` — easement that may affect property use (severity: `medium`)
   - `missing_source` — a county source was unavailable (severity: `medium`)
   - `low_confidence` — AI parsing confidence below threshold (severity: `low`)
2. Each flag has a human-readable `title` and detailed `description`.
3. Flags reference the specific `document_id` and/or `chain_link_id` they relate to.
4. Flags with matching releases/satisfactions are marked `auto_resolved = true`.

#### US-TA-017: View flags for an order

**As an** abstractor,
**I want to** see all flags for an order sorted by severity,
**so that** I can review the most critical issues first.

**Acceptance Criteria:**
1. `GET /orders/{orderId}/flags` returns all `ta_flags` for the order.
2. Flags are sorted by severity: critical → high → medium → low.
3. Each flag shows: type, severity, title, description, linked document/chain-link, auto_resolved status.
4. Resolved flags are visually de-emphasized but still visible.
5. Unresolved flag count is displayed prominently.

#### US-TA-018: Review and resolve a flag

**As an** abstractor,
**I want to** approve, reject, or correct a flagged issue,
**so that** the abstract package reflects accurate human-verified findings.

**Acceptance Criteria:**
1. `POST /orders/{orderId}/flags/{flagId}/review` accepts `{ decision, corrected_value?, notes? }`.
2. Valid decisions: `approve` (flag is valid, issue exists), `reject` (false positive), `correct` (flag is valid but details need adjustment).
3. For `correct` decisions, `corrected_value` JSONB captures the updated information.
4. A `ta_reviews` record is created with `reviewer_id`, `decision`, `original_value`, and `corrected_value`.
5. Reviewing a flag does NOT delete it — the flag persists with the review attached for audit trail.
6. Returns 400 if flag does not belong to the specified order.

---

### 2.7 Abstract Package

#### US-TA-019: Auto-generate abstract package

**As a** title officer,
**I want** the system to automatically generate an abstract package when the chain is complete and all flags are resolved,
**so that** clean searches are delivered without human bottleneck.

**Acceptance Criteria:**
1. After the `chain` pipeline stage, if `chain_complete = true` AND `open_flags_count = 0` (no unresolved critical/high flags), a package is auto-generated.
2. Package status is set to `issued` with `issued_by = auto`.
3. A unique `package_number` is generated (format: `TA-{YYYYMMDD}-{SEQUENCE}`).
4. Package PDF includes: property summary, search scope & years, document inventory, chain-of-title timeline, resolved flags summary.
5. Package JSON includes the same data in structured format for API consumers.
6. Both files are uploaded to storage at `{org_id}/{order_id}/packages/`.
7. Order status transitions to `completed`.

#### US-TA-020: Manually issue abstract package after review

**As an** abstractor,
**I want to** issue an abstract package after I've reviewed and resolved all flags,
**so that** exception orders can still produce a deliverable.

**Acceptance Criteria:**
1. `POST /orders/{orderId}/package/issue` generates and issues the package.
2. Returns 400 if there are unresolved `critical` severity flags — these must be addressed first.
3. Package is issued with `issued_by = manual` and `issuer_id` set to the reviewer's user ID.
4. Unresolved `medium`/`low` flags are included in the package as "open items" section.
5. `open_flags_count` on the package reflects remaining unresolved flags.
6. Order status transitions to `completed`.

#### US-TA-021: Download abstract package

**As a** title officer,
**I want to** download the abstract package as a PDF,
**so that** I can attach it to the title commitment file.

**Acceptance Criteria:**
1. `GET /orders/{orderId}/package` returns the package metadata (number, status, summary, dates).
2. `GET /orders/{orderId}/package/pdf` streams the PDF file with `Content-Type: application/pdf`.
3. Returns 404 if no package has been issued for this order.
4. PDF filename follows convention: `Abstract_{package_number}.pdf`.
5. Package data is also available as JSON via the metadata endpoint for programmatic access.

---

### 2.8 Cross-App Integration

#### US-TA-022: Link a search order to a TI pack

**As a** title officer,
**I want to** link a title search order to an existing Title Intelligence pack,
**so that** search findings feed into the commitment analysis.

**Acceptance Criteria:**
1. `linked_pack_id` can be set at order creation or updated later.
2. The TI pack must belong to the same `org_id`; cross-org linking returns 400.
3. When linked, the TI readiness endpoint includes chain-of-title completeness and open flags from the search order.
4. The TI pack detail page shows a link to the associated search order and its status.
5. An order can be linked to at most one TI pack; a TI pack can have multiple linked search orders.

#### US-TA-023: Surface search flags in TI readiness

**As a** title officer,
**I want** chain gaps and unreleased mortgages found in the search to appear in the TI readiness score,
**so that** I have a single view of all title risks.

**Acceptance Criteria:**
1. When a search order is linked to a TI pack, TI readiness queries `ta_flags` for that order.
2. `critical` and `high` severity search flags reduce the TI readiness score.
3. Search flags appear in a separate "Title Search" category in the readiness breakdown.
4. Resolving a search flag updates the TI readiness score on next calculation.

---

### 2.9 Admin & Operations

#### US-TA-024: View search throughput and status dashboard

**As an** admin,
**I want to** see how many searches are pending, processing, and completed across my organization,
**so that** I can manage workload and identify bottlenecks.

**Acceptance Criteria:**
1. The order list endpoint supports aggregation: total counts by status.
2. Frontend dashboard shows: orders by status (bar/pie chart), average processing time, orders awaiting ground abstractor.
3. Data is scoped to the admin's `org_id`.

#### US-TA-025: Assign a ground abstractor to a source

**As an** admin,
**I want to** assign a ground abstractor user to a non-digital source assignment,
**so that** someone is responsible for the courthouse visit.

**Acceptance Criteria:**
1. Admin can update `assigned_to` on a `ta_source_assignments` record via a PATCH endpoint.
2. The assigned user must belong to the same `org_id`.
3. Assignment is visible in the source list and order detail views.
4. Assigning a user does not change the source status — it stays `pending` until they upload.

---

### 2.10 Error Handling & Edge Cases

#### US-TA-026: Handle portal unavailability gracefully

**As a** title officer,
**I want** the system to handle county portal outages without failing the entire order,
**so that** I still get results from the sources that were available.

**Acceptance Criteria:**
1. If a portal is unreachable after 3 retries, the source assignment is marked `failed`.
2. A `missing_source` flag (severity: `medium`) is created describing which source was unavailable.
3. The pipeline continues with remaining sources — it does not halt the entire order.
4. The order can still reach `completed` status if the chain can be constructed from available sources.
5. The package includes a "Sources Unavailable" section listing failed sources.

#### US-TA-027: Handle ambiguous document parsing

**As an** abstractor,
**I want** the system to flag documents it couldn't parse confidently rather than guessing,
**so that** I can manually review the ambiguous ones.

**Acceptance Criteria:**
1. Documents with confidence < 0.70 are marked `needs_review = true`.
2. A `low_confidence` flag is created for each such document.
3. The flag description includes which specific fields had low confidence (e.g., "Grantee name unclear", "Document type ambiguous").
4. The abstractor can view the raw document (HTML/PDF/image) side-by-side with the parsed result.
5. After correction, the document's confidence is set to 1.0 and `needs_review` to false.

#### US-TA-028: Idempotent pipeline re-processing

**As a** title officer,
**I want to** re-trigger processing on a failed order without creating duplicate data,
**so that** transient errors can be retried safely.

**Acceptance Criteria:**
1. Calling `POST /orders/{orderId}/process` on a `failed` order restarts the pipeline from the failed stage.
2. The `parse` and `chain` stages use delete-then-insert: existing `ta_documents`, `ta_chain_links`, and `ta_flags` for the order are deleted before re-insertion.
3. The `retrieve` stage appends new raw documents without deleting previously retrieved ones.
4. Reviews from prior runs are preserved — they are not deleted on re-process.
5. Order status transitions back to `processing`.

---

## 3. Processing Pipeline

| # | Stage | What Happens | Output | Retry |
|---|---|---|---|---|
| 1 | `order` | Validate inputs, resolve county sources | `ta_orders` row, `ta_source_assignments` | — |
| 2 | `retrieve` | AI agents query county databases | `ta_raw_documents` rows | 3 |
| 3 | `parse` | AI parses documents into structured data | `ta_documents` rows | 3 |
| 4 | `chain` | AI constructs chain-of-title, flags gaps | `ta_chain_links` + `ta_flags` rows | 3 |
| 5 | `package` | Generate abstract/search package | `ta_packages` row (if auto-approved) | — |
| 6 | `complete` | Final status; notify user | Order → `completed` or `review_required` | — |

### Pipeline Characteristics

| Property | Value |
|---|---|
| Execution | FastAPI `BackgroundTasks` (default) or Temporal |
| Idempotency | Parse + Chain stages use delete-then-insert |
| Concurrency | One pipeline per order; multiple orders in parallel |
| Timeout | Retrieve: 120s per source; Parse/Chain: 60s |
| Failure | 3 retries with exponential backoff; then `failed` |
| Ground Abstractor | Pipeline pauses at `retrieve` until uploads received |

---

## 4. Database Schema

All tables prefixed with `ta_` (Title Abstracting). All tenant-scoped via `TenantMixin` unless noted.

### `ta_orders`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | Tenant scope |
| created_by | UUID | FK → users, NOT NULL | |
| property_address | VARCHAR(500) | NOT NULL | |
| parcel_number | VARCHAR(100) | NULLABLE | |
| county | VARCHAR(200) | NOT NULL | |
| state_code | VARCHAR(2) | NOT NULL | |
| legal_description | TEXT | NULLABLE | |
| search_scope | VARCHAR(20) | NOT NULL, DEFAULT 'full' | full / current_owner / limited |
| search_years | INTEGER | NOT NULL, DEFAULT 60 | How many years back to search |
| status | VARCHAR(30) | NOT NULL, DEFAULT 'pending' | pending / processing / awaiting_abstractor / review_required / completed / failed |
| pipeline_stage | VARCHAR(30) | NULLABLE | Current stage |
| pipeline_error | TEXT | NULLABLE | |
| linked_pack_id | UUID | FK → ti_packs, NULLABLE | Cross-app link |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |

### `ta_source_assignments`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL | |
| source_type | VARCHAR(30) | NOT NULL | recorder / clerk / assessor |
| availability | VARCHAR(20) | NOT NULL | digital / partial / non_digital |
| portal_config_id | UUID | FK → ta_county_sources, NULLABLE | |
| assigned_to | UUID | FK → users, NULLABLE | Ground abstractor user |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'pending' | pending / in_progress / completed / failed |
| created_at | TIMESTAMPTZ | NOT NULL | |

### `ta_raw_documents`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL | |
| source_assignment_id | UUID | FK → ta_source_assignments, NOT NULL | |
| source_url | VARCHAR(500) | NULLABLE | URL fetched |
| document_ref | VARCHAR(200) | NULLABLE | Recording number / book-page |
| raw_content | TEXT | NULLABLE | Raw HTML/text |
| storage_path | VARCHAR(500) | NULLABLE | Path to PDF/image in storage |
| content_format | VARCHAR(20) | NOT NULL | html / pdf / image / text |
| fetched_at | TIMESTAMPTZ | NOT NULL | |
| created_at | TIMESTAMPTZ | NOT NULL | |

### `ta_documents`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL | |
| raw_document_id | UUID | FK → ta_raw_documents, NULLABLE | |
| doc_type | VARCHAR(30) | NOT NULL | deed / mortgage / lien / judgment / easement / hoa / satisfaction / release / assignment / other |
| recording_date | DATE | NULLABLE | |
| recording_ref | VARCHAR(200) | NULLABLE | Book/page or instrument number |
| grantor | JSONB | NULLABLE | `{names: [], entity_type}` |
| grantee | JSONB | NULLABLE | `{names: [], entity_type}` |
| legal_description | TEXT | NULLABLE | |
| consideration | NUMERIC(14,2) | NULLABLE | Dollar amount |
| summary | TEXT | NULLABLE | AI-generated summary |
| confidence | FLOAT | NOT NULL, DEFAULT 0.0 | 0.0–1.0 |
| needs_review | BOOLEAN | NOT NULL, DEFAULT FALSE | |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |

### `ta_chain_links`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL | |
| document_id | UUID | FK → ta_documents, NOT NULL | |
| position | INTEGER | NOT NULL | Order in chain (1 = earliest) |
| link_type | VARCHAR(20) | NOT NULL | conveyance / encumbrance / release / gap |
| from_party | JSONB | NULLABLE | Grantor/prior owner |
| to_party | JSONB | NULLABLE | Grantee/new owner |
| effective_date | DATE | NULLABLE | |
| is_gap | BOOLEAN | NOT NULL, DEFAULT FALSE | True if AI detected a gap |
| gap_description | TEXT | NULLABLE | Explanation if gap |
| created_at | TIMESTAMPTZ | NOT NULL | |

### `ta_flags`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL | |
| document_id | UUID | FK → ta_documents, NULLABLE | |
| chain_link_id | UUID | FK → ta_chain_links, NULLABLE | |
| flag_type | VARCHAR(50) | NOT NULL | chain_gap / name_mismatch / unreleased_mortgage / unsatisfied_lien / judgment_match / easement_conflict / missing_source / low_confidence |
| severity | VARCHAR(10) | NOT NULL | critical / high / medium / low |
| title | VARCHAR(200) | NOT NULL | |
| description | TEXT | NOT NULL | |
| auto_resolved | BOOLEAN | NOT NULL, DEFAULT FALSE | |
| created_at | TIMESTAMPTZ | NOT NULL | |

### `ta_reviews`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL | |
| flag_id | UUID | FK → ta_flags, NULLABLE | |
| document_id | UUID | FK → ta_documents, NULLABLE | |
| reviewer_id | UUID | FK → users, NOT NULL | |
| decision | VARCHAR(20) | NOT NULL | approve / reject / correct |
| original_value | JSONB | NULLABLE | |
| corrected_value | JSONB | NULLABLE | |
| notes | TEXT | NULLABLE | |
| created_at | TIMESTAMPTZ | NOT NULL | |

### `ta_packages`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_id | UUID | FK → organizations, NOT NULL, INDEX | |
| order_id | UUID | FK → ta_orders, NOT NULL, UNIQUE | One package per order |
| package_number | VARCHAR(50) | NOT NULL, UNIQUE | System-generated |
| status | VARCHAR(20) | NOT NULL | draft / issued / revised |
| search_scope | VARCHAR(20) | NOT NULL | Copied from order |
| years_covered | INTEGER | NOT NULL | |
| total_documents | INTEGER | NOT NULL, DEFAULT 0 | |
| chain_complete | BOOLEAN | NOT NULL, DEFAULT FALSE | No gaps in chain |
| open_flags_count | INTEGER | NOT NULL, DEFAULT 0 | Unresolved flags |
| property_summary | JSONB | NOT NULL | Address, legal desc, parcel, current owner |
| storage_path_pdf | VARCHAR(500) | NULLABLE | |
| storage_path_json | VARCHAR(500) | NULLABLE | |
| issued_by | VARCHAR(20) | NOT NULL | auto / manual |
| issued_at | TIMESTAMPTZ | NULLABLE | |
| issuer_id | UUID | FK → users, NULLABLE | |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |

### `ta_county_sources`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| county | VARCHAR(200) | NOT NULL | |
| state_code | VARCHAR(2) | NOT NULL | |
| source_type | VARCHAR(30) | NOT NULL | recorder / clerk / assessor |
| availability | VARCHAR(20) | NOT NULL | digital / partial / non_digital |
| portal_url | VARCHAR(500) | NULLABLE | |
| portal_type | VARCHAR(30) | NOT NULL | api / web_scrape / manual_only |
| search_config | JSONB | NOT NULL | Selectors, field mappings, auth |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| last_verified | TIMESTAMPTZ | NULLABLE | |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |

*Note: `ta_county_sources` is NOT tenant-scoped — shared platform resource. Unique on (county, state_code, source_type).*

### Data Model Relationships

```
ta_orders ──────┬──── ta_source_assignments ──── ta_raw_documents
(1 per property)├──── ta_documents ──── ta_chain_links
                ├──── ta_flags
                ├──── ta_reviews
                ├──── ta_packages (1:1)
                └──── ti_packs (optional cross-app link)

ta_county_sources (shared, not tenant-scoped)
```

---

## 5. API Contract

All routes under `/api/v1/apps/title-search/`. Subscription-gated via `MicroAppAccessMiddleware`.

### Order Management

| Method | Path | Request | Response | Status Codes |
|---|---|---|---|---|
| POST | `/orders` | `{ property_address, parcel_number?, county, state_code, search_scope?, search_years?, linked_pack_id? }` | `OrderResponse` | 201, 400, 403 |
| GET | `/orders` | Query: `?status=&page=&size=` | `Page<OrderResponse>` | 200, 403 |
| GET | `/orders/{orderId}` | — | `OrderDetailResponse` | 200, 404 |
| POST | `/orders/{orderId}/process` | — | `{ message: "Processing started" }` | 202, 400, 404 |
| DELETE | `/orders/{orderId}` | — | 204 | 204, 404 |

### Pipeline & Sources

| Method | Path | Request | Response | Status Codes |
|---|---|---|---|---|
| GET | `/orders/{orderId}/pipeline` | — | `PipelineStatusResponse` | 200, 404 |
| GET | `/orders/{orderId}/sources` | — | `SourceAssignment[]` | 200, 404 |
| POST | `/orders/{orderId}/sources/{sourceId}/upload` | multipart (PDF/image) | `RawDocumentResponse` | 201, 400 |

### Documents & Chain

| Method | Path | Request | Response | Status Codes |
|---|---|---|---|---|
| GET | `/orders/{orderId}/documents` | Query: `?doc_type=&needs_review=` | `Document[]` | 200, 404 |
| GET | `/orders/{orderId}/chain` | — | `ChainLink[]` | 200, 404 |
| PATCH | `/orders/{orderId}/documents/{docId}` | Partial update | `Document` | 200, 400, 404 |

### Flags & Reviews

| Method | Path | Request | Response | Status Codes |
|---|---|---|---|---|
| GET | `/orders/{orderId}/flags` | — | `Flag[]` | 200, 404 |
| POST | `/orders/{orderId}/flags/{flagId}/review` | `{ decision, corrected_value?, notes? }` | `ReviewResponse` | 201, 400, 404 |

### Packages

| Method | Path | Request | Response | Status Codes |
|---|---|---|---|---|
| GET | `/orders/{orderId}/package` | — | `PackageResponse` | 200, 404 |
| GET | `/orders/{orderId}/package/pdf` | — | `application/pdf` stream | 200, 404 |
| POST | `/orders/{orderId}/package/issue` | — | `PackageResponse` | 201, 400 |

### County Sources (Platform Admin Only)

| Method | Path | Request | Response | Status Codes |
|---|---|---|---|---|
| GET | `/admin/county-sources` | Query: `?state_code=&source_type=&availability=` | `CountySource[]` | 200 |
| POST | `/admin/county-sources` | `{ county, state_code, source_type, portal_url?, portal_type, search_config }` | `CountySource` | 201, 400 |
| PATCH | `/admin/county-sources/{id}` | Partial update | `CountySource` | 200, 404 |

---

## 6. AI Agents

All agents subclass `BaseAIService`.

| Agent | Purpose | Input | Output | Method |
|---|---|---|---|---|
| `SourceResolverAgent` | Identify available county sources and classify availability | County, state, source configs | Source assignments with availability | `call_haiku_structured` |
| `DocumentRetrievalAgent` | Navigate county portals, retrieve raw documents | Parcel/address, portal config | Raw HTML/PDF/images | `call_with_tools` |
| `DocumentParserAgent` | Parse raw documents into structured fields (parties, dates, amounts) | Raw document content | Structured document records with confidence | `call_haiku_structured` |
| `ChainBuilderAgent` | Assemble documents into chain-of-title, detect gaps/breaks | Parsed documents | Chain links + gap flags | `call_haiku_structured` |
| `AnomalyDetectorAgent` | Flag unreleased mortgages, unsatisfied liens, name mismatches | Chain + documents | Flag list with severity | `call_haiku_structured` |
| `PackageAgent` | Generate abstract/search package (PDF + JSON) | Chain, documents, flags, property info | Formatted package | `call_haiku` |

### Agent Tools (DocumentRetrievalAgent)

| Tool | Description |
|---|---|
| `search_recorder` | Query county recorder by name/parcel/date range |
| `search_clerk` | Query clerk of courts for judgments/lis pendens |
| `search_assessor` | Query assessor for ownership/legal description |
| `fetch_document` | Download a specific document by recording reference |
| `check_county_source` | Retrieve stored config for a county source |

---

## 7. Security Requirements

| Area | Requirement |
|---|---|
| Authentication | All routes require valid JWT |
| Authorization | Order CRUD: `get_current_member()`; County sources: `require_platform_admin()` |
| Tenant Isolation | All queries filter by `org_id`; `ta_county_sources` is the only shared table |
| Portal Credentials | County portal auth stored encrypted in `search_config`; never logged |
| Document Storage | Raw documents tenant-scoped in storage; PII-bearing docs encrypted at rest |
| Ground Abstractor | Upload endpoint validates PDF/image only; size limits enforced |

---

## 8. Performance Targets

| Metric | Target |
|---|---|
| Order creation | < 200ms |
| Source resolution | < 10s |
| Document retrieval (per source) | < 120s (portal-dependent) |
| Document parsing (per document) | < 15s |
| Chain construction | < 30s |
| End-to-end (digital county) | < 2 hours |
| Package PDF generation | < 15s |
| API list queries | < 500ms |

---

## 9. Storage Architecture

```
{org_id}/{order_id}/
  raw/
    recorder_001.html       # Raw portal responses
    clerk_001.pdf           # Downloaded documents
    assessor_001.json
  uploads/
    ground_deed_001.pdf     # Ground abstractor uploads
  packages/
    pkg_{number}.pdf        # Issued abstract package
    pkg_{number}.json       # Structured package data
```

---

## 10. Frontend Routes

| Route | Description |
|---|---|
| `/apps/title-search` | Order list with status filters |
| `/apps/title-search/orders/new` | New search order form |
| `/apps/title-search/orders/[orderId]` | Order detail + pipeline progress |
| `/apps/title-search/orders/[orderId]/documents` | Parsed documents list + type filters |
| `/apps/title-search/orders/[orderId]/chain` | Chain-of-title timeline visualization |
| `/apps/title-search/orders/[orderId]/flags` | Flags + review interface |
| `/apps/title-search/orders/[orderId]/package` | Abstract package view + download |

---

## 11. Implementation Directory Structure

```
backend/app/micro_apps/title_search/
├── __init__.py              # Lazy export (__getattr__ pattern)
├── app.py                   # class TitleSearchMicroApp(MicroAppBase), slug="title-search"
├── models/
│   ├── __init__.py
│   ├── order.py             # TAOrder
│   ├── source_assignment.py # TASourceAssignment
│   ├── raw_document.py      # TARawDocument
│   ├── document.py          # TADocument
│   ├── chain_link.py        # TAChainLink
│   ├── flag.py              # TAFlag
│   ├── review.py            # TAReview
│   ├── package.py           # TAPackage
│   └── county_source.py     # TACountySource (not tenant-scoped)
├── schemas/
│   ├── __init__.py
│   ├── order.py
│   ├── document.py
│   ├── chain.py
│   ├── flag.py
│   └── package.py
├── routes/
│   ├── __init__.py          # get_title_search_router()
│   ├── orders.py
│   ├── documents.py
│   ├── chain.py
│   ├── flags.py
│   ├── packages.py
│   └── county_sources.py    # Platform admin only
├── services/
│   ├── __init__.py
│   ├── order_service.py
│   ├── retrieval_service.py
│   ├── parser_service.py
│   ├── chain_service.py
│   ├── package_service.py
│   └── pipeline_service.py
├── ai/
│   ├── __init__.py
│   ├── source_resolver_agent.py
│   ├── document_retrieval_agent.py
│   ├── document_parser_agent.py
│   ├── chain_builder_agent.py
│   ├── anomaly_detector_agent.py
│   ├── package_agent.py
│   └── tools/
│       ├── __init__.py
│       └── county_portals.py
└── pipeline/
    ├── __init__.py
    ├── stages.py
    └── orchestrator.py
```

---

## 12. Cross-App Integration (Title Intelligence)

| Feature | Mechanism |
|---|---|
| Link order to TI pack | `ta_orders.linked_pack_id` FK → `ti_packs.id` |
| Surface chain gaps in TI readiness | TI readiness endpoint queries `ta_flags` for linked pack |
| Feed documents to TI ingestion | TI ingestion agent can pull `ta_documents` for linked orders |
| Unified property view | Frontend shows search status + TI pipeline progress together |

---

## 13. Testing Strategy

| Layer | Tool | Coverage Target |
|---|---|---|
| Unit | pytest | AI agents, document parsing, chain construction logic |
| Integration | pytest + TestClient | Full order → pipeline → package flow |
| Portal Mocks | pytest fixtures | Simulated county portal responses (recorder, clerk, assessor) |
| E2E | Playwright | Order creation through package download |

```bash
cd backend && pytest tests/title_search/ -v                        # all TA tests
cd backend && pytest tests/title_search/test_orders.py -v          # order CRUD
cd backend && pytest tests/title_search/test_chain.py -v           # chain construction
cd backend && pytest tests/title_search/test_parser.py -v          # document parsing
cd backend && pytest tests/title_search/test_pipeline.py -v        # pipeline stages
```

---

## 14. Verification Checklist

### Orders
- [ ] Create order with valid property/county info
- [ ] Reject invalid state codes and missing required fields
- [ ] List orders filtered by status and org_id
- [ ] Delete pending orders; prevent deletion of completed

### Pipeline
- [ ] Pipeline progresses through all 6 stages for digital counties
- [ ] Pipeline pauses at `retrieve` for non-digital counties
- [ ] Ground abstractor upload resumes pipeline
- [ ] Failed stage sets `failed` status with error

### Document Retrieval & Parsing
- [ ] Retrieval agent fetches from recorder, clerk, assessor
- [ ] Parser correctly classifies deed, mortgage, lien, judgment, easement
- [ ] Low-confidence parses flagged with `needs_review = true`
- [ ] Raw documents stored for audit trail

### Chain-of-Title
- [ ] Chain links ordered chronologically
- [ ] Gaps detected when grantor/grantee names don't match
- [ ] Unreleased mortgages flagged as `high` severity
- [ ] Complete chains marked `chain_complete = true`

### Packages
- [ ] Auto-issued when no unresolved flags and chain complete
- [ ] Manual issuance after reviewer approval
- [ ] PDF includes all documents, chain, and open items
- [ ] Package number unique and system-generated

### Security
- [ ] All endpoints require valid JWT
- [ ] All queries scoped by org_id (except county_sources)
- [ ] Portal credentials never in logs or API responses
- [ ] Ground abstractor uploads validated (PDF/image only, size limit)
