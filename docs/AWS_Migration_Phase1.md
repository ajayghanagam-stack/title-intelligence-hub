# AWS Migration — Phase 1: Lift and Shift

Working document for Phase 1 of the AWS migration. Source of truth: `docs/AWS_Migration.md`.

---

## 1. Current State Assessment

### 1.1 Deployment Model

| Component | Current Setup |
|-----------|--------------|
| **Host** | Single Hetzner VPS at `37.27.210.85` |
| **Orchestration** | Docker Compose (`docker-compose.prod.yml`) |
| **Reverse Proxy** | Caddy on port 80/443, routes `/api/*` to backend:8000, everything else to frontend:3000 |
| **Backend** | Python 3.12 + FastAPI, 2 uvicorn workers, image from GHCR |
| **Frontend** | Next.js 14 standalone build, image from GHCR |
| **Database** | PostgreSQL 16 (Docker container, `pgdata` volume) |
| **Storage** | Local filesystem (`storage_data` Docker volume at `/app/storage`) |
| **Temporal** | Optional profile in compose, not active in default deployment |
| **Deploy user** | `deploy@37.27.210.85`, app at `/opt/title-intelligence-hub` |

### 1.2 Runtime Dependencies

| Dependency | Where | Notes |
|------------|-------|-------|
| **Python 3.12** | Backend container | `python:3.12-slim` base |
| **Tesseract OCR** | Backend container | Installed via `apt-get`, eng.traineddata downloaded at build time |
| **Node 20** | Frontend container | `node:20-alpine` base, standalone output mode |
| **PostgreSQL 16** | DB container | `postgres:16-alpine` |
| **Caddy 2** | Proxy container | `caddy:2-alpine` |
| **litellm** | Python dependency | Multi-provider AI (Anthropic/Bedrock/OpenAI/Azure) |
| **aiobotocore** | Python dependency | S3 storage provider (already implemented, not active) |
| **fpdf2** | Python dependency | PDF report generation |

### 1.3 Environment Variables

**Required** (enforced with `?` in compose):
- `POSTGRES_PASSWORD` — database password
- `JWT_SECRET` — HS256 signing key
- `ANTHROPIC_API_KEY` — AI provider key

**Configurable** (with defaults):
- `DATABASE_URL` — constructed from `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` + `db` hostname
- `AI_PLATFORM` — default `anthropic`
- `STORAGE_PROVIDER` — default `local`
- `STORAGE_PATH` — default `/app/storage`
- `PIPELINE_BACKEND` — default `background_tasks`
- `CORS_ORIGINS` — default `["http://${SERVER_IP:-localhost}"]`
- `DOMAIN` — Caddy domain, default `localhost`
- `IMAGE_TAG` — Docker image tag, default `latest`
- `GITHUB_REPOSITORY` — for GHCR image paths
- `DEBUG` — default `false`

**S3 variables** (exist in config but not currently set):
- `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`

### 1.4 Storage Strategy

The app already has a `StorageProvider` abstraction (`backend/app/services/storage.py`) with two implementations:
- `LocalStorage` — filesystem at `STORAGE_PATH` (currently active)
- `S3Storage` — via `aiobotocore` with full CRUD + `delete_dir` + presigned URLs

Switching is a single env var change: `STORAGE_PROVIDER=s3`. No code changes needed.

Path convention: `{org_id}/{pack_id}/files/`, `pages/`, `thumbs/`, `ocr/`, `reports/`, `ai_cache/`.

### 1.5 OCR Dependencies

- Tesseract is installed in the Docker image at build time (`apt-get install tesseract-ocr`)
- English trained data is downloaded from GitHub during build
- No GPU dependency — CPU-only OCR
- `TESSERACT_PATH` env var for custom binary path (empty = system default)
- OCR runs synchronously wrapped in `asyncio.to_thread`

### 1.6 CI/CD Setup

