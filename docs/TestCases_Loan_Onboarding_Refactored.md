# Test Cases — Loan Onboarding (Refactored)

**Version:** 1.0  
**Date:** 2026-05-10  
**Scope:** Phase 6 LogikIntake cutover — `/loans/*` operator surface, reject + re-upload flow, audit drawer, customer-tree mirrors, 301 redirects from legacy `/packages/*` URLs, brand-QA fixes, plus regression coverage of the underlying 5-stage LO pipeline (ingest → classify → stack → validate → review).

---

## 1. Test Environment

| Item | Value |
|---|---|
| Backend | `http://localhost:8000` |
| Frontend (platform) | `http://localhost:3000` |
| Frontend (customer scope) | `http://localhost:3000/org/{orgSlug}` |
| Postgres (Docker) | `localhost:5436`, db `title_intelligence_hub` |
| Temporal UI | `http://localhost:8085` |
| Test PDF | `docs/loan-package-final-packet.pdf` |
| Platform admin | `admin@logikality.com` / `admin123` |
| Customer owner | `admin@societytitle.com` / `admin123` |

**Pre-flight**: `./start-dev.sh` running; database freshly truncated of all `lo_*` rows; `storage/*/ai_cache/` removed; browser site-data cleared.

## 2. Conventions

- **ID**: `LO-TC-NNN`
- **Priority**: Critical / High / Medium / Low
- **Type**: Functional / UI / Security / Regression / Performance / Brand
- **Result**: Pass / Fail / Blocked / N/A — record with tester initials + date.

---

## 3. Authentication & Tenant Isolation

### LO-TC-001: Platform admin login
**Priority:** Critical · **Type:** Functional  
**Preconditions:** Fresh DB, seeded admin user.  
**Steps:**
1. Visit `http://localhost:3000/login`.
2. Enter `admin@logikality.com` / `admin123`.
3. Click Sign In.

**Expected:** Redirect to `/dashboard`. JWT stored in `localStorage` under key `auth_token`. `GET /api/v1/auth/me` returns `is_platform_admin: true`.

### LO-TC-002: Customer-owner login
**Priority:** Critical · **Type:** Functional  
**Preconditions:** Society Title org seeded with active LO subscription.  
**Steps:**
1. Sign in as `admin@societytitle.com` / `admin123`.
2. Observe sidebar.

**Expected:** Land on customer-scoped dashboard. Sidebar shows "Loan Files" entry only if active LO subscription exists.

### LO-TC-003: Tenant isolation — cross-org loan list
**Priority:** Critical · **Type:** Security  
**Preconditions:** Loan exists in Logikality org; signed in as Society Title owner.  
**Steps:**
1. Open DevTools → Network.
2. `GET /api/v1/apps/loan-onboarding/loans` with `X-Org-Id: <societytitle-org-id>`.

**Expected:** `200 OK` returning only Society Title's loans. Logikality's loan never appears.

### LO-TC-004: Tenant isolation — cross-org loan GET
**Priority:** Critical · **Type:** Security  
**Steps:** As Society Title owner, hit `GET /loans/{logikality_loan_id}`.  
**Expected:** `404 Not Found` (no leakage, not 403 — to prevent enumeration).

### LO-TC-005: Subscription gate
**Priority:** High · **Type:** Security  
**Preconditions:** Org without active LO subscription.  
**Steps:** Hit any `/api/v1/apps/loan-onboarding/*` endpoint.  
**Expected:** `403 Forbidden` from `MicroAppAccessMiddleware`.

### LO-TC-006: JWT expiry
**Priority:** High · **Type:** Security  
**Steps:** Manually edit `auth_token` in `localStorage` to one with `exp` in the past; reload `/apps/loan-onboarding`.  
**Expected:** Redirect to `/login`. Stale UI state not exposed.

---

## 4. Sidebar & Navigation (Phase 6 cutover)

### LO-TC-010: Sidebar shows single "Loan Files" entry
**Priority:** High · **Type:** UI / Regression  
**Steps:** Sign in → expand sidebar → expand Loan Onboarding section.  
**Expected:** Single entry labeled **Loan Files** linking to `/apps/loan-onboarding`. No legacy "Packages", "Compliance", "Pipeline Dashboard" entries.

### LO-TC-011: Recent loans link to /loans/{id}
**Priority:** High · **Type:** Regression  
**Steps:** Hover a recent loan in the sidebar.  
**Expected:** Anchor `href` is `/apps/loan-onboarding/loans/{id}` (or `/org/{slug}/apps/loan-onboarding/loans/{id}` for customer scope). No `/packages/{id}` URLs anywhere in the sidebar HTML.

### LO-TC-012: Top-level Loan Files page
**Priority:** Critical · **Type:** Functional  
**Steps:** Click **Loan Files**.  
**Expected:** Land on `/apps/loan-onboarding` showing the queue. Empty state on a fresh DB. **+ New file** CTA visible.

---

## 5. Legacy URL Redirects (301)

