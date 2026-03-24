---
name: audit-golden-template
description: Run a golden template compliance audit on the backend codebase. Use when assessing code quality, architecture conformance, production readiness, and deterministic output stability review.
argument-hint: "[fix|report|wave N]"
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Task
effort: max
---

# Golden Template Compliance Audit

You are auditing the target mini app/backend against the golden template standard. This is the reference architecture for all future micro apps on this platform.

In addition to security, architecture, testing, and operations, you must audit the app for deterministic behavior, repeatability, and stable business outputs across repeated runs of the same input.

The goal is:

- The same input file, request, payload, or user action should produce the same business outcome every time unless:
  - the source input changed
  - the versioned prompt changed
  - the model version changed
  - the rules version changed
  - the extraction pipeline version changed
  - the retrieval index/version changed
  - the OCR/parser version changed

You must audit the application like a production system where the same input must produce the same business result repeatedly.

---

## Mode Selection

Based on `$ARGUMENTS`:

- **No args / `report`**: Run the full audit and produce the compliance report (Phase 1 only — no changes).
- **`fix`**: Run the audit, then fix all issues automatically, one wave at a time, running tests after each fix. Present a summary of all changes at the end.
- **`wave N`** (e.g., `wave 1`): Audit and report only the specified wave.
- **`fix wave N`**: Fix only issues in the specified wave.

---

## Wave Task Checklist

Score each item: **Done** (1.0), **Partial** (0.5), or **Missing** (0.0).

### Wave 1 — Security & Input Validation (Critical, weight 2.0)

| ID | Task | What to check |
|----|------|---------------|
| W1.1 | Pydantic on every POST/PUT/PATCH | All request bodies use typed Pydantic schemas — no raw `dict` or `Request.json()` |
| W1.2 | Service-layer exceptions | Routes raise `ServiceError` subclasses (`NotFoundError`, `ValidationError`, `ForbiddenError`, `ConflictError`), never `HTTPException` |
| W1.3 | Path traversal guard | `LocalStorage._resolve()` validates resolved path stays within `base_path` |
| W1.4 | PDF magic-byte check | File upload validates `%PDF-` header, not just extension |
| W1.5 | File size enforcement | Upload checks `len(data) > max_size` before writing |

### Wave 2 — Tenant Isolation & Audit (Critical, weight 2.0)

| ID | Task | What to check |
|----|------|---------------|
| W2.1 | Every query has `org_id` | All SELECT/UPDATE/DELETE on tenant-scoped tables include `org_id` in WHERE |
| W2.2 | Pipeline queries scoped | `stages.py`, `orchestrator.py`, `temporal_activities.py` — all Pack/Page/Flag/Extraction queries include `org_id` |
| W2.3 | Audit trail complete | 9 events: pack_created, files_uploaded, pipeline_started, pipeline_completed, pipeline_failed, pack_deleted, flag_{decision}, report_generated, report_downloaded |
| W2.4 | Error messages sanitized | No raw exception text exposed to clients; generic messages only |

### Wave 3 — Architecture & Plugin Boundaries (High, weight 1.5)

| ID | Task | What to check |
|----|------|---------------|
| W3.1 | StorageProvider at platform level | `app/services/storage.py` owns `StorageProvider`/`LocalStorage`/`S3Storage`; TI re-exports via shim |
| W3.2 | `get_models()` on MicroAppBase | Each micro app declares its models; `app/models/__init__.py` uses registry, not hard-coded imports |
| W3.3 | No double-mount | `discover_micro_apps()` + `include_router` called exactly once (in `create_app()`, not also in `lifespan`) |
| W3.4 | `MicroAppBase` complete | Has `slug`, `name`, `description`, `icon`, `get_router()`, `get_models()` |
| W3.5 | Lazy `__init__.py` | Micro app `__init__.py` uses `__getattr__` pattern to prevent circular imports |

### Wave 4 — Service Layer & Testing (High, weight 1.5)

| ID | Task | What to check |
|----|------|---------------|
| W4.1 | Routes are thin | Route functions delegate to service functions; no direct DB queries or AI calls in routes |
| W4.2 | Service-layer unit tests | Every service module has tests covering happy path + at least one error case |
| W4.3 | AI agent in service layer | `ReviewAssistant` called from `flag_service.get_ai_recommendation()`, not from route |
| W4.4 | Test coverage for auth | Login success, wrong password, rate limiting tests exist |
| W4.5 | Test coverage for config | JWT secret validation, Literal types, DEBUG flag tests exist |

