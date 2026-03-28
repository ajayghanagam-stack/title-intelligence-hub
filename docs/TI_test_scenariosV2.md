# Title Intelligence — UI Test Scenarios V2

Manual UI test scenarios for all 15 gap stories (TI-GAP-001 through TI-GAP-015).

**Prerequisites:**
- Dev environment running (`backend :8000`, `frontend :3000`)
- Logged in as a customer user (not platform admin)
- At least one pack uploaded and fully processed (status: `completed`)
- At least one pack currently processing (for in-progress scenarios)

---

## 1. Upload Page (TI-GAP-009, TI-GAP-013)

### TC-1.1: Upload page wording and layout
1. Navigate to **Title Intelligence > Upload** (sidebar)
2. **Verify:**
   - Page title reads **"Upload Documents"**
   - Subtitle reads "Upload your title search package files for AI-powered analysis."
   - Dropzone text reads **"Upload a Title Search Package"**
   - Dropzone description mentions "Supports PDF, PNG, and JPEG files"
   - Submit button is full-width, sky-blue, and reads **"Analyze Package"**
   - Submit button is disabled when no files are selected or pack name is empty

### TC-1.2: Upload PDF files
1. Enter a pack name (e.g., "Test PDF Upload")
2. Click "Select Files" and choose one or more `.pdf` files
3. **Verify:**
   - Files appear in the list below the dropzone with name + size in MB
   - Hovering a file row reveals an X button to remove it
4. Click **"Analyze Package"**
5. **Verify:** Button text changes to "Creating pack..." then "Uploading files..." and redirects to the pack detail page

### TC-1.3: Upload PNG/JPEG files
1. Enter a pack name (e.g., "Test Image Upload")
2. Click "Select Files" and choose `.png`, `.jpg`, or `.jpeg` files
3. **Verify:** Files are accepted and listed (not rejected by the file picker)
4. Click **"Analyze Package"**
5. **Verify:** Upload completes and redirects to pack detail

### TC-1.4: Drag and drop files
1. Drag a PDF file onto the dropzone area
2. **Verify:** Border turns primary color and background highlights during drag
3. Drop the file
4. **Verify:** File appears in the list
5. Repeat with a `.png` file — should also be accepted
6. Drag a `.txt` file — **Verify:** File is filtered out (not added to list)

### TC-1.5: Remove file from list
1. Add multiple files to the upload list
2. Hover over a file row and click the X button
3. **Verify:** File is removed from the list; other files remain

---

## 2. Results Page — Header (TI-GAP-001, TI-GAP-002, TI-GAP-011)

### TC-2.1: Property address header
1. Navigate to a **completed** pack's results page
2. **Verify:**
   - The main header shows the **AI-extracted property address** (e.g., "675 BUNKER HILL ROAD, COLUMBIA, MS 39429-7832")
   - If no address was extracted, the header falls back to the **pack name**
   - Address text is bold and prominent

### TC-2.2: Order metadata line
1. On the same results page, look below the property address
2. **Verify:**
   - A metadata line shows: **"Order No: {value} | Commitment Date: {value} | Issued by: {value}"**
   - If a field was not extracted, that field is omitted gracefully (no "undefined" or empty labels)
   - Separator `|` only appears between present fields

### TC-2.3: Analyzed timestamp
1. On a completed pack's results page, look at the top-right area
2. **Verify:**
   - Text reads **"Analyzed on {M/D/YYYY} at {HH:MM AM/PM}"** (e.g., "Analyzed on 3/25/2026 at 02:30 PM")
   - Timestamp matches the pack's `updated_at` value
3. Navigate to a pack that is still processing
4. **Verify:** The "Analyzed on" timestamp is **not shown** (or shows processing status instead)

---

## 3. Results Page — Summary Cards (TI-GAP-003)