### LO-TC-020: Legacy /packages/{id} → /loans/{id}
**Priority:** High · **Type:** Functional  
**Preconditions:** A loan exists with id `{loanId}`.  
**Steps:** Browser → `http://localhost:3000/apps/loan-onboarding/packages/{loanId}`.  
**Expected:** 301 redirect to `/apps/loan-onboarding/loans/{loanId}`. Final URL in address bar is `/loans/{loanId}`.

### LO-TC-021: Legacy /packages/{id}/processing → /loans/{id}
**Priority:** High · **Type:** Functional  
**Steps:** Visit `/apps/loan-onboarding/packages/{loanId}/processing`.  
**Expected:** 301 to `/apps/loan-onboarding/loans/{loanId}`.

### LO-TC-022: Legacy /packages/{id}/results, /dashboard, /compliance → /loans/{id}
**Priority:** Medium · **Type:** Functional  
**Steps:** Visit each of `/packages/{loanId}/results`, `/packages/{loanId}/dashboard`, `/packages/{loanId}/compliance`.  
**Expected:** All 301 to `/loans/{loanId}` — sub-tabs collapse onto unified overview.

### LO-TC-023: Legacy /packages/new → /apps/loan-onboarding
**Priority:** Medium · **Type:** Functional  
**Steps:** Visit `/apps/loan-onboarding/packages/new`.  
**Expected:** 301 to `/apps/loan-onboarding` (new-file modal replaces standalone wizard).

### LO-TC-024: Customer-scoped legacy redirects
**Priority:** Medium · **Type:** Functional  
**Steps:** Visit `/org/societytitle/apps/loan-onboarding/packages/{loanId}/processing`.  
**Expected:** 301 to `/org/societytitle/apps/loan-onboarding/loans/{loanId}`. Org slug preserved.

### LO-TC-025: Bookmarked deep link (cold visit)
**Priority:** Medium · **Type:** Regression  
**Steps:** Open a private/incognito window → paste a legacy `/packages/{id}` URL.  
**Expected:** Login page (auth gate), then post-login the redirect chain still resolves to `/loans/{id}`.

---

## 6. New Loan Creation

### LO-TC-030: Open new-file modal
**Priority:** Critical · **Type:** Functional  
**Steps:** Click **+ New file** on `/apps/loan-onboarding`.  
**Expected:** Modal opens with three steps: Loan context → Doc types → Validation rules. Step 1 has fields: Loan name, Borrower name, Loan reference, HITL threshold (default 0.75).

### LO-TC-031: Validation — required loan name
**Priority:** Medium · **Type:** Functional  
**Steps:** Try to advance step 1 with empty Loan name.  
**Expected:** Inline error "Loan name is required". Cannot advance.

### LO-TC-032: HITL threshold range
**Priority:** Medium · **Type:** Functional  
**Steps:** Set threshold to `1.5` and to `-0.1`.  
**Expected:** Both rejected; allowed range is `[0, 1]`.

### LO-TC-033: Doc-type picker — preset selection
**Priority:** High · **Type:** Functional  
**Steps:** On step 2, select URLA_1003, PAYSTUB, W2 from the preset list.  
**Expected:** Each pill shows label + "Required" toggle; defaults to required.

### LO-TC-034: Doc-type picker — AI-suggested chip
**Priority:** Medium · **Type:** UI  
**Steps:** Type a custom doc type (e.g., "Verification of Employment") in the search.  
**Expected:** Sparkles icon appears next to AI-suggested entries. User can add or dismiss.

### LO-TC-035: Validation rules — preset rules
**Priority:** High · **Type:** Functional  
**Steps:** Step 3, enable presets: missing_signatures, missing_pages, missing_fields, min_page_count, max_page_count.  
**Expected:** Each renders with config inputs (page-count thresholds editable). Toggling persists in form state.

### LO-TC-036: Validation rules — custom NL rule
**Priority:** Medium · **Type:** Functional  
**Steps:** Add a custom rule: "Borrower income on 1003 should match paystub YTD within 10%".  
**Expected:** Saved with `rule_source=custom`, `rule_id` auto-generated, description preserved.

### LO-TC-037: Submit — POST /loans
**Priority:** Critical · **Type:** Functional  
**Steps:** Click Create. Inspect Network tab.  
**Expected:** `POST /api/v1/apps/loan-onboarding/loans` with body containing `name`, `borrower_name`, `loan_reference`, `hitl_threshold`, `doc_types[]`, `validation_rules[]`. Response `201` with `id`, `status: "uploading"`. Modal closes; loan appears in queue with status badge "Uploading".

### LO-TC-038: Loan reference uniqueness scope
**Priority:** Low · **Type:** Functional  
**Steps:** Try to create two loans with identical `loan_reference` in the same org.  
**Expected:** Either both accepted (no DB constraint) **or** second rejected — verify behavior matches the schema. Document actual behavior in result.

---

## 7. File Upload

### LO-TC-040: Upload final-packet PDF
**Priority:** Critical · **Type:** Functional  
**Preconditions:** Loan in `uploading` status.  
**Steps:**
1. From the modal (or loan detail), drag-drop `docs/loan-package-final-packet.pdf`.
2. Watch upload progress.

