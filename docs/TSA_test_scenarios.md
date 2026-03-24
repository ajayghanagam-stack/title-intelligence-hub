# Title Search & Abstracting — E2E Browser Test Scenarios

End-to-end test scenarios for manually verifying the Title Search & Abstracting micro app entirely from the browser.

## Prerequisites

- Backend running on `localhost:8000`, frontend on `localhost:3000`
- Database seeded (`python scripts/seed.py`) — creates `admin@logikality.com` / `admin123`
- County sources pre-configured in the database for at least one digital county (seeded or inserted by admin before testing)

> **Note:** County source administration, document correction, ground abstractor upload, and order deletion do not have UI pages — they are API-only. These scenarios cover only what is testable through the browser.

---

## Scenario 1: Platform Admin Login & Customer Onboarding

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `localhost:3000` | Redirected to `/login` |
| 2 | Login as `admin@logikality.com` / `admin123` | Redirected to `/dashboard`, sidebar shows admin nav |
| 3 | Go to **Admin > Accounts** | "Customer Accounts" page loads |
| 4 | Click **New Customer** | Form expands with company name, admin name, email, password fields |
| 5 | Fill form: `Acme Title Co`, `Jane Smith`, `jane@acme.com`, `password123` | Fields populated |
| 6 | Toggle **Title Search & Abstracting** app chip | Chip turns primary color with checkmark |
| 7 | Click **Create Account** | Success message, account appears in list as "Active" |
| 8 | Logout (top-right) | Redirected to `/login` |

---

## Scenario 2: Customer Login & First Visit

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as `jane@acme.com` / `password123` | Redirected to `/dashboard` |
| 2 | Verify dashboard | Title Search & Abstracting card shows as subscribed app with "Open" button |
| 3 | Click **Open** on TSA card | Navigates to `/apps/title-search`, order list page loads |
| 4 | Verify empty state | "No orders yet" message displayed |

---

## Scenario 3: Create a Search Order

| Step | Action | Expected |
|------|--------|----------|
| 1 | On order list page, click **New Order** | Navigates to `/apps/title-search/orders/new` |
| 2 | Verify form fields | Property address, county, state dropdown, parcel number, search scope dropdown, search years input |
| 3 | Enter property address: `123 Main St, Springfield, IL 62701` | Field populated |
| 4 | Enter county: `Cook` | Field populated |
| 5 | Select state: `Illinois` from dropdown | State selected |
| 6 | Enter parcel number: `12-34-567-890` | Optional field populated |
| 7 | Verify search scope defaults to `Full Search` | Default selected in dropdown |
| 8 | Verify search years defaults to `60` | Default value shown |
| 9 | Click **Create & Process Order** | Button shows "Creating order...", then redirects to order detail page |
| 10 | Verify order detail | Property address displayed, status badge shows "Processing" |

---

## Scenario 4: Create Order — Form Validation

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `/apps/title-search/orders/new` | Create form loads |
| 2 | Leave all fields empty, observe **Create & Process Order** button | Button is disabled |
| 3 | Fill county and select state, leave property address empty | Button remains disabled |
| 4 | Fill property address and county, leave state unselected | Button remains disabled |
| 5 | Fill all three required fields (address, county, state) | Button becomes enabled |
| 6 | Change search years to `0` | Validation error or rejected on submit |
| 7 | Change search years to `201` | Validation error or rejected on submit |
| 8 | Reset search years to `60`, click **Create & Process Order** | Order created successfully |

---

## Scenario 5: Create Order — Search Scope Options

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to create order form | Form loads with defaults |
| 2 | Open search scope dropdown | Three options: "Full Search", "Current Owner", "Limited" |
| 3 | Select "Current Owner" | Scope changed |
| 4 | Change search years to `10` | Years updated |
| 5 | Fill required fields and submit | Order created with scope "current_owner" and 10 years |
| 6 | On order overview, verify scope displayed | Shows "Current Owner" with years covered |

---

## Scenario 6: Pipeline Progress Monitoring

