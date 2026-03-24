# Title Intelligence — E2E Browser Test Scenarios

End-to-end test scenarios for manually verifying the Title Intelligence micro app from the browser.

## Prerequisites

- Backend running on `localhost:8000`, frontend on `localhost:3000`
- Database seeded (`python scripts/seed.py`) — creates `admin@logikality.com` / `admin123`
- A sample title commitment PDF ready for upload

---

## Scenario 1: Platform Admin Login & Customer Onboarding

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `localhost:3000` | Redirected to `/login` |
| 2 | Login as `admin@logikality.com` / `admin123` | Redirected to `/dashboard`, sidebar shows admin nav |
| 3 | Go to **Admin > Accounts** | "Customer Accounts" page loads |
| 4 | Click **New Customer** | Form expands with company name, admin name, email, password fields |
| 5 | Fill form: `Acme Title Co`, `Jane Smith`, `jane@acme.com`, `password123` | Fields populated |
| 6 | Toggle **Title Intelligence** app chip | Chip turns primary color with checkmark |
| 7 | Click **Create Account** | Success message, account appears in list as "Active" |
| 8 | Logout (top-right) | Redirected to `/login` |

---

## Scenario 2: Customer Login & Org Setup

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as `jane@acme.com` / `password123` | Redirected to `/dashboard` |
| 2 | Verify sidebar | "Title Intelligence" link visible under apps |
| 3 | Verify dashboard | Title Intelligence card shows as subscribed app |
| 4 | Click **Title Intelligence** in sidebar | Pack list page loads, empty state: "No packs yet" |

---

## Scenario 3: Pack Creation & Upload

| Step | Action | Expected |
|------|--------|----------|
| 1 | On pack list, click **Upload Pack** | Navigates to `/apps/title-intelligence/packs/new` |
| 2 | Enter pack name: "Test Commitment" | Name field populated |
| 3 | Drag-and-drop a PDF onto the dropzone | File appears in the file list with name + size |
| 4 | Add a second PDF | Both files listed with remove buttons |
| 5 | Click remove (x) on second file | Second file removed, one file remains |
| 6 | Click **Upload & Process** | Loading state shows, then redirects to pack detail page |
| 7 | Verify pack detail | Pack name "Test Commitment", status badge shows "Processing" |

---

## Scenario 4: Pipeline Progress Monitoring

| Step | Action | Expected |
|------|--------|----------|
| 1 | On pack detail page during processing | Pipeline component visible with stage circles |
| 2 | Watch pipeline auto-update (polls every 3s) | Stages transition: ingest > render > ocr > index > ingestion_agent > risk_agent > complete |
| 3 | Completed stages show checkmarks | Green/amber circles with check icons |
| 4 | Current stage shows spinner | Animated spinner on active stage |
| 5 | Pending stages show empty circles | Muted gray circles |
| 6 | When pipeline completes | Status badge changes to "Completed", action buttons appear |

---

## Scenario 5: Results Page — Readiness Dashboard

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **View Results** on pack detail | Navigates to results page |
| 2 | Verify readiness dashboard at top | Donut chart with score, status label (Ready/At Risk/Not Ready) |
| 3 | Check open flags breakdown | Colored severity pills with counts |
| 4 | Check category scorecard | 5 category cards with scores and icons |
| 5 | If AI summary present | Amber box with sparkle icon and summary text |

---

## Scenario 6: Results — Flags Tab

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **Flags** tab | Flag list loads with severity badges |
| 2 | Click a flag row | Row expands showing description, evidence refs |
| 3 | If flag has AI explanation | Amber "AI Recommendation" box with sparkle icon visible |
| 4 | Click page reference link (e.g., "p.3") | Navigates to document viewer at that page |
| 5 | Navigate back, click **Approve** (green check) on a flag | Flag status changes to approved, progress bar updates |
| 6 | Click **Reject** (red X) on another flag | Flag status changes to rejected |
| 7 | Click **Escalate** (amber triangle) on a flag | Flag status changes to escalated |
| 8 | Verify pagination | If >10 flags, pagination controls work correctly |

---

## Scenario 7: Results — Checklist Tab

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **Checklist** tab | Progress bar shows "X of Y cleared" |
| 2 | Click an expandable item (has chevron) | Expands to show detail and/or AI recommendation |
| 3 | Items with flag actions | Approve/reject/escalate buttons visible inline |
| 4 | Take action on a flag-linked item | Item resolves, strikethrough applied, progress bar updates |
| 5 | Resolved items | Green background, checkmark icon, strikethrough text |
| 6 | Items with severity | Severity badge visible on the right |