**Expected:** `POST /loans/{id}/files` returns `201` with file metadata. File appears in the loan's file list. `lo_package_files` row created with correct `filename`, `size`, `storage_path` under `{org_id}/{loan_id}/files/`.

### LO-TC-041: Reject non-PDF
**Priority:** High · **Type:** Functional  
**Steps:** Drop a `.docx` or `.png`.  
**Expected:** Inline error "Only PDF files allowed". No DB row created.

### LO-TC-042: Size limit enforcement
**Priority:** Medium · **Type:** Functional  
**Steps:** Upload a PDF > `FILE_UPLOAD_MAX_SIZE` (default 100 MB).  
**Expected:** `413 Payload Too Large` from backend. UI shows "File exceeds 100 MB limit".

### LO-TC-043: Multiple-file upload
**Priority:** Medium · **Type:** Functional  
**Steps:** Drop two PDFs at once.  
**Expected:** Both upload concurrently; both appear in `lo_package_files`. Each has its own page-extraction pass during ingest.

### LO-TC-044: Storage path tenant scoping
**Priority:** Critical · **Type:** Security  
**Steps:** After upload, verify on disk: `ls backend/storage/{org_id}/{loan_id}/files/`.  
**Expected:** PDF saved under `{org_id}/` prefix. No cross-org access path constructible.

---

## 8. Pipeline — 5 Stages

### LO-TC-050: Trigger pipeline
**Priority:** Critical · **Type:** Functional  
**Steps:** From loan detail with at least one uploaded PDF, click **Process** (or `POST /loans/{id}/process`).  
**Expected:** Status transitions `uploading → processing`. `pipeline_stage` becomes `ingest`. Response `202`.

### LO-TC-051: Ingest stage — page splitting
**Priority:** Critical · **Type:** Functional  
**Steps:** Wait for ingest stage to complete (poll `/loans/{id}/pipeline`).  
**Expected:** `lo_pages` has one row per PDF page. Each row has `page_number`, `text` (PyMuPDF extraction), and a thumbnail path under `{org_id}/{loan_id}/thumbs/`.

### LO-TC-052: Classify stage — per-page LLM
**Priority:** Critical · **Type:** Functional  
**Steps:** Pipeline advances to `classify`. Watch `lo_classifications` table.  
**Expected:** One row per page with `predicted_doc_type`, `page_role` (first_page/continuation/last_page/signature_page), `detected_fields`, `classification_confidence`. Pages with no match get `doc_type="Others"`.

### LO-TC-053: Stack stage — contiguous grouping
**Priority:** Critical · **Type:** Functional  
**Steps:** Pipeline advances to `stack`.  
**Expected:** `lo_stacks` rows grouping contiguous same-doc-type pages. `page_role="first_page"` always starts a new stack. "Others" stack is always `requires_hitl=True`.

### LO-TC-054: Validate stage — preset rules
**Priority:** Critical · **Type:** Functional  
**Steps:** Pipeline advances to `validate`.  
**Expected:** `lo_validation_results` has one row per stack. Each row has `rules_evaluated[]` with `rule_id`, `passed`, `evidence`. Confidence breakdown stored with weights 0.4 classification + 0.25 split + 0.35 validation. Others stacks short-circuit to `passed=true`.

### LO-TC-055: Review stage — Reasoning agent
**Priority:** Critical · **Type:** Functional  
**Steps:** Pipeline reaches `review`.  
**Expected:** Per-stack decision (`accept`/`needs_review`/`reject`) on `lo_stacks.status`. Package-level issues persisted. Stacks previously flagged HITL cannot be auto-accepted (HITL floor preserved).

### LO-TC-056: Terminal status — awaiting_review
**Priority:** Critical · **Type:** Functional  
**Steps:** After review stage completes with at least one HITL stack.  
**Expected:** `lo_packages.status = "awaiting_review"`. UI banner says "Review needed".

### LO-TC-057: Terminal status — completed
**Priority:** High · **Type:** Functional  
**Steps:** Process a loan whose stacks all auto-accept.  
**Expected:** Status transitions to `decision_ready` (no HITL). Final-packet generation succeeds.

### LO-TC-058: Pipeline retry on transient failure
**Priority:** High · **Type:** Regression  
**Steps:** Kill the Temporal worker mid-classify; restart it.  
**Expected:** Workflow resumes from the failed activity. `lo_classifications` not duplicated (delete-then-insert idempotency).

### LO-TC-059: Pipeline pause — failed status
**Priority:** Medium · **Type:** Functional  
**Steps:** Force a non-retryable error (e.g., delete the source PDF mid-pipeline).  
**Expected:** Status `failed`. Error reason persisted on `lo_packages`. UI shows error banner with retry CTA.

---

## 9. Pipeline Progress UI (SSE)

### LO-TC-060: Pipeline progress polling
**Priority:** High · **Type:** UI  
**Steps:** Watch the loan card while pipeline runs.  
**Expected:** `pipeline-stages-bar` advances through ingest → classify → stack → validate → review. Active step in `--brand-purple`. Completed in `--brand-teal`.

