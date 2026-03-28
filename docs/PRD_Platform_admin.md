# PRD: Platform Admin (Logikality Admin)

## Overview

The Platform Admin is the centralized management interface for the Logikality SaaS platform. It enables a designated super-admin (the "Logikality Admin") to onboard customer organizations, manage user accounts, control micro app availability, and manage subscriptions — all from a single admin dashboard.

There is **no public self-signup**. All customer accounts are provisioned by the Platform Admin.

---

## Personas

| Persona | Description |
|---------|-------------|
| **Logikality Admin** | Internal super-admin (`is_platform_admin=true`). Creates customer accounts, manages apps and subscriptions. Seeded at deploy time. |
| **Customer Owner** | The first user created for a customer org. Has `owner` role within their org. Cannot access admin routes. |
| **Customer Member** | Additional users within a customer org. Has `member` or `admin` role. Cannot access admin routes. |

---

## Authentication & Authorization

### Login
- **Single login page** for all users (admin and customers).
- `POST /api/v1/auth/login` — accepts email + password, returns a JWT (HS256, 24-hour expiry).
- Rate-limited to 5 requests/minute per IP.
- No "forgot password" self-service — the Platform Admin resets passwords manually.

### Admin Authorization
- Admin routes live under `/api/v1/admin/*`.
- All admin endpoints require the `require_platform_admin` dependency, which:
  1. Decodes the JWT to get `auth_user_id`.
  2. Looks up the User record where `is_active=true` AND `is_platform_admin=true`.
  3. Returns 403 if no match.
- **No org context required**: Admin routes skip the `TenantContextMiddleware` entirely (the admin operates across all orgs, not within one).
- The `X-Org-Id` header is not needed for admin API calls.

### Seeded Admin Account
- Created by `scripts/seed.py`:
  - Email: `admin@logikality.com`
  - Password: `admin123` (must be changed after first login)
  - Organization: "Logikality" (slug: `logikality`)
  - Role: `owner` within the Logikality org
  - `is_platform_admin: true`
- The Logikality org itself has **no micro app subscriptions** — the admin manages other orgs' subscriptions.
- The seed script is idempotent (safe to re-run).

---

## Feature Requirements

### FR-1: Customer Account Onboarding

**Goal**: Create a new customer organization with an owner user and optional micro app subscriptions in a single operation.

**API**: `POST /api/v1/admin/accounts`

**Request body**:
| Field | Type | Validation | Description |
|-------|------|------------|-------------|
| `email` | EmailStr | Valid email, must be unique across all users | Owner user's email |
| `password` | string | min 6 characters | Owner user's initial password |
| `full_name` | string | 1-255 characters | Owner user's display name |
| `org_name` | string | 1-255 characters | Organization display name |
| `org_slug` | string | 1-100 characters, pattern `^[a-z0-9][a-z0-9-]*[a-z0-9]$`, must be unique | URL-safe org identifier |
| `app_slugs` | string[] | Optional, defaults to `[]` | Micro app slugs to subscribe to at creation time |

**Business rules**:
- Email must be globally unique (checked across all orgs).
- Org slug must be unique.
- The owner user is created with `role=owner`, `is_platform_admin=false`.
- `auth_user_id = id` (self-referential, since auth is local).
- Password is hashed with bcrypt via `passlib`.
- Subscriptions are created with `status=active`, `purchased_at=now`, `enabled_at=now`.
- Only active micro apps can be subscribed to (inactive apps in `app_slugs` are silently skipped).

**Response**: `201 Created` with `AccountResponse` (org_id, org_name, org_slug, user_id, email, full_name, subscriptions).

**Frontend**: "New Customer" button on the Accounts page opens an inline form with fields for Company Name, Admin Full Name, Admin Email, Password, and a multi-select for available micro apps.

---

### FR-2: Customer Account Listing

**Goal**: View all customer organizations with summary metrics.

**API**: `GET /api/v1/admin/accounts`

**Response**: Array of `OrgListItem`:
| Field | Description |
|-------|-------------|
| `id` | Organization UUID |
| `name` | Organization display name |
| `slug` | URL-safe identifier |
| `is_active` | Whether the org is active |
| `user_count` | Number of active users in the org |
| `created_at` | Org creation timestamp |

**Business rules**:
- The Platform Admin's own organization (Logikality) is excluded from the list.
- Sorted by `created_at` descending (newest first).

**Frontend**: Card list with org name, slug, user count, active/inactive badge, and a link to the account detail page. Each row has a delete button with confirmation.

---

### FR-3: Customer Account Detail

**Goal**: View and manage a single customer account — its users, subscriptions, and available apps.

**API**: `GET /api/v1/admin/accounts/{org_id}`

**Response**: `AccountDetail`:
| Field | Description |
|-------|-------------|
| `id` | Organization UUID |
| `name` | Organization display name |
| `slug` | URL-safe identifier |
| `is_active` | Whether the org is active |
| `created_at` | Org creation timestamp |
| `users` | Array of `{id, email, full_name, role, is_active}` |
| `subscriptions` | Array of `{id, app_id, app_name, app_slug, status}` |