**CI** (`.github/workflows/ci.yml`):
- Triggers: push to `main` + PRs
- Jobs: backend tests (Python 3.12 + Tesseract) → frontend lint+build (Node 20) → Docker build check
- Tests use SQLite, no external services needed

**CD** (`.github/workflows/cd.yml`):
- Triggers: push to `main`
- Builds backend + frontend Docker images in parallel → pushes to GHCR
- Deploys via SSH to Hetzner: runs `scripts/deploy.sh` (pull → migrate → restart → health check)
- Uses GitHub secrets: `HETZNER_HOST`, `HETZNER_SSH_USER`, `HETZNER_SSH_KEY`, `NEXT_PUBLIC_API_URL`

**Quick deploy** (`scripts/quick-deploy.sh`):
- Hardcoded `deploy@37.27.210.85`
- Rsyncs files + restarts on server, skips CI

### 1.7 Hetzner-Specific References

| File | Reference |
|------|-----------|
| `.github/workflows/cd.yml` | `HETZNER_HOST`, `HETZNER_SSH_USER`, `HETZNER_SSH_KEY` secrets, job name "Deploy to Hetzner" |
| `scripts/quick-deploy.sh` | Hardcoded `deploy@37.27.210.85` |
| `CLAUDE.md` | SSH commands with `37.27.210.85`, "Hetzner VPS" references |

### 1.8 What Already Supports AWS (no changes needed)

- S3 storage provider is fully implemented and tested
- Config accepts S3 env vars
- `STORAGE_PROVIDER=s3` toggles from local to S3
- Docker images are multi-stage, production-ready
- Caddy config is generic (no Hetzner-specific routing)
- Health check endpoint exists (`/api/v1/health`)
- Alembic migrations work standalone (`alembic upgrade head`)

---

## 2. Phase 1 Plan

### 2.1 Objective

Run the existing application on a single AWS EC2 instance using Docker Compose, with RDS PostgreSQL and S3 for storage. Minimal code changes.

### 2.2 Target Architecture

```
                    ┌──────────────────────────────────────┐
                    │           EC2 Instance               │
                    │                                      │
  Internet ──:80──▶ │  Caddy ──▶ backend:8000             │
                    │         ──▶ frontend:3000            │
                    │                                      │
                    └──────────┬───────────┬───────────────┘
                               │           │
                    ┌──────────▼──┐  ┌─────▼──────┐
                    │ RDS         │  │ S3 Bucket  │
                    │ PostgreSQL  │  │ (storage)  │
                    │ 16          │  │            │
                    └─────────────┘  └────────────┘
```

### 2.3 What Changes