### LO-TC-061: Pipeline SSE stream
**Priority:** Medium · **Type:** Functional  
**Steps:** DevTools Network → filter "EventStream" → confirm `GET /loans/{id}/pipeline/stream`.  
**Expected:** `text/event-stream` response. Frames emit on stage transitions. Stream closes cleanly on terminal status.

### LO-TC-062: Pipeline stream — terminal frame
**Priority:** Medium · **Type:** Regression  
**Steps:** Open SSE stream on a loan already at `decision_ready`.  
**Expected:** Single frame with `status: "decision_ready"`, `pipeline_stage: "review"`, then connection closes.

### LO-TC-063: Pipeline stream — 404 for missing loan
**Priority:** Low · **Type:** Functional  
**Steps:** Hit `GET /loans/{random-uuid}/pipeline/stream`.  
**Expected:** `404 Not Found` immediately, no stream opened.

---

## 10. LogikIntake — Loan Detail Page

### LO-TC-070: Loan header
**Priority:** High · **Type:** UI  
**Steps:** Open `/loans/{id}` for an `awaiting_review` loan.  
**Expected:** Header shows loan name, borrower, loan ref, status badge, **Audit** + **Advance** + **Reject/Re-upload** action buttons (when applicable).

### LO-TC-071: Document checklist
**Priority:** High · **Type:** Functional  
**Steps:** Verify checklist beneath header.  
**Expected:** Each configured doc type appears once with `received` boolean (true if at least one stack of that type exists). Required vs Optional clearly labeled.

### LO-TC-072: Stack list
**Priority:** Critical · **Type:** UI  
**Steps:** Scroll to stack cards.  
**Expected:** One card per stack. Card shows doc type, page range, confidence band (color-coded `--brand-teal`/`--brand-orange`/`--brand-charcoal`), HITL badge if `requires_hitl=true`.

### LO-TC-073: Confidence band — auto chip contrast
**Priority:** Medium · **Type:** Brand  
**Steps:** Inspect a high-confidence stack's "auto" chip.  
**Expected:** Text color `text-brand-charcoal` (not teal). Contrast ratio ≥ 4.5:1 on white background.

### LO-TC-074: Empty state
**Priority:** Low · **Type:** UI  
**Steps:** Open `/loans/{id}` for a loan with no stacks yet.  
**Expected:** Friendly empty state ("Processing in progress" or "No documents classified yet"), no JS errors.

### LO-TC-075: Status banner — emerald replaced
**Priority:** Medium · **Type:** Brand  
**Steps:** View a `decision_ready` loan.  
**Expected:** Success banner uses `border-brand-teal/40 bg-brand-teal/10 text-brand-charcoal` (NOT `emerald-*`). Brand-QA fix verification.

---

## 11. Document Validation (HITL flow)

### LO-TC-080: Open doc-validation sub-page
**Priority:** High · **Type:** Functional  
**Steps:** Click into `/loans/{id}/doc-validation` for an `awaiting_review` loan.  
**Expected:** Lists all stacks with `requires_hitl=true`. Each row has confidence breakdown, reason for HITL, and an Open/Review CTA.

### LO-TC-081: Open validation sub-page
**Priority:** High · **Type:** Functional  
**Steps:** Visit `/loans/{id}/validation`.  
**Expected:** Per-stack rule evaluations grouped by stack. Failed rules highlighted; passed rules collapsed by default.

### LO-TC-082: Soft-flag acknowledge
**Priority:** Critical · **Type:** Functional  
**Steps:** On a failed soft-flag rule, click **Acknowledge** → enter override note → submit.  
**Expected:** `POST /loans/{id}/validations/{check_id}/acknowledge` with `{override_note}`. Rule entry in `lo_validation_results.rules_evaluated[].acknowledged=true` with timestamp + note. UI moves the rule to "Acknowledged" section.

### LO-TC-083: Acknowledge passing rule rejected
**Priority:** Medium · **Type:** Functional  
**Steps:** Try to acknowledge a rule that is `passed=true`.  
**Expected:** `400 Bad Request` "Cannot acknowledge a passing rule". UI prevents the action.

### LO-TC-084: Acknowledge unknown rule 404
**Priority:** Low · **Type:** Functional  
**Steps:** Hit `POST /validations/{stack_id}__preset__no_such_rule/acknowledge`.  
**Expected:** `404 Not Found`.

### LO-TC-085: Acknowledge malformed check_id
**Priority:** Low · **Type:** Functional  
**Steps:** Hit `POST /validations/not-a-valid-id/acknowledge`.  
**Expected:** `400 Bad Request`.

---

## 12. Classification Confirm / Reclassify

### LO-TC-090: Open classify sub-page
**Priority:** High · **Type:** Functional  
**Steps:** From a HITL stack, click "Classify" → land on `/loans/{id}/classify/{docId}`.  
**Expected:** Page image (current page) renders with bbox overlays. Doc-type picker shown. Stack metadata sidebar.