**Frontend**: Three-section page:
1. **Enabled Micro Apps** — lists current subscriptions with a "Remove" button each.
2. **Available Micro Apps** — lists unsubscribed active apps with an "Enable" button each.
3. **Users** — lists all users with role badge, active/inactive badge, "Reset Password" button, and "Delete" button (with confirmation).

---

### FR-4: Customer Account Deletion

**Goal**: Permanently delete a customer organization and all associated data.

**API**: `DELETE /api/v1/admin/accounts/{org_id}`

**Response**: `204 No Content`

**Business rules**:
- Deletes in FK-safe order to avoid constraint violations:
  1. Title Intelligence data: TextChunk, ChatMessage, Review, Flag, Extraction, Section, Page, PipelineRun, PackFile, Pack
  2. Title Search data: TAReview, TAFlag, TAPackage, TAChainLink, TADocument, TARawDocument, TASourceAssignment, TAPipelineRun, TAOrder
  3. AuditEvent records
  4. Subscriptions
  5. Users
  6. Organization
- If a micro app's models are not installed (ImportError), that step is silently skipped.
- Returns 404 if the org does not exist.

**Frontend**: Delete button on the accounts list page with a two-step confirmation (click delete icon, then "Confirm" / "Cancel" buttons appear inline).

---

### FR-5: User Deletion

**Goal**: Remove a specific user from a customer organization.

**API**: `DELETE /api/v1/admin/accounts/{org_id}/users/{user_id}`

**Response**: `204 No Content`

**Business rules**:
- The user must belong to the specified org (validated via `org_id` + `user_id` query).
- Returns 404 if user not found in that org.
- Does not prevent deleting the last owner (no guardrail — admin is trusted).

**Frontend**: "Delete" button on each user row in the account detail page, with inline confirmation.

---

### FR-6: User Password Reset

**Goal**: Reset a customer user's password (no self-service password reset exists).

**API**: `PATCH /api/v1/admin/accounts/{org_id}/users/{user_id}/password`

**Request body**:
| Field | Type | Validation |
|-------|------|------------|
| `new_password` | string | min 6 characters |

**Response**: `200 OK` with `{"detail": "Password reset successfully"}`

**Business rules**:
- The user must belong to the specified org.
- Password is hashed with bcrypt and stored directly.
- No email notification is sent — admin communicates the new password to the user out-of-band.

**Frontend**: "Reset Password" button on each user row expands an inline form with a password input and Confirm/Cancel buttons.

---

### FR-7: Subscription Management

**Goal**: Add or remove micro app subscriptions for a customer org.

#### Add Subscription
**API**: `POST /api/v1/admin/accounts/{org_id}/subscriptions`

**Request body**: `{ "app_id": "<uuid>" }`

**Response**: `201 Created` with `{"detail": "Subscription added"}`

**Business rules**:
- Cannot add a duplicate subscription (returns 409 Conflict).
- Subscription created with `status=active`, `purchased_at=now`, `enabled_at=now`.
- The `MicroAppAccessMiddleware` checks for an active subscription on every request to `/api/v1/apps/{slug}/*`. Adding a subscription immediately grants access.

#### Remove Subscription
**API**: `DELETE /api/v1/admin/accounts/{org_id}/subscriptions/{sub_id}`

**Response**: `200 OK` with `{"detail": "Subscription removed"}`

**Business rules**:
- The subscription must belong to the specified org (validated via `org_id` + `sub_id` query).
- The subscription record is hard-deleted (not soft-deleted).
- Removing a subscription immediately revokes access — the next API call to that micro app returns 403.

**Frontend**: On the account detail page:
- "Enabled Micro Apps" section shows current subscriptions with "Remove" button.
- "Available Micro Apps" section shows unsubscribed active apps with "Enable" button.

---

### FR-8: Micro App Management

**Goal**: Create, list, and manage micro app definitions (the "catalog" of available apps).

#### List Apps
**API**: `GET /api/v1/admin/apps`

**Response**: Array of `AppResponse`:
| Field | Description |
|-------|-------------|
| `id` | App UUID |
| `name` | Display name (e.g., "Title Intelligence") |
| `slug` | URL-safe identifier (e.g., "title-intelligence") |
| `description` | Optional description |
| `icon` | Optional Lucide icon name |
| `is_active` | Whether the app is available for subscription |
| `created_at` | Creation timestamp |

Sorted by `created_at` descending.

#### Create App
**API**: `POST /api/v1/admin/apps`

**Request body**:
| Field | Type | Validation |
|-------|------|------------|
| `name` | string | 1-255 characters, required |
| `slug` | string | 1-100 characters, pattern `^[a-z0-9][a-z0-9-]*[a-z0-9]$`, must be unique |
| `description` | string | Optional |
| `icon` | string | Optional (Lucide icon name) |

**Business rules**:
- Slug must be unique (returns 409 Conflict if taken).
- New apps are created with `is_active=true` by default.
- The slug must match a registered micro app plugin (under `backend/app/micro_apps/`) for the app to actually function, but the admin can create the DB record independently.