---

## Scenario 8: Results — Extractions Tab

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **Extractions** tab | Filter pills at top: All, Parties, Property Info, Requirements, Exceptions, Endorsements, Legal Description |
| 2 | Click a type filter pill (e.g., "Parties") | Only party extractions shown, pill highlighted |
| 3 | Click "All" pill | All extractions shown again |
| 4 | Click an extraction row | Expands to show all key-value pairs |
| 5 | Click again | Collapses back to summary |
| 6 | Check page references | "p.X" badges on rows with evidence |
| 7 | Verify pagination | Navigation works, expanded rows reset on page change |

---

## Scenario 9: Document Viewer

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **View Pages** on pack detail (or page link from flags) | Full-screen document viewer loads |
| 2 | Left sidebar shows page thumbnails | Thumbnails load with page numbers |
| 3 | Click a thumbnail | Main view jumps to that page |
| 4 | Toggle **Sections** panel | Right panel shows detected document sections (Schedule A/B/C etc.) |
| 5 | Toggle **OCR** panel | OCR text overlay or panel appears for current page |
| 6 | Use page number input in toolbar | Navigates to entered page |
| 7 | Use prev/next controls | Pages navigate sequentially |

---

## Scenario 10: AI Chat

| Step | Action | Expected |
|------|--------|----------|
| 1 | Click **AI Chat** on pack detail | Chat panel opens (slide panel or full page) |
| 2 | Type "What parties are involved in this commitment?" | Message sent, loading indicator shows |
| 3 | AI response streams in (SSE) | Text appears progressively with citations |
| 4 | Citations reference specific pages | Clickable page references in response |
| 5 | Ask follow-up: "Are there any exceptions I should be concerned about?" | Context-aware response referencing pack data |
| 6 | Verify message history persists | Previous messages visible in chat |

---

## Scenario 11: Report Export

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to results page, click **Exports** tab (or export button) | Export panel loads |
| 2 | Select audience: "Underwriter" | Audience selected |
| 3 | Select format: "PDF" | Format selected |
| 4 | Click **Generate Report** | Loading state, then download link appears |
| 5 | Try "Markdown" format | Markdown report generated |
| 6 | Try "JSON" format | JSON report generated |
| 7 | Try different audience: "Buyer" | Report tailored to buyer audience |

---

## Scenario 12: Pack List Management

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `/apps/title-intelligence` | Pack list shows "Test Commitment" with "Completed" badge |
| 2 | Verify pack metadata | Shows file count, creation date |
| 3 | Click pack row | Navigates to pack detail |
| 4 | Upload a second pack | Both packs listed, sorted by creation date |

---

## Scenario 13: Error Handling

| Step | Action | Expected |
|------|--------|----------|
| 1 | Stop the backend server | Next API call shows error state |
| 2 | Navigate to pack detail | Error boundary catches, shows "Something went wrong" with retry |
| 3 | Navigate to non-existent pack ID | Error state or 404 handling |
| 4 | Upload an invalid file (non-PDF) | Upload validation error message |
| 5 | Restart backend, click retry | Page recovers and loads correctly |

---

## Scenario 14: Multi-Tenant Isolation

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as admin, create a second customer org | Second org created |
| 2 | Login as second org user | Dashboard loads with their org context |
| 3 | Navigate to Title Intelligence | Pack list is empty (no cross-org data leak) |
| 4 | Upload a pack in org 2 | Pack only visible to org 2 |
| 5 | Login back as org 1 user | Only org 1's packs visible |

---

## Scenario 15: Pipeline Failure Recovery

| Step | Action | Expected |
|------|--------|----------|
| 1 | Upload a pack that triggers a pipeline failure (e.g., corrupted PDF) | Pipeline starts processing |
| 2 | Watch pipeline progress | Stage fails, status changes to "Failed" |
| 3 | Error message displayed | Red error box with failure details on pack detail page |
| 4 | Verify pack can be re-processed if endpoint exists | "Retry" or "Reprocess" option available |

---

## Quick Smoke Test (5-minute version)

If you need a fast sanity check:

1. Login as admin > create customer account with TI subscription
2. Login as customer > go to Title Intelligence
3. Upload a PDF > verify auto-process starts
4. Wait for pipeline completion (~2-10 min depending on PDF size)
5. Open results > verify flags, extractions, and readiness dashboard populate
6. Approve one flag > verify status updates
7. Open document viewer > verify pages render
8. Ask a chat question > verify AI responds with citations