### Wave 5 — Operational Excellence (Medium, weight 1.0)

| ID | Task | What to check |
|----|------|---------------|
| W5.1 | Request correlation | `RequestIdMiddleware` sets `X-Request-Id` on every request/response |
| W5.2 | Metrics endpoint | `GET /api/v1/metrics` returns Prometheus text format; `MetricsMiddleware` tracks count + latency |
| W5.3 | Deep health check | `GET /api/v1/health/ready` checks DB connectivity + registered apps |
| W5.4 | Structured logging | `ContextLogger` supports `org_id`, `pack_id`, `stage`, `request_id` |
| W5.5 | `datetime.utcnow()` eliminated | All datetime calls use `datetime.now(timezone.utc)` |
| W5.6 | Login rate limiting | `slowapi` on `POST /auth/login` with reasonable limit |
| W5.7 | JWT secret validation | `Settings` model_validator rejects insecure default in non-DEBUG mode |
| W5.8 | Config uses Literal types | `AI_PLATFORM`, `STORAGE_PROVIDER`, `PIPELINE_BACKEND` use `Literal` |

### Wave 6 — Determinism & Repeatability (Critical, weight 2.0)

| ID | Task | What to check |
|----|------|---------------|
| W6.1 | Separation of concerns | The app separates deterministic preprocessing, extraction, classification, scoring/decisioning, and presentation. Flag if a single LLM call directly produces final business decisions, final scores, or final recommendations without a deterministic rules layer. |
| W6.2 | Evidence first, rules later | The system does not rely on free-form LLM output for final decisions. Expected: model extracts structured facts, each fact includes source evidence, deterministic rules compute final outcome. Flag if the app asks the model to directly produce final score, final readiness, pass/fail, business recommendation, or exception severity without closed-set logic. |
| W6.3 | Stable prompting | Prompts are versioned, stored centrally, not dynamically mutated in uncontrolled ways, use explicit schemas, use closed-set labels where possible, and avoid vague open-ended instructions. Flag unconstrained prose prompts where structured extraction is expected. |
| W6.4 | Structured output enforcement | AI extraction/classification outputs use structured schemas such as JSON or typed objects with fixed schema, closed enum values, required fields, evidence fields, and confidence fields where applicable. Flag free-text parsing where structured output could have been used. |
| W6.5 | Deterministic model settings | The app pins or configures model name/version, temperature, top_p/top_k if applicable, seed if supported, max_tokens, stop conditions, and reasoning/thinking mode if applicable. Flag if these are omitted, floating, or environment-dependent. |
| W6.6 | Versioned pipeline components | The app versions and persists per run where relevant: input hash, OCR version, preprocessing version, chunking version, extraction prompt version, model version, taxonomy version, rules version, retrieval index version, scoring version. Flag missing version traceability as a reproducibility defect. |
| W6.7 | Deterministic retrieval | If retrieval or RAG is used, verify fixed chunking logic, fixed chunk overlap, fixed embedding model/version, fixed reranking logic, deterministic sorting/tie-breaking, fixed top_k, and stable filters. Flag if retrieval results may vary across runs for the same document without a version change. |
| W6.8 | Caching and replayability | The app caches immutable intermediate artifacts keyed by composite version hashes. **OCR cache**: keyed by `(page_image + tesseract_version)` via `make_ocr_path_versioned`. **AI output cache**: keyed by `(input_file_hash + ai_model + prompt_hash + tool_schema_hash)` for ingestion and `(ingestion_output_hash + ai_model + prompt_hash + tool_hash + rules_version)` for risk, via `make_ai_cache_path`. Verify: (a) `storage.exists()` check before every AI call in `stage_ingestion_agent` and `stage_risk_agent`, (b) cache write after AI call with `_serialize_ingestion_output`/`_serialize_risk_output`, (c) cache replay via `_replay_ingestion_cache`/`_replay_risk_cache` that inserts DB records from cached JSON with new UUIDs and correct FK linking, (d) risk cache stores post-normalization flags so `normalize_flags()` is not re-run on hit, (e) cache key helpers in `version_tracker.py` (`compute_ingestion_cache_key`, `compute_ingestion_output_hash`, `compute_risk_cache_key`), (f) no explicit invalidation needed — any config/model/prompt/tool/rules change produces a different hash → automatic cache miss, (g) tests in `test_ai_cache.py` cover key determinism, sensitivity to config changes, order independence, serialization roundtrips, and DB replay correctness. Flag if any AI stage skips the cache check, if cache keys omit a version component, or if cached data is replayed without idempotent delete-then-insert. |
| W6.9 | Closed-set classification | Classification tasks use bounded label sets instead of open-ended text. Expected examples: OPEN/CLOSED/RELEASED/UNKNOWN, CRITICAL/MAJOR/MINOR/INFO, READY/CONDITIONAL/NOT_READY. Flag if business-critical labels are inferred from prose after generation. |
| W6.10 | Evidence binding | Every business-critical extracted fact includes page number or source location, text span/quote/bounding box, normalized label, and confidence or verification state. Flag unsupported conclusions with no traceable evidence. |
| W6.11 | Rule engine or deterministic scoring layer | Final outcomes are computed through deterministic logic such as a rule engine, scoring matrix, policy evaluator, threshold engine, or config-driven business logic. Flag if final output depends on generative narration rather than explicit rules. |
| W6.12 | Abstention and uncertainty handling | The system supports uncertainty states such as POSSIBLE, UNCERTAIN, NEEDS_REVIEW, NOT_ENOUGH_EVIDENCE. Flag if the system is forced to decide when confidence is low. |
| W6.13 | Regression and golden set testing | The app includes repeatability tests that rerun the same inputs multiple times and compare extracted facts, classifications, score/recommendation, reason codes, and evidence bindings. Expected: golden dataset, deterministic regression tests, snapshot or semantic diff checks, variance reports. Flag absence of repeatability tests as a production readiness gap. |
| W6.14 | Output stability contract | The app defines which outputs must remain stable: final score, final status, reason codes, extracted critical entities, evidence spans. Document acceptable variance: wording may vary in explanation text; business results must not vary for same input/version set. Flag lack of explicit stability contract. |
| W6.15 | Determinism gate | A mini app cannot be marked production-ready if the same input can produce different business outcomes across repeated runs, final scoring is directly LLM-generated, prompt/model/rule versions are not traceable, critical extracted facts are not evidence-linked, or repeatability tests are absent. |