#### Update App
**API**: `PATCH /api/v1/admin/apps/{app_id}`

**Request body** (all optional):
| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Update display name |
| `description` | string | Update description |
| `icon` | string | Update icon |
| `is_active` | boolean | Enable/disable the app |

**Business rules**:
- Setting `is_active=false` disables the app globally. Existing subscriptions remain in the DB but `MicroAppAccessMiddleware` only checks for subscriptions to active apps.
- Only provided fields are updated (partial update via `exclude_unset`).

**Frontend**: Apps management page with:
- "New App" button opens an inline creation form.
- Card list of all apps with name, slug, description, active/disabled badge, and Enable/Disable toggle button.

---

## Data Model

### Organization
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key, auto-generated |
| `name` | String(255) | Display name |
| `slug` | String(100) | Unique, URL-safe |
| `is_active` | Boolean | Default true |
| `created_at` | DateTime | Auto-set |
| `updated_at` | DateTime | Auto-updated |

### User
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `auth_user_id` | UUID | = `id` for local auth |
| `org_id` | UUID | FK to organizations |
| `email` | String(255) | Unique within org |
| `full_name` | String(255) | Nullable |
| `password_hash` | String(255) | bcrypt hash, nullable |
| `role` | String(50) | `owner`, `admin`, or `member` |
| `is_active` | Boolean | Default true |
| `is_platform_admin` | Boolean | Default false |
| `password_reset_token` | String(255) | Nullable (reserved for future use) |
| `password_reset_expires` | DateTime | Nullable (reserved for future use) |

Unique constraint: `(auth_user_id, org_id)`.

### MicroApp
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `name` | String(255) | Display name |
| `slug` | String(100) | Unique |
| `description` | Text | Nullable |
| `icon` | String(100) | Nullable (Lucide icon name) |
| `is_active` | Boolean | Default true |
| `created_at` | DateTime | Auto-set |

### Subscription
| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `org_id` | UUID | FK to organizations |
| `app_id` | UUID | FK to micro_apps |
| `status` | String(50) | `active` (only value used currently) |
| `purchased_at` | DateTime | Set at creation |
| `enabled_at` | DateTime | Set at creation |
| `disabled_at` | DateTime | Nullable (reserved for future use) |

Unique constraint: `(org_id, app_id)`.

---

## Frontend Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/admin/accounts` | Customer Accounts | List all orgs, onboard new customers, delete orgs |
| `/admin/accounts/[orgId]` | Account Detail | View/manage users, subscriptions, password resets |
| `/admin/apps` | Micro Apps | Create apps, enable/disable apps |
| `/admin/users` | Users (placeholder) | Future: cross-org user search |
| `/admin/subscriptions` | Subscriptions (placeholder) | Future: cross-org subscription management |

### Navigation
The admin pages are accessible from the sidebar. The sidebar conditionally renders the "Admin" section only for users with `is_platform_admin=true`.

### Auth Flow
Admin pages use a dedicated `adminFetch()` helper that:
1. Reads the JWT from localStorage (`getToken()`).
2. Sets `Authorization: Bearer <token>` header.
3. Does **not** set `X-Org-Id` (admin routes don't need it).
4. Handles 204 No Content responses (for DELETE operations).

---

## Security Requirements

1. **All admin endpoints require `is_platform_admin=true`** — enforced at the dependency level, not middleware.
2. **No public signup** — only the Platform Admin can create user accounts.
3. **Passwords are hashed with bcrypt** — never stored in plaintext.
4. **JWTs expire in 24 hours** — no refresh token mechanism.
5. **Rate limiting on login** — 5 requests/minute to prevent brute force.
6. **Cascade delete is explicit** — account deletion follows a specific FK-safe order to ensure no orphaned records.
7. **Admin's own org is excluded from listing** — prevents accidental self-deletion.

---

## Seeded Data

The `scripts/seed.py` script provisions the initial platform state:

| Entity | Value | Purpose |
|--------|-------|---------|
| Organization | Logikality (`logikality`) | Admin's home org |
| User | admin@logikality.com / admin123 | Platform super admin |
| MicroApp | Title Intelligence (`title-intelligence`) | First product module |
| MicroApp | Title Search & Abstracting (`title-search`) | Second product module |
| CountySources | Cook IL, Los Angeles CA, Harris TX, Maricopa AZ | Test data for TSA pipeline |

---

## Not In Scope (Current)

- **Self-service signup**: No public registration. All accounts are admin-provisioned.
- **Billing/payments**: Subscriptions are manually managed. No Stripe/payment integration.
- **Self-service password reset**: No "forgot password" flow. Admin resets passwords manually.
- **Audit logging of admin actions**: AuditEvent model exists but admin CRUD actions are not logged.
- **Org deactivation (soft delete)**: Currently only hard delete. No "deactivate org" toggle.
- **User invitation flow**: No email invitations. Admin creates users directly with a password.
- **Multi-admin support**: Only one platform admin is supported (the seeded account). Additional admins would need manual DB `is_platform_admin=true` flag setting.
- **Role management within customer orgs**: Admin can see user roles but cannot change them. Role changes happen within the customer's own org context.