### LO-TC-091: Confirm classification — accept
**Priority:** Critical · **Type:** Functional  
**Steps:** Click **Accept** without changing doc type.  
**Expected:** `POST /loans/{id}/documents/{stack_id}/classify` with empty body. Response `201` with `decision: "accept"`. `lo_stacks.status` → `accepted`, `requires_hitl` → `false`. Stack disappears from doc-validation queue.

### LO-TC-092: Confirm classification — reclassify
**Priority:** Critical · **Type:** Functional  
**Steps:** Pick a different doc type (e.g., URLA_1003 → PAYSTUB) → add note → submit.  
**Expected:** Body `{doc_type: "PAYSTUB", notes: "..."}`. Response with `decision: "reclassify"`. `lo_stacks.doc_type` swapped. Audit event `reclassified` recorded.

### LO-TC-093: Reclassify — unknown doc 404
**Priority:** Low · **Type:** Functional  
**Steps:** Hit endpoint with random stack UUID.  
**Expected:** `404 Not Found`.

### LO-TC-094: Page image fetch
**Priority:** High · **Type:** Functional  
**Steps:** DevTools Network on classify page.  
**Expected:** `GET /packages/{id}/pages/{page_id}/image` returns the rendered page JPEG. Status `200`. (This sub-router endpoint stays live post Phase 6.)

### LO-TC-095: Bbox overlay alignment
**Priority:** Medium · **Type:** UI  
**Steps:** On the page image, hover bbox overlays.  
**Expected:** Bboxes align to text fields visible in the image. Click highlights the corresponding field in the side panel.

---

## 13. Field Extraction & Overrides

### LO-TC-100: Open extract sub-page
**Priority:** High · **Type:** Functional  
**Steps:** Click "Extract" on an accepted stack → `/loans/{id}/extract/{docId}`.  
**Expected:** Page image renders below `<BboxPageOverlay>` (regression check — was missing before Phase 5 wiring). Field list with values, confidence, location.

### LO-TC-101: Field grounded vs ungrounded
**Priority:** Medium · **Type:** UI  
**Steps:** View a field with `status: "located"` vs `status: "low_confidence"`.  
**Expected:** Located → `grounded=true`, bbox visible on image. Low-confidence → `grounded=false`, no bbox, badge says "Needs review".

### LO-TC-102: PATCH single field — create override
**Priority:** Critical · **Type:** Functional  
**Steps:** Edit "Wages" from "$72,000" to "$74,500" → save.  
**Expected:** `PATCH /loans/{id}/extractions/{stack_id}/fields/Wages` with `{value: "$74,500"}`. `lo_extraction_overrides` row created (one per field). Field shows `edited=true` badge.

### LO-TC-103: PATCH idempotency
**Priority:** Medium · **Type:** Functional  
**Steps:** PATCH the same field twice with different values.  
**Expected:** Single override row updated (not two). Latest value persists.

### LO-TC-104: GET merges overrides
**Priority:** High · **Type:** Functional  
**Steps:** `GET /loans/{id}/extractions/{stack_id}` after a PATCH.  
**Expected:** Field's `value` reflects override; original AI value preserved in `original_value`. `edited=true`.

### LO-TC-105: Unknown stack 404
**Priority:** Low · **Type:** Functional  
**Steps:** GET extraction for a random stack UUID.  
**Expected:** `404 Not Found`.

---

## 14. Reject + Re-upload Flow (Phase 6 — newly wired)

### LO-TC-110: Open remediation modal
**Priority:** Critical · **Type:** Functional  
**Steps:** On an HITL stack, click **Remediate**.  
**Expected:** Modal with two ActionRows: **Reject document** (destructive tone) and **Re-upload corrected file**. Shared notes textarea visible.

### LO-TC-111: Reject — inline confirm
**Priority:** Critical · **Type:** Functional  
**Steps:** Click Reject → "Are you sure?" inline confirm → Confirm.  
**Expected:** `POST /loans/{id}/documents/{stack_id}/reject` with `{notes}`. `lo_stacks.status` → `rejected`. Audit event `rejected` recorded with notes. Stack vanishes from review queue.

### LO-TC-112: Reject — cancel
**Priority:** Medium · **Type:** Functional  
**Steps:** Click Reject → click Cancel on confirm.  
**Expected:** No request fired. Stack unchanged.

### LO-TC-113: Re-upload — file picker
**Priority:** Critical · **Type:** Functional  
**Steps:** Click Re-upload → pick a corrected PDF → submit.  
**Expected:** Hidden `<input type="file" accept="application/pdf">` triggered. `POST /loans/{id}/documents/{stack_id}/reupload` multipart. Response `201`. Audit event `reuploaded`. Stack re-enters classify pipeline.

### LO-TC-114: Re-upload — non-PDF rejected
**Priority:** Medium · **Type:** Functional  
**Steps:** Pick a `.png` from the file dialog.  
**Expected:** OS file dialog filters to PDFs only (because of `accept="application/pdf"`). If user selects "All files" and picks .png → backend `400 Bad Request`.

