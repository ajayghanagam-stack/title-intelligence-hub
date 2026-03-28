# Title Intelligence — Gap Stories

Stories derived from gap analysis between doc3.docx reference screens and current implementation.

---

## High Priority

### TI-GAP-001: Display extracted property address as pack header
**As a** title examiner,
**I want** the AI-extracted property address (e.g., "675 BUNKER HILL ROAD, COLUMBIA, MS 39429-7832") displayed as the main header on the results page,
**So that** I can immediately identify which property I'm reviewing without relying on the user-entered pack name.

**Acceptance Criteria:**
- After pipeline completion, the results page header shows the extracted property address in bold
- Falls back to the pack name if no address was extracted
- Address is sourced from extractions where `extraction_type = "property_info"` and `label = "address"`

---

### TI-GAP-002: Display extracted order metadata in results header
**As a** title examiner,
**I want** to see Order Number, Commitment Date, and Issued By displayed below the property address on the results page,
**So that** I have full context about the commitment without digging into extractions.

**Acceptance Criteria:**
- Header sub-line shows: "Order No: {value} | Commitment Date: {value} | Issued by: {value}"
- Values sourced from extractions (`commitment_number`, `effective_date`, `title_company`/`underwriter`)
- Gracefully omits any field that was not extracted

---

### TI-GAP-003: Add Critical / Warnings / Under Review summary count cards
**As a** title examiner,
**I want** a row of summary cards showing counts of Critical Issues, Warnings, Under Review items, and a Validation Score,
**So that** I can triage a package at a glance without scrolling to the flags table.

**Acceptance Criteria:**
- Four cards displayed in a horizontal row above the flags section:
  1. **Critical Issues** — count of flags with severity `critical`, red accent
  2. **Warnings** — count of flags with severity `high` or `medium`, amber accent
  3. **Under Review** — count of flags with status `under_review` or `escalated`, blue accent
  4. **Validation Score** — readiness score displayed as "X / 10" (score / 10, rounded), green accent
- Each card shows the count prominently (large font) with a subtitle label
- Cards update when flag statuses change (approve/reject/escalate)

---

### TI-GAP-004: Add "Required Action" column to flags table
**As a** title examiner,
**I want** each flag row in the results table to show a recommended required action,
**So that** I can see the next step for each issue without expanding the row.

**Acceptance Criteria:**
- New "Required Action" column added to the flags table (visible in the collapsed row)
- Content sourced from the flag's `ai_explanation` field (first sentence or a dedicated field if added)
- Text truncated with ellipsis if longer than ~80 characters
- Full text visible in expanded flag detail

---

### TI-GAP-005: Add recent packs list to sidebar
**As a** title examiner,
**I want** to see my most recent packages listed in the sidebar,
**So that** I can quickly switch between packages without navigating back to the dashboard.

**Acceptance Criteria:**
- Sidebar shows "RECENT PACKAGES" section below the navigation items
- Lists the 5 most recent packs for the current org (ordered by `created_at` desc)
- Each entry shows: pack name (truncated), order number (if extracted), date, flag count icon + count
- Clicking a pack navigates to its results page
- Active pack is visually highlighted
- List updates when a new pack is created or processing completes

---

## Medium Priority

### TI-GAP-006: Add "Re-analyze" button to results page
**As a** title examiner,
**I want** a "Re-analyze" button on the results page,
**So that** I can retrigger the AI analysis pipeline without re-uploading files.

**Acceptance Criteria:**
- "Re-analyze" button with refresh icon displayed in the results page header (next to Export)
- Clicking triggers a confirmation dialog: "Re-analyze will reprocess this package. Continue?"
- On confirm, calls the existing `POST /packs/{packId}/pipeline` endpoint
- Pack status resets to `processing` and pipeline progress is shown
- Button is disabled while processing is in progress

---

### TI-GAP-007: Add inline "Ask a Question" input on results page
**As a** title examiner,
**I want** an inline question input directly on the results page (above the flags table),
**So that** I can ask quick questions without opening a separate chat panel.

**Acceptance Criteria:**
- Text input with "Ask a question about this package..." placeholder and "Ask" button
- Positioned between the summary cards and the Exceptions section
- Submitting a question opens the chat slide panel with the question pre-sent
- Input clears after submission
- Chat panel still available via the existing button for full conversation history

---

