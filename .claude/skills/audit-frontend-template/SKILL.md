---
name: audit-frontend-template
description: Run a golden template compliance audit on the frontend codebase. Use when assessing frontend code quality, accessibility, security, type safety, or production readiness.
argument-hint: "[fix|report|wave N]"
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
effort: max
---

# Frontend Golden Template Compliance Audit

You are auditing the Title Intelligence Hub frontend (`frontend/`) against the golden template standard for production-ready Next.js + TypeScript SaaS applications.

## Mode Selection

Based on `$ARGUMENTS`:

- **No args / `report`**: Run the full audit and produce the compliance report (no changes).
- **`fix`**: Run the audit, then fix all issues automatically, one wave at a time. Run `npm run build` after each wave to verify. Present summary at the end.
- **`wave N`** (e.g., `wave 1`): Audit and report only the specified wave.
- **`fix wave N`**: Fix only issues in the specified wave.

---

## Wave Task Checklist

Score each item: **Done** (1.0), **Partial** (0.5), or **Missing** (0.0).

### Wave 1 — Security & Auth (Critical, weight 2.0)

| ID | Task | What to check |
|----|------|---------------|
| F1.1 | Security headers | `next.config.js` sets `X-Frame-Options`, `X-Content-Type-Options`, `Strict-Transport-Security`, `Referrer-Policy`, `Content-Security-Policy` via `headers()` |
| F1.2 | Middleware route protection | `src/middleware.ts` checks for auth token on protected routes and redirects to `/login` if missing — prevents serving page shells to unauthenticated users |
| F1.3 | Token expiry handling | API layer detects 401 responses and clears token + redirects to login, not just on `/auth/me` but on any API call |
| F1.4 | No silent error swallowing | Zero empty `catch {}` blocks — all catch blocks either show user feedback (toast/alert), log the error, or re-throw |
| F1.5 | No console.error in production | Replace `console.error` with proper error reporting or remove from production paths |

### Wave 2 — Type Safety & Data Integrity (High, weight 1.5)

| ID | Task | What to check |
|----|------|---------------|
| F2.1 | Single source of truth for types | All TI domain types (`Pack`, `Flag`, `Extraction`, `ChatMessage`, `StageStatus`, etc.) defined once in `ti-types.ts` and imported everywhere — no duplicate interface definitions in hooks or components |
| F2.2 | Typed API responses | `apiFetch` uses a generic type parameter `apiFetch<T>(path): Promise<T>` so consumers get compile-time type safety on API responses |
| F2.3 | Zero `any` types | No `: any`, `as any`, or implicit `any` in the codebase |
| F2.4 | Consistent type imports | All components import types from `@/lib/ti-types` or a shared types file, not from other components or hooks |

### Wave 3 — Error Handling & Resilience (Critical, weight 2.0)

| ID | Task | What to check |
|----|------|---------------|
| F3.1 | Global error boundary | `src/app/error.tsx` exists with a user-friendly error UI and "Try again" button |
| F3.2 | Platform error boundary | `src/app/(platform)/error.tsx` exists — catches errors in authenticated pages without losing auth state |
| F3.3 | Pack-level error boundary | `src/app/(platform)/apps/title-intelligence/packs/[packId]/error.tsx` exists — catches pack-specific errors |
| F3.4 | Loading states | `src/app/(platform)/loading.tsx` and `src/app/(platform)/apps/title-intelligence/loading.tsx` exist with skeleton/spinner UI |
| F3.5 | Not-found page | `src/app/not-found.tsx` exists with a user-friendly 404 page |
| F3.6 | API error feedback | Failed API calls show user-visible error messages (inline error text, toast, or alert) — never silently fail |

### Wave 4 — Accessibility (High, weight 1.5)