### LO-TC-115: Re-upload — notes propagate
**Priority:** Medium · **Type:** Functional  
**Steps:** Add notes "Borrower sent corrected paystub" before re-uploading.  
**Expected:** Notes stored on the audit event and visible in the audit drawer.

### LO-TC-116: Network failure during reject
**Priority:** Low · **Type:** Functional  
**Steps:** DevTools → throttle to "Offline" → click Confirm reject.  
**Expected:** Error toast "Failed to reject — try again". Stack state unchanged. No partial update.

---

## 15. Audit Drawer (Phase 6 — newly wired)

### LO-TC-120: Open audit drawer
**Priority:** High · **Type:** UI  
**Steps:** Click **Audit** in loan header.  
**Expected:** Slide-out drawer renders. `GET /loans/{id}/audit-events` fires. Loading skeleton shown briefly.

### LO-TC-121: Event types
**Priority:** High · **Type:** Functional  
**Steps:** Trigger several actions (upload, classify, accept, reject, re-upload, override) and reopen drawer.  
**Expected:** Each action surfaces with distinct icon + label. Verify all 17 mapped action strings render correctly: `created`, `uploaded`, `processing_started`, `classified`, `accepted`, `rejected`, `reclassified`, `reuploaded`, `field_overridden`, `acknowledged`, `hard_stop_overridden`, `advanced`, `decision_ready`, `pipeline_failed`, `pipeline_retried`, `note_added`, `assigned`.

### LO-TC-122: Event metadata describe()
**Priority:** Medium · **Type:** UI  
**Steps:** View a `field_overridden` event.  
**Expected:** Description pulls from metadata: "Wages: $72,000 → $74,500". Reject events show notes; reupload events show new file name.

### LO-TC-123: Empty state
**Priority:** Low · **Type:** UI  
**Steps:** Open drawer for a fresh loan (no events yet).  
**Expected:** "No activity yet" empty state, no errors.

### LO-TC-124: Chronological order
**Priority:** Medium · **Type:** Functional  
**Steps:** Trigger 5 distinct actions over a minute.  
**Expected:** Events listed newest-first. Timestamps human-readable ("just now", "2 minutes ago").

### LO-TC-125: Drawer closes on escape
**Priority:** Low · **Type:** UI  
**Steps:** Press `Esc` while drawer open.  
**Expected:** Drawer closes. Focus returns to Audit button.


---

## 16. Hard-Stop Overrides

### LO-TC-130: Hard-stop banner appears
**Priority:** Critical · **Type:** Functional  
**Steps:** Process a loan that triggers a hard-stop validation rule (e.g., missing notarization on a deed).  
**Expected:** Red hard-stop banner renders on loan detail page. **Advance** button disabled. Banner lists each blocking rule with rule_id + reason.

### LO-TC-131: Override requires reason
**Priority:** Critical · **Type:** Functional  
**Steps:** Click **Override Hard-Stop** without typing a reason.  
**Expected:** Submit button disabled until reason ≥ 10 chars entered.

### LO-TC-132: Override audit event
**Priority:** High · **Type:** Functional  
**Steps:** Submit override with reason "Approved by underwriter — see ticket #123".  
**Expected:** `POST /loans/{id}/hard-stop-overrides` succeeds. Audit drawer shows `hard_stop_overridden` event with reason + actor.

### LO-TC-133: Stage advance unblocked
**Priority:** Critical · **Type:** Functional  
**Steps:** After override, click **Advance**.  
**Expected:** Stage advances; banner replaced by yellow "1 hard-stop overridden" indicator.

### LO-TC-134: Authorization
**Priority:** High · **Type:** Authorization  
**Steps:** Log in as Member role (not Admin/Owner). Attempt override.  
**Expected:** Either button hidden OR API returns 403. No silent success.

### LO-TC-135: Multiple overrides
**Priority:** Medium · **Type:** Functional  
**Steps:** Loan with 2 hard-stops; override each separately.  
**Expected:** Both audit events recorded; advance only enabled after both cleared.

---

## 17. Stage Advance

### LO-TC-140: Advance gate — incomplete stack
**Priority:** Critical · **Type:** Functional  
**Steps:** Loan has 1 stack still in `needs_review`. Click **Advance**.  
**Expected:** Toast "Cannot advance — N stack(s) need review". Stage unchanged.

### LO-TC-141: Advance gate — pending fields
**Priority:** High · **Type:** Functional  
**Steps:** All stacks accepted but a required field still empty. Click **Advance**.  
**Expected:** Advance blocked with field-level error message.

### LO-TC-142: Successful advance
**Priority:** Critical · **Type:** Functional  
**Steps:** All gates green. Click **Advance**.  
**Expected:** `POST /loans/{id}/advance` returns 200. Stage chip updates. `advanced` audit event recorded with from→to stage.

### LO-TC-143: Final stage → decision_ready
**Priority:** Critical · **Type:** Functional  
**Steps:** Advance from final review stage.  
**Expected:** Loan status transitions to `decision_ready`. Final packet section unlocks. `decision_ready` audit event recorded.

### LO-TC-144: Cannot advance past final
**Priority:** Medium · **Type:** Functional  
**Steps:** From `decision_ready` state, attempt advance.  
**Expected:** Advance button hidden or returns 409. No state change.