| Step | Action | Expected |
|------|--------|----------|
| 1 | After creating an order, land on order detail **Overview** tab | Pipeline progress section visible |
| 2 | Observe pipeline stages listed | Stages shown: order, retrieve, parse, chain, package, complete |
| 3 | Watch pipeline auto-update (polls every 3 seconds) | Stages transition one by one |
| 4 | Completed stages | Green checkmark (✓) icon, static |
| 5 | Currently running stage | Blue spinner (⟳), animated |
| 6 | Pending stages | Gray clock (⏱) icon |
| 7 | When all stages complete | Status badge changes to "Completed" or "Review Required" |
| 8 | Pipeline progress stops polling | No more spinner animation |

---

## Scenario 7: Order Detail — Property Information

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to a completed order's **Overview** tab | Property details card visible |
| 2 | Verify property address | Matches what was entered during creation |
| 3 | Verify county and state | Correct county / state code displayed |
| 4 | Verify search scope | Shows "Full Search" (or whichever was selected) with years |
| 5 | Verify status | Correct status badge (color-coded) |

---

## Scenario 8: Order Detail — Tab Navigation

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to a completed order | Overview tab loads by default |
| 2 | Verify breadcrumb | "Title Search" (clickable) > "Order Details" |
| 3 | Verify 5 tabs visible | Overview, Documents, Chain of Title, Flags, Package |
| 4 | Click **Documents** tab | Documents page loads, tab underline moves to Documents |
| 5 | Click **Chain of Title** tab | Chain page loads, tab underline moves |
| 6 | Click **Flags** tab | Flags page loads, tab underline moves |
| 7 | Click **Package** tab | Package page loads, tab underline moves |
| 8 | Click **Overview** tab | Returns to overview with pipeline progress |
| 9 | Click "Title Search" in breadcrumb | Navigates back to order list |

---

## Scenario 9: Documents — View & Filter

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to a completed order, click **Documents** tab | Documents list loads with count in header (e.g., "Documents (12)") |
| 2 | Verify document card layout | Each card shows: document type icon, type label, recording ref & date |
| 3 | Find a deed document | Shows grantor name(s), grantee name(s), consideration amount (formatted as currency) |
| 4 | Find a mortgage document | Shows parties and dollar amount |
| 5 | Open type filter dropdown | Options: All Types, Deed, Mortgage, Lien, Judgment, Easement, Satisfaction, Release, Assignment, Other |
| 6 | Select "Deed" | Only deed documents displayed, count updates |
| 7 | Select "Mortgage" | Only mortgage documents displayed |
| 8 | Select "All Types" | All documents shown again, count restored |
| 9 | Look for documents with yellow "Review" badge (⚠) | Low-confidence parses have AlertTriangle icon + "Review" badge |
| 10 | Check confidence score | Percentage displayed (e.g., "87% conf") |

---

## Scenario 10: Documents — Empty State

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to **Documents** tab for an order still in early pipeline stages | Empty state displayed |
| 2 | Verify message | "No documents found" shown |
| 3 | Apply a type filter that matches nothing | "No documents found" shown |

---

## Scenario 11: Chain of Title — Complete Chain

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to a completed order with no gaps, click **Chain of Title** tab | Chain view loads |
| 2 | Verify chain status header | Green "✓ Complete" badge with CheckCircle2 icon |
| 3 | Verify link count | "X links" displayed next to status |
| 4 | Chain link cards display vertically | Connected by visual lines/icons between them |
| 5 | Verify first link (position 1) | Shows position number in circle, from party → to party, effective date, link type |
| 6 | Verify links are chronological | Position 1 = earliest transfer, increasing to present |
| 7 | Conveyance links | Show `link_type: conveyance` |
| 8 | Encumbrance links (mortgages/liens) | Show `link_type: encumbrance` |
| 9 | Release links (satisfactions) | Show `link_type: release` |

---

## Scenario 12: Chain of Title — Chain with Gaps

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to an order with chain gaps, click **Chain of Title** tab | Chain view loads |
| 2 | Verify chain status header | Yellow "⚠ X gap(s)" badge with AlertTriangle icon |
| 3 | Find a gap link in the chain | Yellow border/background, visually distinct from normal links |
| 4 | Verify gap description | Red "GAP: {description}" text displayed on the gap card |
| 5 | Non-gap links surrounding the gap | Normal styling, show from/to parties |