| ID | Task | What to check |
|----|------|---------------|
| F4.1 | Dialog semantics | Modal/dialog components (`flag-detail-dialog`, `chat-slide-panel`) use `role="dialog"`, `aria-modal="true"`, `aria-label`, focus trap, and focus restoration |
| F4.2 | Icon button labels | All icon-only buttons have `aria-label` describing the action (close, next page, approve, etc.) |
| F4.3 | Form labels | All form inputs have associated `<label>` elements or `aria-label`. `<select>` elements have labels. |
| F4.4 | Navigation landmarks | Breadcrumbs have `<nav aria-label="breadcrumb">`. Sidebar has `<nav aria-label="main navigation">`. |
| F4.5 | Live regions | Pipeline status updates, chat messages, and error notifications use `aria-live="polite"` or `aria-live="assertive"` |
| F4.6 | Keyboard navigation | Dropzone is keyboard-accessible. Interactive elements in tables have proper tabIndex. Escape closes modals. |

### Wave 5 — Code Quality & Maintainability (Medium, weight 1.0)

| ID | Task | What to check |
|----|------|---------------|
| F5.1 | ESLint config | `.eslintrc.json` or `eslint.config.*` exists with `eslint-plugin-jsx-a11y` for accessibility rules and `@typescript-eslint` for type-aware rules |
| F5.2 | No dead config | Unused config like `darkMode: ["class"]` is removed unless dark mode is actually implemented |
| F5.3 | API base URL from env | `NEXT_PUBLIC_API_URL` used in `api.ts` instead of hardcoded `http://localhost:8000` |
| F5.4 | Consistent loading pattern | Data-fetching hooks follow a uniform pattern with `{ data, loading, error }` return shape |
| F5.5 | Server components where possible | Layout components and static pages are server components (no `"use client"` where it's not needed) |

---

## Audit Procedure

1. **Read `package.json`** and `tsconfig.json` for project config context.
2. **For each wave**, grep/read the relevant files and score each task.
3. **Run `cd frontend && npm run build`** to get the current build status.
4. **Compile the report** in the format below.

### File Targets per Wave

- **F1**: `next.config.js`, `src/middleware.ts`, `src/lib/auth.ts`, `src/lib/api.ts`, grep for `catch {}` and `console.error`
- **F2**: `src/lib/ti-types.ts`, `src/hooks/*.ts`, `src/components/title-intelligence/*.tsx`, grep for `: any` and duplicate interface names
- **F3**: `src/app/error.tsx`, `src/app/(platform)/error.tsx`, `src/app/**/loading.tsx`, `src/app/not-found.tsx`, grep for `catch` blocks in page components
- **F4**: `src/components/title-intelligence/flag-detail-dialog.tsx`, `src/components/title-intelligence/chat-slide-panel.tsx`, all components with `<button>` containing only icons, `src/components/sidebar.tsx`, breadcrumb components
- **F5**: `.eslintrc*`, `tailwind.config.ts`, `src/lib/api.ts`, all `"use client"` declarations

---

## Output Format

```markdown
# Frontend Golden Template Compliance Audit

**Date**: {date}
**Build status**: {pass/fail}

## Score Summary

| Wave | Weight | Score | Weighted |
|------|--------|-------|----------|
| F1 Security & Auth | 2.0 | X/5 | ... |
| F2 Type Safety | 1.5 | X/4 | ... |
| F3 Error Handling | 2.0 | X/6 | ... |
| F4 Accessibility | 1.5 | X/6 | ... |
| F5 Code Quality | 1.0 | X/5 | ... |
| **Total** | | | **X/10.0** |

## Detailed Findings

### Wave 1 — Security & Auth
| ID | Task | Status | Notes |
|----|------|--------|-------|
| F1.1 | Security headers | Done/Partial/Missing | ... |
...

(repeat for each wave)

## Priority Remediation

1. {highest impact item}
2. ...
```

---

## Fix Mode Rules

When running in **fix** mode:

1. Work through waves in order (F1 → F5).
2. For each Missing/Partial item, implement the fix.
3. Run `cd frontend && npm run build` after each wave to verify no type errors.
4. Create new files (error.tsx, loading.tsx, not-found.tsx) as needed.
5. When consolidating types, update ALL import sites — don't leave broken imports.
6. For accessibility fixes, add `aria-*` attributes without changing visual behavior.
7. Present a summary table of all changes when done.
8. Do NOT commit — let the user decide when to commit.