---

## Audit Procedure

1. **Read CLAUDE.md** for current architecture context.
2. **For each wave**, grep/read the relevant files and score each task.
3. **Compile the report** in the format below.
4. For Wave 6, audit the app specifically for deterministic behavior, repeatability, and stable business outputs.
5. Focus especially on:
   - places where an LLM directly decides business outcomes
   - places where retrieval may drift
   - places where parsing is brittle
   - places where output schemas are weak or absent
   - places where prompt logic is doing work that business rules should do
   - places where missing caching or versioning breaks reproducibility
6. Do not give generic advice.
7. Do not merely say “reduce temperature.”
8. Audit the app like a production system where the same input must produce the same business result repeatedly.

### File Targets per Wave

- **W1**: `routes/*.py`, `services/pack_service.py`, `services/storage.py`, `core/exceptions.py`
- **W2**: `pipeline/stages.py`, `pipeline/orchestrator.py`, `pipeline/temporal_activities.py`, `routes/packs.py`, `routes/flags.py`, `routes/reports.py`, `services/chat_service.py`
- **W3**: `app/services/storage.py`, `app/micro_apps/base.py`, `app/micro_apps/registry.py`, `app/main.py`, `app/models/__init__.py`, `micro_apps/title_intelligence/__init__.py`
- **W4**: `routes/*.py`, `services/*.py`, `tests/`
- **W5**: `core/middleware.py`, `core/metrics.py`, `core/logging.py`, `api/v1/health.py`, `api/v1/auth.py`, `config.py`, all files for `utcnow`
- **W6**: `pipeline/stages.py` (AI cache check/save + serialization/replay helpers), `pipeline/version_tracker.py` (cache key computation), `pipeline/orchestrator.py`, `services/storage.py` (`make_ai_cache_path`, `make_ocr_path_versioned`), `services/*.py`, `ai/*.py`, `config.py`, `tests/title_intelligence/test_ai_cache.py`, `tests/title_intelligence/test_determinism.py`, extraction/scoring modules, retrieval modules, OCR/parser integrations