### LO-TC-145: Optimistic UI rollback
**Priority:** Medium · **Type:** UI  
**Steps:** Force advance API to fail (kill backend mid-call).  
**Expected:** Frontend reverts stage chip; error toast shown; no stale state.

### LO-TC-146: Concurrent advance
**Priority:** Low · **Type:** Functional  
**Steps:** Two browser tabs open same loan. Click Advance simultaneously.  
**Expected:** First succeeds, second receives 409 Conflict (stale stage). No double-advance.

---

## 18. Final Packet Download

### LO-TC-150: Generate final packet
**Priority:** Critical · **Type:** Functional  
**Steps:** From `decision_ready` loan, click **Download Final Packet**.  
**Expected:** `GET /loans/{id}/final-packet` streams a single PDF. File name format: `loan_<id>_final_packet.pdf`.

### LO-TC-151: Packet contents
**Priority:** Critical · **Type:** Functional  
**Steps:** Open downloaded PDF.  
**Expected:** Cover page with loan summary + decision metadata. Each accepted stack rendered in canonical order with extracted fields. TOC links navigable.

### LO-TC-152: Packet excludes rejected stacks
**Priority:** High · **Type:** Functional  
**Steps:** Loan has 1 rejected stack + 5 accepted. Download packet.  
**Expected:** Only the 5 accepted stacks present. Rejected stack omitted entirely.

### LO-TC-153: Cached packet
**Priority:** Medium · **Type:** Performance  
**Steps:** Download packet twice in succession.  
**Expected:** Second download served from cache (< 500ms). Same content hash.

---

## 19. Customer Tree URLs (`/org/{slug}/...`)

### LO-TC-160: Slug-prefixed loan list
**Priority:** Critical · **Type:** Routing  
**Steps:** Navigate to `/org/society-title/apps/loan-onboarding`.  
**Expected:** Renders loan queue scoped to that org (matches `useOrg()` slug).

### LO-TC-161: Slug-prefixed loan detail
**Priority:** Critical · **Type:** Routing  
**Steps:** `/org/society-title/apps/loan-onboarding/loans/{loanId}`.  
**Expected:** Loan detail renders with same data as `/apps/...` route.

### LO-TC-162: Cross-org access denied
**Priority:** Critical · **Type:** Security  
**Steps:** Logged in as `admin@societytitle.com`, navigate to `/org/grid151/apps/loan-onboarding`.  
**Expected:** 403 or redirect to /dashboard. No data leak.

### LO-TC-163: Slug mismatch with active org
**Priority:** High · **Type:** Routing  
**Steps:** URL slug doesn't match Zustand `org-store` current org.  
**Expected:** Either auto-switch org with confirmation, or show "wrong org" error.

### LO-TC-164: Legacy `/packages/` redirect under slug tree
**Priority:** High · **Type:** Routing  
**Steps:** `/org/society-title/apps/loan-onboarding/packages/{loanId}/processing`.  
**Expected:** 301 to `/org/society-title/apps/loan-onboarding/loans/{loanId}` (per `next.config.js` redirects).

---

## 20. Brand Compliance QA

### LO-TC-170: Typography — Mona Sans active
**Priority:** High · **Type:** Visual  
**Steps:** Reload app in a clean browser session. Inspect `<body>` computed font.  
**Expected:** `font-family` resolves to `Mona Sans` first (self-hosted via `next/font/google`, exposed as `--font-mona-sans`). No external font-CDN request in Network tab.

### LO-TC-171: Typography — fallback chain
**Priority:** High · **Type:** Visual  
**Steps:** Block the Mona Sans woff2 asset in devtools and reload.  
**Expected:** Computed font falls through to Arial → Helvetica → sans-serif. Layout intact, no flash of unstyled text outside acceptable FOUT.

### LO-TC-172: Color tokens — no off-palette hex
**Priority:** High · **Type:** Code Quality  
**Steps:** `grep -rE "#[0-9A-Fa-f]{6}" frontend/src/app/(platform)/apps/loan-onboarding`  
**Expected:** Zero raw hex literals. All colors via `brand-*` Tailwind tokens.

### LO-TC-173: Brand status pills
**Priority:** Medium · **Type:** Visual  
**Steps:** View loan queue with mixed statuses.  
**Expected:** Pills use brand-teal (active), brand-orange (review), brand-purple (decision_ready). No raw amber/red/green from default Tailwind palette.

### LO-TC-174: CSP — no external font CDN
**Priority:** High · **Type:** Security  
**Steps:** Open browser devtools → Network → Console. Reload the app.  
**Expected:** Mona Sans woff2 served from same-origin `/_next/static/media/...`. No requests to `use.typekit.net`, `fonts.googleapis.com`, or `fonts.gstatic.com`. Zero CSP violation entries in console.

---

## 21. Admin Pages

### LO-TC-180: Doc Types CRUD
**Priority:** High · **Type:** Functional  
**Steps:** As Admin, navigate to Loan Onboarding → Doc Types. Add/edit/delete a doc type.  
**Expected:** Changes persist via `/admin/lo/doc-types`. Visible in next loan upload's doc-type-config selector.