---

## Scenario 13: Chain of Title — Empty State

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to **Chain of Title** tab for an order still processing | Empty state displayed |
| 2 | Verify message | "No chain links found" shown |

---

## Scenario 14: Flags — View & Review

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to a completed order with flags, click **Flags** tab | Flag list loads with count in header |
| 2 | Verify severity summary badges (top area) | Colored count pills: "X critical" (red), "X high" (orange), "X medium" (yellow), "X low" (blue) |
| 3 | Verify flag sort order | Critical flags first, then high, then medium, then low |
| 4 | Verify flag card contents | AlertTriangle icon, flag title, status badge, description text, flag type label |
| 5 | Verify severity color coding | Critical = red border, High = orange border, Medium = yellow border, Low = blue border |
| 6 | Verify open flags show action buttons | **Approve** (green) and **Reject** (red) buttons visible |
| 7 | Click **Approve** on an open flag | Flag status updates, buttons disappear for that flag, list refreshes |
| 8 | Click **Reject** on another open flag | Flag status changes to rejected, buttons disappear |
| 9 | Verify reviewed flags | No action buttons displayed, status badge updated |
| 10 | Check severity badge counts after reviews | Counts remain (flags persist with review attached) |

---

## Scenario 15: Flags — Empty State

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to **Flags** tab for an order with no flags | Empty state displayed |
| 2 | Verify icon | Large green CheckCircle2 icon |
| 3 | Verify message | "No flags detected" shown |
| 4 | No severity badges visible | Badge area empty or hidden |

---

## Scenario 16: Flags — Severity Verification

| Step | Action | Expected |
|------|--------|----------|
| 1 | Process an order that produces various flag types | Pipeline completes with flags |
| 2 | Navigate to **Flags** tab | Flags listed |
| 3 | Find a `chain_gap` flag | Severity is at least `high` (severity floor enforced) |
| 4 | Find an `unreleased_mortgage` flag | Severity is at least `high` |
| 5 | Find a `low_confidence` flag | Severity is at most `medium` (severity cap enforced) |
| 6 | Find a `missing_source` flag | Severity is at most `medium` |
| 7 | Verify no duplicate flag types for same document | Each `(flag_type, document)` pair appears only once |

---

## Scenario 17: Package — Auto-Issued (Clean Order)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Process an order where chain is complete and no unresolved critical/high flags | Pipeline completes all 6 stages |
| 2 | Navigate to **Package** tab | Package exists, header shows package number |
| 3 | Verify package number format | Format: `TA-YYYYMMDD-NNNN` (e.g., `TA-20260323-0001`) |
| 4 | Verify status shows "issued" | Status label visible |
| 5 | Verify `issued_by` shows "auto" | "(auto)" displayed in package header |
| 6 | Verify metadata grid | Search Scope, Years Covered, Total Documents, Chain Complete (✓ Yes), Open Flags (0), Issued At (timestamp) |
| 7 | Verify property summary section | Property details displayed as key-value grid |
| 8 | Click **Download PDF** | PDF file downloads to browser |
| 9 | Open downloaded PDF | Contains: property summary, search scope, document inventory, chain timeline |

---

## Scenario 18: Package — Manual Issue After Flag Review

| Step | Action | Expected |
|------|--------|----------|
| 1 | Process an order that produces critical/high flags | Order completes with "Review Required" status |
| 2 | Navigate to **Package** tab | Package shows status "draft" |
| 3 | Click **Issue Package** | Error message displayed — unresolved critical/high flags block issuance |
| 4 | Navigate to **Flags** tab | Open critical/high flags listed with Approve/Reject buttons |
| 5 | Click **Approve** or **Reject** on each critical flag | Flags reviewed, buttons disappear |
| 6 | Click **Approve** or **Reject** on each high flag | All critical/high flags resolved |
| 7 | Navigate to **Package** tab | "Issue Package" button still visible |
| 8 | Click **Issue Package** | Button shows "Issuing...", then package status transitions to "issued" |
| 9 | Verify `issued_by` shows "manual" | "(manual)" displayed, issuer name shown |
| 10 | Click **Download PDF** | PDF downloads successfully |
| 11 | Verify any remaining medium/low flags | Reflected in "Open Flags" count in metadata grid |