---

## Output Format

```markdown
# Golden Template Compliance Audit

**Date**: {date}
**Test count**: {N} passing

## Score Summary

| Wave | Weight | Score | Weighted |
|------|--------|-------|----------|
| W1 Security | 2.0 | X/5 | ... |
| W2 Tenant | 2.0 | X/4 | ... |
| W3 Architecture | 1.5 | X/5 | ... |
| W4 Service Layer | 1.5 | X/5 | ... |
| W5 Operations | 1.0 | X/8 | ... |
| W6 Determinism | 2.0 | X/15 | ... |
| **Total** | | | **X/12.0** |

## Detailed Findings

### Wave 1 — Security & Input Validation
| ID | Task | Status | Notes |
|----|------|--------|-------|
| W1.1 | Pydantic schemas | Done/Partial/Missing | ... |

### Wave 2 — Tenant Isolation & Audit
| ID | Task | Status | Notes |
|----|------|--------|-------|
| W2.1 | Every query has `org_id` | Done/Partial/Missing | ... |

### Wave 3 — Architecture & Plugin Boundaries
| ID | Task | Status | Notes |
|----|------|--------|-------|
| W3.1 | StorageProvider at platform level | Done/Partial/Missing | ... |

### Wave 4 — Service Layer & Testing
| ID | Task | Status | Notes |
|----|------|--------|-------|
| W4.1 | Routes are thin | Done/Partial/Missing | ... |

### Wave 5 — Operational Excellence
| ID | Task | Status | Notes |
|----|------|--------|-------|
| W5.1 | Request correlation | Done/Partial/Missing | ... |

### Wave 6 — Determinism & Repeatability
| ID | Task | Status | Notes |
|----|------|--------|-------|
| W6.1 | Separation of concerns | Done/Partial/Missing | ... |
| W6.2 | Evidence first, rules later | Done/Partial/Missing | ... |
| W6.3 | Stable prompting | Done/Partial/Missing | ... |
| W6.4 | Structured output enforcement | Done/Partial/Missing | ... |
| W6.5 | Deterministic model settings | Done/Partial/Missing | ... |
| W6.6 | Versioned pipeline components | Done/Partial/Missing | ... |
| W6.7 | Deterministic retrieval | Done/Partial/Missing | ... |
| W6.8 | Caching and replayability | Done/Partial/Missing | ... |
| W6.9 | Closed-set classification | Done/Partial/Missing | ... |
| W6.10 | Evidence binding | Done/Partial/Missing | ... |
| W6.11 | Rule engine or deterministic scoring layer | Done/Partial/Missing | ... |
| W6.12 | Abstention and uncertainty handling | Done/Partial/Missing | ... |
| W6.13 | Regression and golden set testing | Done/Partial/Missing | ... |
| W6.14 | Output stability contract | Done/Partial/Missing | ... |
| W6.15 | Determinism gate | Done/Partial/Missing | ... |

## Determinism Review

### Determinism Score
Give a score out of 10 for deterministic architecture.

### Executive Summary
Summarize whether the app is capable of producing stable business outcomes for repeated identical inputs.

### Non-Determinism Risks
List every design or implementation area causing output instability.

### Root Causes
Explain the specific underlying causes of drift.

### Required Architecture Fixes
For each issue, provide:
- what is wrong
- why it causes non-determinism
- exact remediation recommendation

### Required Code Fixes
Identify:
- missing versioning
- missing schemas
- missing rules
- unstable retrieval
- prompt issues
- missing cache strategy
- missing evidence binding
- direct LLM-driven scoring

### Required Testing Fixes
Call out missing repeatability tests, golden datasets, snapshot diffs, or variance reports.

### Recommended Deterministic Target Design
Provide the ideal deterministic architecture for this app in practical engineering terms.

### Repeatability Sign-Off Checklist
Provide a checklist the implementer can use before sign-off.

## Priority Remediation

1. {highest impact item}
2. ...

## Fix Mode Rules

When running in **fix** mode:

1. Work through waves in order (W1 → W6).
2. For each Missing/Partial item, implement the fix.
3. Run `pytest --tb=short -q` after each fix to verify no regressions.
4. If tests fail, fix the failure before moving on.
5. Never change test assertions to make tests pass — fix the code.
6. Present a summary table of all changes when done.
7. Do NOT commit — let the user decide when to commit.