# Contributing to Title Intelligence Hub

## Getting Started

### 1. Clone the repo

```bash
git clone git@github.com:techlogikality/title-intelligence-hub.git
cd title-intelligence-hub
```

### 2. Set up local environment

**Prerequisites**: Python 3.12, Node 20, PostgreSQL 16, Tesseract OCR (`brew install tesseract` on macOS)

```bash
# Backend
cd backend
cp .env.example .env          # ask the team lead for actual values
pip install -r requirements.txt
alembic upgrade head
PYTHONPATH=. python scripts/seed.py

# Frontend
cd ../frontend
npm install
```

### 3. Run locally

```bash
# Option A: Full stack
./start-dev.sh

# Option B: Individual services
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
cd frontend && npm run dev
```

### 4. Default login credentials (local dev)

| Role | Email | Password |
|------|-------|----------|
| Platform Admin | admin@logikality.com | admin123 |
| Customer Demo | admin@societytitle.com | password123 |
| Customer Demo | admin@alliancetitle.com | password123 |

---

## Development Workflow

### Never push directly to `main`. Always use feature branches + pull requests.

### Branch naming

| Type | Pattern | Example |
|------|---------|---------|
| Bug fix | `fix/short-description` | `fix/login-redirect-loop` |
| Feature | `feat/short-description` | `feat/bulk-upload` |
| Refactor | `refactor/short-description` | `refactor/auth-middleware` |
| Chore | `chore/short-description` | `chore/update-deps` |

### Steps

```bash
# 1. Start from latest main
git checkout main
git pull origin main

# 2. Create a feature branch
git checkout -b fix/description-of-bug

# 3. Make changes and test locally
cd backend && pytest                          # all backend tests
cd backend && pytest tests/test_health.py -v  # single test file
cd frontend && npm run build                  # type-check + compile
cd frontend && npm run lint                   # ESLint

# 4. Commit with a clear message
git add <specific files>
git commit -m "Fix: description of what was fixed and why"

# 5. Push your branch
git push origin fix/description-of-bug

# 6. Open a Pull Request on GitHub
#    - Add a description of what changed and why
#    - Request a review from at least one teammate
#    - Wait for CI to pass and approval before merging
```

### Keeping your branch up to date

```bash
git checkout main
git pull origin main
git checkout my-branch
git rebase main
# Resolve conflicts if any, then:
git push origin my-branch --force-with-lease
```

---

## Commit Messages

Write clear, concise commit messages. Focus on **why**, not just what.

```
Fix: prevent duplicate subscriptions on account creation

The admin account endpoint was not checking for existing subscriptions
before creating new ones, causing integrity errors on re-runs.
```

**Prefixes**: `Fix:`, `Feat:`, `Refactor:`, `Chore:`, `Docs:`, `Test:`

---

## Code Standards

### Backend (Python)

- **Type hints** on all function signatures
- **Pydantic schemas** for all API request/response validation
- **Tenant scoping**: Every query must filter by `org_id` (unless platform-admin scope, with a comment explaining why)
- **Tests required**: Every new feature or bug fix needs test coverage
- Run `pytest` before pushing — all tests must pass

### Frontend (TypeScript)

- **Strict TypeScript**: No `any` types without justification
- **Next.js App Router** conventions (server components by default, `"use client"` only when needed)
- Run `npm run build` before pushing — must compile cleanly
- Run `npm run lint` — no ESLint errors

### Security

- Never hardcode secrets, API keys, or credentials
- Never commit `.env` files (they are gitignored)
- Validate all user input with Pydantic schemas
- All API routes require JWT authentication (except `/api/v1/health`)

---

## Testing

```bash
# Backend — all tests
cd backend && pytest

# Backend — specific test file
cd backend && pytest tests/test_billing.py -v

# Backend — specific test
cd backend && pytest tests/test_organizations.py::test_create_organization -v

# Backend — TI micro app tests
cd backend && pytest tests/title_intelligence/ -v

# Frontend — type check + build
cd frontend && npm run build

# Frontend — lint
cd frontend && npm run lint
```

---

## Pull Request Checklist

Before requesting a review, verify:

- [ ] Tests pass locally (`pytest` and `npm run build`)
- [ ] New code has test coverage
- [ ] No secrets or credentials in the diff
- [ ] Commit messages are clear and descriptive
- [ ] Branch is rebased on latest `main`
- [ ] PR description explains what changed and why

---

## Project Structure

```
backend/
  app/
    api/v1/           # REST API routes
    core/             # Auth, middleware, dependencies
    models/           # SQLAlchemy ORM models
    services/         # Business logic
    ai/               # AI base service + providers
    micro_apps/       # Self-contained feature modules
      title_intelligence/   # TI micro app
      title_search/         # TSA micro app
    pipeline/         # Background processing (Temporal)
  tests/              # pytest test suite
  scripts/            # seed.py, utilities

frontend/
  src/
    app/              # Next.js App Router pages
    components/       # Reusable UI components
    hooks/            # Custom React hooks
    lib/              # API client, auth, config, types
```

See `CLAUDE.md` for detailed architecture documentation.