---

## Scenario 19: Package — Empty State

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to **Package** tab for an order still processing | Empty state shown |
| 2 | Verify icon and message | Package icon + "No package generated yet" displayed |
| 3 | No **Issue Package** button | Button not shown |
| 4 | No **Download PDF** button | Button not shown |

---

## Scenario 20: Order List — Status Filtering

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `/apps/title-search` with multiple orders in various statuses | Order list loads showing all orders |
| 2 | Click **All** filter tab | All orders displayed |
| 3 | Click **pending** filter tab | Only pending orders shown |
| 4 | Click **processing** filter tab | Only processing orders shown |
| 5 | Click **completed** filter tab | Only completed orders shown |
| 6 | Click **failed** filter tab | Only failed orders shown |
| 7 | Click **All** again | Full list restored |

---

## Scenario 21: Order List — Card Display & Navigation

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `/apps/title-search` with orders | Order cards displayed |
| 2 | Verify each card shows | Property address, county/state, creation date |
| 3 | Verify status badges are color-coded | pending=gray, processing=blue, awaiting_abstractor=yellow, review_required=orange, completed=green, failed=red |
| 4 | Click an order card | Navigates to `/apps/title-search/orders/{orderId}` |
| 5 | Click breadcrumb "Title Search" | Returns to order list |

---

## Scenario 22: Pipeline Failure Display

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to an order where pipeline failed | Overview tab loads |
| 2 | Verify pipeline progress display | Failed stage shows red alert icon (⚠) |
| 3 | Verify error message | Human-readable pipeline error text displayed |
| 4 | Verify order status badge | Red "Failed" badge shown |
| 5 | Non-failed stages before the failure | Show green checkmarks (completed) |
| 6 | Stages after the failure | Show gray clock icons (never started) |

---

## Scenario 23: Multiple Orders Workflow

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to order list, click **New Order** | Create form loads |
| 2 | Create first order: `100 Oak Ave, Dallas, TX` | Order created, redirected to detail |
| 3 | Navigate back to order list (breadcrumb or browser back) | First order visible in list |
| 4 | Click **New Order** again | Create form loads (fields are empty/default) |
| 5 | Create second order: `200 Elm St, Chicago, IL` | Second order created |
| 6 | Navigate to order list | Both orders visible, sorted by creation date (newest first) |
| 7 | Click first order | Detail loads for first order |
| 8 | Click second order | Detail loads for second order |

---

## Scenario 24: Multi-Tenant Isolation

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as platform admin | Dashboard loads |
| 2 | Go to **Admin > Accounts**, create Org 1: `Alpha Title`, `alice@alpha.com`, `password123` with TSA subscription | Account created |
| 3 | Create Org 2: `Beta Title`, `bob@beta.com`, `password123` with TSA subscription | Account created |
| 4 | Logout, login as `alice@alpha.com` | Dashboard loads |
| 5 | Open Title Search, create an order: `111 Alpha St, Cook, IL` | Order created in Org 1 |
| 6 | Wait for pipeline to complete | Order reaches "Completed" |
| 7 | Logout, login as `bob@beta.com` | Dashboard loads |
| 8 | Open Title Search | Order list is empty — Org 1's order not visible |
| 9 | Create an order: `222 Beta Ave, Cook, IL` | Order created in Org 2 |
| 10 | Logout, login as `alice@alpha.com` | Title Search shows only `111 Alpha St` order |
| 11 | Navigate directly to Org 2's order URL (copy/paste orderId) | Error or empty data — order not accessible |

---