| Area | Change | Risk |
|------|--------|------|
| **Database** | `DATABASE_URL` points to RDS endpoint instead of `db` container | Low — just a connection string |
| **Storage** | `STORAGE_PROVIDER=s3` with S3 bucket config | Low — provider already implemented |
| **Docker Compose** | Remove `db` service, update `DATABASE_URL` | Low |
| **CI/CD** | Add AWS deploy job alongside Hetzner (don't remove Hetzner yet) | Low |
| **Env vars** | New `.env.aws.example` with RDS + S3 vars | None |
| **Deploy script** | New `scripts/deploy-aws.sh` for EC2 | None |

### 2.4 What Does NOT Change

- Backend code (zero changes)
- Frontend code (zero changes)
- Caddy config (same reverse proxy)
- Docker images (same GHCR images)
- CI pipeline (tests unchanged)
- Temporal config (stays optional)

### 2.5 Prerequisites (manual AWS setup)

These are done in the AWS Console or CLI before any code changes:

1. **EC2 instance** — `t3.medium` or `t3.large`, Ubuntu 22.04, Docker + Docker Compose installed
2. **Security group** — inbound: 80 (HTTP), 443 (HTTPS), 22 (SSH from your IP only)
3. **RDS PostgreSQL 16** — `db.t3.micro` or `db.t3.small`, same VPC as EC2
   - Security group: allow inbound 5432 from EC2's security group only
4. **S3 bucket** — private, same region as EC2
   - IAM user or role with `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`
5. **SSH key pair** — for EC2 access and GitHub Actions deployment
6. **GHCR access** — EC2 needs `docker login ghcr.io` (use a PAT or GitHub App token)

### 2.6 Deliverables

| # | Deliverable | Type |
|---|------------|------|
| 1 | `.env.aws.example` | New file — AWS-specific env template |
| 2 | `docker-compose.aws.yml` | New file — compose without `db` service, RDS connection |
| 3 | `scripts/deploy-aws.sh` | New file — deploy script for EC2 |
| 4 | `.github/workflows/cd.yml` | Updated — add AWS deploy job (keep Hetzner) |
| 5 | `scripts/quick-deploy.sh` | Updated — parameterize server address |
| 6 | Smoke test checklist | In this document |
| 7 | Rollback plan | In this document |

### 2.7 Risks

| Risk | Mitigation |
|------|-----------|
| RDS connectivity from EC2 | Same VPC + security group allowing 5432 |
| S3 permissions | Test with `aws s3 ls` before deploying |
| Tesseract in container | No change — already in Docker image |
| DNS/HTTPS not ready | Keep HTTP initially, HTTPS in Phase 2 |
| Data migration from Hetzner | `pg_dump` from Hetzner DB → `pg_restore` to RDS |
| GHCR auth on EC2 | Docker login with PAT stored on instance |
| Rollback | Hetzner stays running in parallel until verified |

### 2.8 Smoke Test Checklist

After deploying to AWS EC2:

- [ ] `curl http://<EC2_IP>/api/v1/health` returns `{"status":"healthy"}`
- [ ] Login page loads at `http://<EC2_IP>/login`
- [ ] Login with `admin@logikality.com` / `admin123` succeeds
- [ ] Dashboard loads with subscriptions
- [ ] Upload a PDF pack → pipeline processes successfully
- [ ] OCR stage completes (Tesseract works in container)
- [ ] AI analysis completes (Anthropic API reachable)
- [ ] Download PDF report works
- [ ] Delete pack works (S3 files removed)
- [ ] Chat/streaming works
- [ ] Alembic migrations ran without error

### 2.9 Rollback Plan

1. Hetzner stays running during Phase 1 — no changes to Hetzner deployment
2. DNS (if configured) can be pointed back to Hetzner IP in minutes
3. If AWS deploy fails, Hetzner continues serving traffic
4. RDS data can be discarded — it's a fresh migration
5. S3 bucket can be emptied — no production data until cutover

### 2.10 Data Migration Plan

1. On Hetzner: `pg_dump -Fc title_intelligence_hub > backup.dump`
2. Transfer to local: `scp deploy@37.27.210.85:/tmp/backup.dump .`
3. Restore to RDS: `pg_restore -h <RDS_ENDPOINT> -U postgres -d title_intelligence_hub backup.dump`
4. Storage files: if needed, sync from Hetzner volume to S3 using `aws s3 sync`
5. Verify row counts match between Hetzner and RDS

---

## 3. Implementation Status

- [ ] AWS infrastructure provisioned (EC2, RDS, S3, security groups)
- [ ] `.env.aws.example` created
- [ ] `docker-compose.aws.yml` created
- [ ] `scripts/deploy-aws.sh` created
- [ ] CD pipeline updated with AWS deploy job
- [ ] Database migrated from Hetzner to RDS
- [ ] Storage files migrated to S3
- [ ] Smoke tests passed
- [ ] Hetzner decommissioned (only after full verification)

---

## 4. Notes

- Phase 1 intentionally keeps GHCR as the image registry. Moving to ECR is Phase 2.
- Phase 1 keeps secrets in `.env` file on EC2. Secrets Manager is Phase 2.
- Phase 1 keeps HTTP. HTTPS with ACM/Route 53 is Phase 2.
- No code changes are needed for Phase 1 — the app already supports RDS (asyncpg) and S3 (aiobotocore).