### LO-TC-181: Validation Rules — preset
**Priority:** High · **Type:** Functional  
**Steps:** Toggle a preset rule (e.g., `missing_signatures`) on/off.  
**Expected:** Toggle persists; new loans inherit current preset state.

### LO-TC-182: Validation Rules — custom NL
**Priority:** High · **Type:** Functional  
**Steps:** Add custom NL rule "Reject if income < $30,000".  
**Expected:** Rule saved, validated for syntax, dispatched to StackValidatorAgent on next pipeline run.

### LO-TC-183: Program Profiles
**Priority:** Medium · **Type:** Functional  
**Steps:** Create program profile bundling doc-type config + rule set.  
**Expected:** Profile selectable at loan creation; pre-fills config.

### LO-TC-184: Global Settings — HITL threshold
**Priority:** High · **Type:** Functional  
**Steps:** Change `LO_HITL_THRESHOLD` from 0.75 → 0.85 in global settings.  
**Expected:** New loans use 0.85 floor. Existing in-flight loans unaffected (per-package value preserved).

### LO-TC-185: Settings authorization
**Priority:** Critical · **Type:** Authorization  
**Steps:** Log in as Member. Visit admin settings URL.  
**Expected:** Redirected to /dashboard or shown 403. Settings invisible in nav.

---

## 22. Error & Edge Cases

### LO-TC-190: PDF corruption
**Priority:** High · **Type:** Error  
**Steps:** Upload a truncated/corrupted PDF.  
**Expected:** Pipeline marks loan `failed` with stage=`ingest`. Error message surfaced in UI. No partial DB state.

### LO-TC-191: AI provider timeout
**Priority:** High · **Type:** Error  
**Steps:** Block outbound traffic to Vertex AI / Anthropic during classify.  
**Expected:** Stage retries 3x with exponential backoff. After max retries, loan marked `failed` with clear error.

### LO-TC-192: Storage failure
**Priority:** High · **Type:** Error  
**Steps:** Make `STORAGE_PATH` read-only mid-upload.  
**Expected:** Upload returns 500 with descriptive error. No orphan DB rows.

### LO-TC-193: Concurrent re-upload race
**Priority:** Medium · **Type:** Functional  
**Steps:** Two users re-upload to same rejected stack within 1s.  
**Expected:** One succeeds; second returns 409 with "stack already has pending re-upload".

### LO-TC-194: SSE disconnect/reconnect
**Priority:** Medium · **Type:** Resilience  
**Steps:** Drop network for 10s mid-pipeline. Restore.  
**Expected:** SSE auto-reconnects. Progress catches up. Final state correct.

### LO-TC-195: Browser refresh mid-pipeline
**Priority:** Medium · **Type:** UI  
**Steps:** Refresh during processing.  
**Expected:** Page renders with current progress; SSE resumes. No loss of state.

---

## 23. Performance & Smoke

### LO-TC-200: Cold-start ingest (50pp)
**Priority:** High · **Type:** Performance  
**Steps:** Upload 50pp PDF, no AI cache.  
**Expected:** End-to-end pipeline < 90s.

### LO-TC-201: Warm-cache re-run
**Priority:** Medium · **Type:** Performance  
**Steps:** Delete loan, re-upload identical PDF (same content hash).  
**Expected:** Classify stage hits cache, completes < 5s. Total < 30s.

### LO-TC-202: Large packet (200pp)
**Priority:** Medium · **Type:** Performance  
**Steps:** Upload 200pp loan-package-final-packet.pdf.  
**Expected:** Pipeline completes < 5min. UI remains responsive throughout.

### LO-TC-203: Concurrent pipelines
**Priority:** Medium · **Type:** Performance  
**Steps:** Trigger 5 loans simultaneously.  
**Expected:** All complete without deadlock. Temporal queue depth normal. No DB connection exhaustion.

### LO-TC-204: Smoke — happy path
**Priority:** Critical · **Type:** Smoke  
**Steps:** Login → create loan → upload `loan-package-final-packet.pdf` → wait for completion → review stacks → accept all → advance → download final packet.  
**Expected:** Every step succeeds first time. Total elapsed < 5min including human review.

---

## Exit Criteria & Sign-off

**Mandatory pass:** All `Priority: Critical` cases (LO-TC-001, 002, 003, 010, 020, 030, 040, 050, 070, 080, 130, 131, 133, 140, 142, 143, 150, 151, 160, 161, 162, 185, 204).

**Acceptable failure (with ticket):** Up to 3 `Priority: Low` cases may regress, must be filed as non-blocking issues.

**Brand compliance:** LO-TC-170 through LO-TC-174 must all pass — typography and palette are guideline mandates.

**Sign-off roles:**
- QA Lead — overall test execution
- Product — UX/UI parity with refactor spec
- Security — LO-TC-001, 005, 006, 134, 162, 185
- Engineering — LO-TC-190 through 195 error paths

---

**Document end.**