## Scenario 25: Subscription Gating

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as platform admin | Dashboard loads |
| 2 | Create a customer account WITHOUT TSA subscription (only TI, or no apps) | Account created |
| 3 | Logout, login as the new customer user | Dashboard loads |
| 4 | Verify TSA is not in subscribed apps | TSA card shows as "Available" (not subscribed) or not visible |
| 5 | Navigate directly to `/apps/title-search` in browser URL bar | Error page or 403 — no active subscription |
| 6 | Logout, login as platform admin | Dashboard loads |
| 7 | Go to **Admin > Accounts**, find the customer, add TSA subscription | Subscription added |
| 8 | Logout, login as customer again | Dashboard now shows TSA as subscribed |
| 9 | Click **Open** on TSA card | Order list page loads successfully |

---

## Scenario 26: Dashboard — App Card Display

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as a customer with TSA subscription | Dashboard loads |
| 2 | Find TSA app card on dashboard | Card shows "Title Search & Abstracting" with description |
| 3 | Card shows **Open** button | Button is clickable |
| 4 | Click **Open** | Navigates to `/apps/title-search` |

---

## Scenario 27: Error Handling — Backend Down

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login and navigate to Title Search | Order list loads normally |
| 2 | Stop the backend server | Server goes offline |
| 3 | Click **New Order** and try to submit | Error message displayed (network/API error) |
| 4 | Navigate to an existing order | Error state shown on the page |
| 5 | Restart the backend server | Server comes back online |
| 6 | Refresh the page in the browser | Page recovers and loads data correctly |

---

## Scenario 28: Error Handling — Invalid Navigation

| Step | Action | Expected |
|------|--------|----------|
| 1 | Navigate to `/apps/title-search/orders/nonexistent-uuid` | Error state or "not found" handling |
| 2 | Navigate to a valid order's **Documents** tab before pipeline reaches parse stage | "No documents found" empty state (not an error) |
| 3 | Navigate to a valid order's **Chain** tab before pipeline reaches chain stage | "No chain links found" empty state |
| 4 | Navigate to a valid order's **Package** tab before package stage | "No package generated yet" empty state |

---

## Scenario 29: Full End-to-End Workflow

| Step | Action | Expected |
|------|--------|----------|
| 1 | Login as platform admin | Dashboard loads |
| 2 | Create a customer account with TSA subscription | Account created |
| 3 | Logout, login as customer | Dashboard loads |
| 4 | Open Title Search & Abstracting | Empty order list |
| 5 | Click **New Order** | Create form loads |
| 6 | Fill: address `500 Court St`, county `Cook`, state `IL`, scope `Full Search`, years `60` | Fields populated |
| 7 | Click **Create & Process Order** | Redirects to order detail, status "Processing" |
| 8 | Watch pipeline progress | Stages complete one by one with auto-refresh |
| 9 | Pipeline completes | Status changes to "Completed" or "Review Required" |
| 10 | Click **Documents** tab | Parsed documents listed with types, parties, dates, confidence |
| 11 | Filter documents by "Deed" | Only deeds shown |
| 12 | Reset filter to "All Types" | All documents shown |
| 13 | Click **Chain of Title** tab | Chain links displayed chronologically, status shows complete or gaps |
| 14 | Click **Flags** tab | Flags listed by severity (or "No flags detected" empty state) |
| 15 | If flags exist: approve one flag | Flag reviewed, button disappears |
| 16 | If flags exist: reject another flag | Flag rejected |
| 17 | Click **Package** tab | Package displayed with metadata |
| 18 | If package is "draft": resolve all critical/high flags (go to Flags tab), then return and click **Issue Package** | Package status becomes "issued" |
| 19 | Click **Download PDF** | PDF file downloads |
| 20 | Open PDF | Contains property summary, documents, chain, flags |
| 21 | Click breadcrumb "Title Search" | Back to order list, order shows "Completed" status |

---

## Quick Smoke Test (5-minute version)

If you need a fast sanity check:

1. Login as admin > create customer account with TSA subscription
2. Login as customer > open Title Search & Abstracting from dashboard
3. Click **New Order** > fill address/county/state > click **Create & Process Order**
4. Watch pipeline progress on Overview tab (auto-refreshes every 3s)
5. When complete: click **Documents** tab > verify documents with types and parties
6. Click **Chain of Title** tab > verify links displayed with from/to parties
7. Click **Flags** tab > approve one flag (if any exist)
8. Click **Package** tab > verify package, click **Download PDF**