### TI-GAP-008: Add "Document Ref" column to flags table
**As a** title examiner,
**I want** to see the document reference (e.g., "Schedule B-I Requirements" or page/book reference) for each flag directly in the table row,
**So that** I can quickly identify where in the document each issue originates.

**Acceptance Criteria:**
- New "Document Ref" column visible in the collapsed flag row
- Content derived from the flag's `evidence_refs` array (section name + page number)
- Format: "{section_type} Page {page_number}" or "Page {page_number}" if no section
- If multiple evidence refs, show the first with a "+N more" indicator
- Clicking the ref navigates to the documents viewer at that page

---

### TI-GAP-009: Support PNG and JPEG file uploads
**As a** title examiner,
**I want** to upload PNG and JPEG image files in addition to PDFs,
**So that** I can analyze scanned documents that aren't in PDF format.

**Acceptance Criteria:**
- Upload dropzone accepts `.pdf`, `.png`, `.jpg`, `.jpeg` files
- Backend `POST /packs/{packId}/files` accepts image MIME types (`image/png`, `image/jpeg`)
- Image files are treated as single-page documents in the pipeline
- stage_render handles images directly (skip PDF rendering, create page image + thumbnail)
- OCR runs on image uploads since they won't have embedded text
- File type validation updated on both frontend and backend

---

### TI-GAP-010: Add sequential exception IDs to flags
**As a** title examiner,
**I want** each flag to display a sequential ID (e.g., "EX-001", "EX-002"),
**So that** I can easily reference specific issues in conversations and reports.

**Acceptance Criteria:**
- Each flag in the table shows an ID in the format "EX-{NNN}" (zero-padded, sequential per pack)
- IDs are assigned in order of creation (by flag position/page number)
- ID column is the first column in the flags table
- IDs are included in exported reports
- IDs are stable across page refreshes (derived from sort order, not random)

---

## Low Priority

### TI-GAP-011: Add "Analyzed on" timestamp to results page
**As a** title examiner,
**I want** to see when the analysis was completed (e.g., "Analyzed on 3/2/2026 at 01:11 PM"),
**So that** I know how recent the analysis results are.

**Acceptance Criteria:**
- Timestamp displayed in the top-right area of the results page header
- Format: "Analyzed on {M/D/YYYY} at {HH:MM AM/PM}"
- Sourced from the pipeline run's `completed_at` timestamp
- Only shown when pack status is `completed`

---

### TI-GAP-012: Update section header wording to match reference
**As a** product owner,
**I want** the flags section header to read "Exceptions & Required Actions" instead of "Risk Flags",
**So that** the terminology matches industry conventions used in the reference design.

**Acceptance Criteria:**
- Tab/section header changed from "Risk Flags" to "Exceptions & Required Actions"
- Subtitle added: "Issues identified requiring resolution prior to closing"
- Filter tabs show: "All (N) | Critical (N) | Warning (N) | Review (N)"

---

### TI-GAP-013: Update upload page wording and button styling
**As a** product owner,
**I want** the upload page title to say "Upload Documents" and the submit button to be a full-width light blue "Analyze Package" button,
**So that** the UI matches the reference design.

**Acceptance Criteria:**
- Page title: "Upload Documents"
- Subtitle: "Upload your title search package files for AI-powered analysis."
- Submit button: full-width, light blue background, text "Analyze Package"
- Upload area text: "Upload a Title Search Package"

---

### TI-GAP-014: Add footer bar with org name and admin info
**As a** platform user,
**I want** a persistent footer bar showing "{Org Name} | Powered by Logikality" with admin email and sign-out link,
**So that** I always know which organization context I'm in and can quickly sign out.

**Acceptance Criteria:**
- Footer bar at bottom of the page (outside sidebar)
- Left: "TITLE INTELLIGENCE PLATFORM" label
- Center: "{Org Name} | Powered by Logikality"
- Right: admin email + "Sign Out" link
- Footer is sticky/visible on all TI pages

---

### TI-GAP-015: Increase information density in flags table
**As a** title examiner,
**I want** key flag details (description snippet, document ref, required action) visible in the collapsed table row,
**So that** I can scan issues quickly without expanding every row.

**Acceptance Criteria:**
- Collapsed flag row shows: ID, Severity, Category, Description (truncated), Document Ref, Required Action (truncated)
- Table uses a traditional row layout (not card-based)
- Reduce reliance on expand/collapse for essential information
- Maintain expand for full details, AI explanation, and evidence list