### TC-3.1: Summary card display
1. Navigate to a completed pack's results page
2. **Verify** four cards appear in a horizontal row above the flags section:
   | Card | Color Accent | Content |
   |------|-------------|---------|
   | Critical Issues | Red (left border) | Count of flags with severity `critical` |
   | Warnings | Amber (left border) | Count of flags with severity `high` or `medium` |
   | Under Review | Blue (left border) | Count of flags with status `escalated` |
   | Validation Score | Green (left border) | Readiness score as "X / 10" |

### TC-3.2: Summary card counts are accurate
1. Count the flags in the table by severity and status
2. **Verify:** Card counts match:
   - Critical Issues = number of `critical` severity flags
   - Warnings = number of `high` + `medium` severity flags
   - Under Review = number of `escalated` status flags
   - Validation Score = readiness_score / 10 (rounded to 1 decimal)

### TC-3.3: Cards update after flag action
1. Find a `critical` severity flag with status `open`
2. Click the green checkmark (Approve) quick action
3. **Verify:** The "Under Review" or status counts may update; the critical count stays the same (severity doesn't change)
4. Escalate a flag using the yellow triangle button
5. **Verify:** "Under Review" count increases by 1

---

## 4. Results Page — Inline Question (TI-GAP-007)

### TC-4.1: Ask a question input display
1. Navigate to a completed pack's results page
2. **Verify:** An input field with placeholder **"Ask a question about this package..."** and an **"Ask"** button appears between the summary cards and the Exceptions section

### TC-4.2: Submit a question
1. Type a question (e.g., "What are the main risks in this commitment?")
2. Click **"Ask"** or press Enter
3. **Verify:**
   - The chat slide panel opens from the right
   - The question is automatically sent as the first message
   - An AI response streams in
   - The inline input field is cleared

### TC-4.3: Empty question
1. Leave the input field empty and click "Ask"
2. **Verify:** Nothing happens (button should be disabled or no action taken)

---

## 5. Results Page — Section Header & Tabs (TI-GAP-012)

### TC-5.1: Section header wording
1. Navigate to a completed pack's results page
2. Scroll to the flags/exceptions section
3. **Verify:**
   - Section header reads **"Exceptions & Required Actions"** (not "Risk Flags")
   - Subtitle reads **"Issues identified requiring resolution prior to closing"**

### TC-5.2: Tab labels
1. Look at the tab bar in the results page
2. **Verify:** The tab previously labeled "Risk Flags" now reads **"Exceptions & Required Actions"**

---

## 6. Results Page — Re-analyze Button (TI-GAP-006)

### TC-6.1: Re-analyze button display
1. Navigate to a completed pack's results page
2. **Verify:** A **"Re-analyze"** button with a refresh icon is visible in the header area (near the Export button)

### TC-6.2: Re-analyze confirmation
1. Click the **"Re-analyze"** button
2. **Verify:** A confirmation dialog appears with message: "This will reprocess the entire package through the AI pipeline. All existing analysis results will be replaced."
3. Click **"Cancel"**
4. **Verify:** Dialog closes, nothing happens

### TC-6.3: Re-analyze execution
1. Click **"Re-analyze"** again
2. Click **"Re-analyze"** in the confirmation dialog
3. **Verify:**
   - The pipeline restarts (pack status goes to `processing`)
   - The page shows processing/progress indicators
   - When processing completes, results are refreshed with new analysis

### TC-6.4: Re-analyze while processing
1. While a pack is still processing, check the Re-analyze button
2. **Verify:** The button is **disabled** (greyed out, not clickable)

---

## 7. Flags Table — Exception IDs (TI-GAP-010)

### TC-7.1: Exception ID display
1. Navigate to a completed pack's results page with flags
2. **Verify:**
   - Each flag row shows an ID in the format **"EX-001"**, **"EX-002"**, etc.
   - IDs are sequential, zero-padded to 3 digits
   - ID is the first element in each row (monospace font)

### TC-7.2: Exception ID stability
1. Note the exception IDs on the page
2. Refresh the page (F5)
3. **Verify:** IDs remain the same (they are derived from sort order, not random)

### TC-7.3: Exception IDs across pages
1. If there are more than 10 flags, navigate to page 2 of the flags table
2. **Verify:** IDs continue sequentially (e.g., page 2 starts at EX-011)

---

## 8. Flags Table — Required Action Column (TI-GAP-004, TI-GAP-015)

### TC-8.1: Required action in collapsed row
1. On a desktop/wide screen (1024px+), view the flags table
2. **Verify:**
   - Each collapsed flag row shows a "Required Action" text snippet
   - Text is truncated with ellipsis if too long (max ~200px wide)
   - Content is the first sentence from the flag's AI explanation

### TC-8.2: Required action in expanded row
1. Click on a flag row to expand it
2. **Verify:** The full AI explanation is visible in the expanded section (not truncated)

### TC-8.3: Required action on mobile
1. Resize browser to a narrow width (< 1024px)
2. **Verify:** The Required Action column is **hidden** (responsive, only shown on `lg:` screens)

---

## 9. Flags Table — Document Reference (TI-GAP-008)

### TC-9.1: Document ref in collapsed row
1. View flags that have `evidence_refs` data
2. **Verify:**
   - Each flag shows a document reference badge (e.g., **"Page 3"**)
   - Badge has a file icon and primary color styling
   - If a flag has multiple evidence refs, it shows **"+N"** indicator (e.g., "Page 3 +2")

### TC-9.2: No evidence refs
1. Find a flag with no evidence_refs (if any exist)
2. **Verify:** No document ref badge is shown (empty space, no errors)

### TC-9.3: Evidence refs in expanded row
1. Expand a flag with multiple evidence refs
2. **Verify:**
   - All evidence refs are listed under an **"Evidence (N)"** header
   - Each ref shows page number and quoted text snippet (if available)

---

## 10. Flags Table — Table Header Row (TI-GAP-015)

### TC-10.1: Table header display
1. On a desktop screen (1024px+), view the flags table
2. **Verify:** A header row appears above the flag rows with columns:
   - (expand icon space) | **ID** | **Severity** | **Description** | **Doc Ref** | **Required Action** | **Status** | **Actions**

### TC-10.2: Table header on mobile
1. Resize to narrow width (< 1024px)
2. **Verify:** Table header row is **hidden** (flags display as cards without header)

---

## 11. Flags Table — Quick Actions (Existing + Verify)

### TC-11.1: Approve a flag
1. Find an `open` status flag
2. Click the green checkmark icon
3. **Verify:** Flag status changes to `approved` (green badge)

### TC-11.2: Reject a flag
1. Find an `open` status flag
2. Click the red X icon
3. **Verify:** Flag status changes to `rejected` (red badge)

### TC-11.3: Escalate a flag
1. Find an `open` status flag
2. Click the amber triangle icon
3. **Verify:** Flag status changes to `escalated` (purple badge)

### TC-11.4: Actions hidden for non-open flags
1. Find a flag that is already `approved`, `rejected`, or `escalated`
2. **Verify:** Quick action buttons are **not shown** for that row

---

## 12. Sidebar — Recent Packs (TI-GAP-005)

### TC-12.1: Recent packs section display
1. Navigate to any Title Intelligence page
2. **Verify:**
   - Sidebar shows a **"Recent Packages"** section below the navigation items
   - Lists up to 5 most recent packs

### TC-12.2: Recent pack entry content
1. Look at each entry in the Recent Packages list
2. **Verify:**
   - Pack name is shown (truncated if too long)
   - Date is shown below the name (formatted as locale date)
   - Status dot color:
     - Green = `completed`
     - Amber (pulsing) = `processing`
     - Red = `failed`
     - Grey = other statuses

### TC-12.3: Click a recent pack
1. Click on a recent pack entry
2. **Verify:** Navigates to `/apps/title-intelligence/packs/{packId}/results`

### TC-12.4: Active pack highlight
1. Navigate to a specific pack's results page
2. **Verify:** That pack is visually highlighted in the Recent Packages list (active state styling)

### TC-12.5: Recent packs not shown for platform admin
1. Log in as `admin@logikality.com` (platform admin)
2. **Verify:** The "Recent Packages" section is **not visible** in the sidebar

### TC-12.6: Recent packs not shown outside TI
1. Navigate to the Dashboard (`/dashboard`) or any non-TI page
2. **Verify:** The "Recent Packages" section is **not visible** in the sidebar

---

## 13. Footer Bar (TI-GAP-014)

### TC-13.1: Footer bar display
1. Navigate to any page in the platform (dashboard, TI results, admin, etc.)
2. **Verify:**
   - A footer bar is visible at the bottom of the content area (not inside the sidebar)
   - Footer has three sections:
     - **Left:** "TITLE INTELLIGENCE PLATFORM" (uppercase, bold)
     - **Center:** "{Org Name} | Powered by Logikality"
     - **Right:** User email + "Sign Out" link

### TC-13.2: Footer org name
1. Check the center section of the footer
2. **Verify:** It shows the current organization's name (matches the org switcher)

### TC-13.3: Footer sign out
1. Click the **"Sign Out"** link in the footer
2. **Verify:** User is signed out and redirected to the login page

### TC-13.4: Footer persistence
1. Navigate between multiple pages (dashboard, TI upload, TI results, admin)
2. **Verify:** Footer remains visible on all pages

---

## 14. Export Button Styling (TI-GAP-012 related)

### TC-14.1: Export button on results page
1. Navigate to a completed pack's results page
2. **Verify:**
   - Export button reads **"Export Full Report"**
   - Button uses the CTA style (amber/brand gradient)
   - Download icon is present

---

## 15. End-to-End Flow

### TC-15.1: Full upload-to-review flow
1. Go to **Title Intelligence > Upload**
2. Enter pack name: "E2E Test — {today's date}"
3. Upload a multi-page title commitment PDF
4. Click **"Analyze Package"**
5. **Verify:** Redirected to pack detail, processing starts
6. Wait for processing to complete (poll every 3 seconds)
7. Navigate to the **Results** tab
8. **Verify in order:**
   - Property address header (or pack name fallback)
   - Order metadata line (if extractable)
   - "Analyzed on" timestamp
   - 4 summary count cards with correct counts
   - "Ask a question" input field
   - "Exceptions & Required Actions" section header
   - Flags table with: EX-IDs, severity badges, descriptions, doc refs, required actions, status badges, action buttons
   - Table header row on desktop
   - Expand a flag — full detail, AI explanation, evidence list
   - Use quick actions (approve/reject/escalate)
   - "Re-analyze" button present
   - "Export Full Report" button present
9. Check sidebar:
   - New pack appears in "Recent Packages"
   - Active pack is highlighted
10. Check footer bar is visible with correct org name

### TC-15.2: Multiple pack switching via sidebar
1. Upload two separate packs (or use existing ones)
2. Navigate to the first pack's results
3. Click the second pack in the sidebar "Recent Packages"
4. **Verify:** Results page updates to show the second pack's data
5. **Verify:** Sidebar highlights the second pack

---

## 16. Responsive Design Checks

### TC-16.1: Desktop (1440px+)
1. View results page at 1440px width
2. **Verify:** All columns visible — ID, Severity, Description, Doc Ref, Required Action, Status, Actions

### TC-16.2: Laptop (1024px)
1. Resize to 1024px width
2. **Verify:** Required Action column visible, table header visible, cards in a row

### TC-16.3: Tablet (768px)
1. Resize to 768px width
2. **Verify:** Required Action and table header hidden; cards may stack; sidebar may collapse

### TC-16.4: Mobile (375px)
1. Resize to 375px width
2. **Verify:** Summary cards stack vertically; flag rows show essential info only; inline question input is full-width

---

## Notes

- All test scenarios assume a clean dev environment with seeded data
- For scenarios requiring specific flag states, use the quick action buttons to set flags to desired statuses
- If extractions are missing (no property address, no order number), verify the fallback behavior gracefully handles `null`/missing data
- The backend must have processed at least one pack with the AI pipeline for extraction-dependent tests to be meaningful
