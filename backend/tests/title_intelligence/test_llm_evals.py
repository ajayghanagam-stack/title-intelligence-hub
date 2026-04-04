"""LLM-level evaluation tests for pipeline output stability.

These tests call real AI APIs (Gemini) and compare output against golden
datasets. They are excluded from normal CI and run on-demand or in a
dedicated eval CI job.

Usage:
    pytest tests/title_intelligence/test_llm_evals.py -v -m llm_eval
    python scripts/run_evals.py  # CLI wrapper

Requirements:
    - GOOGLE_API_KEY environment variable set
    - Golden datasets in tests/title_intelligence/golden/
    - Input PDFs present in golden dataset directories
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.title_intelligence.eval_config import DEFAULT_THRESHOLDS
from tests.title_intelligence.eval_helpers import (
    build_eval_report,
    compare_extractions,
    compare_flags,
    compare_sections,
    compare_transcriptions,
    compute_eval_fingerprint,
)
from tests.title_intelligence.golden.loader import (
    load_golden_set,
    list_golden_sets,
    validate_golden_set_versions,
)


# All tests in this module require the llm_eval marker
pytestmark = pytest.mark.llm_eval

# Namespace for deterministic UUIDs
_NS = uuid.NAMESPACE_DNS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def golden_simple():
    """Load the simple_commitment golden dataset."""
    try:
        return load_golden_set("simple_commitment")
    except FileNotFoundError:
        pytest.skip("simple_commitment golden dataset not found")


@pytest.fixture
def golden_complex():
    """Load the complex_commitment golden dataset."""
    try:
        return load_golden_set("complex_commitment")
    except FileNotFoundError:
        pytest.skip("complex_commitment golden dataset not found")


# ---------------------------------------------------------------------------
# Pipeline runner fixture (runs once per session for each dataset)
# ---------------------------------------------------------------------------


async def _run_pipeline_for_dataset(dataset_name: str) -> dict:
    """Run the TI pipeline on a golden dataset PDF and return cache results.

    Sets up a temporary SQLite DB + LocalStorage, seeds minimal ORM records,
    runs stages 1-3 (ingest → render → examine), and reads the AI cache.
    """
    from tests.title_intelligence.golden.loader import GOLDEN_DIR

    pdf_path = GOLDEN_DIR / dataset_name / "input.pdf"
    if not pdf_path.exists():
        pytest.skip(f"No input PDF for {dataset_name}")

    pdf_bytes = pdf_path.read_bytes()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # Save original env vars to restore later
    _saved_env = {}
    _env_keys = [
        "DATABASE_URL", "STORAGE_PROVIDER", "STORAGE_PATH",
        "AI_PROVIDER", "PIPELINE_MODE", "PIPELINE_BACKEND",
        "DEBUG", "JWT_SECRET",
        "VERTEX_AI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_REGION",
    ]
    for k in _env_keys:
        _saved_env[k] = os.environ.get(k)

    # Create temp directory for DB + storage
    tmp_dir = tempfile.mkdtemp(prefix=f"eval_{dataset_name}_")

    try:
        # Configure environment
        db_path = os.path.join(tmp_dir, "eval.db")
        storage_path = os.path.join(tmp_dir, "storage")
        os.makedirs(storage_path, exist_ok=True)

        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
        os.environ["STORAGE_PROVIDER"] = "local"
        os.environ["STORAGE_PATH"] = storage_path
        os.environ["AI_PROVIDER"] = "gemini"
        os.environ["PIPELINE_MODE"] = "native_pdf"
        os.environ["PIPELINE_BACKEND"] = "background_tasks"
        os.environ["DEBUG"] = "true"
        os.environ["JWT_SECRET"] = "eval-test-secret"
        # Vertex AI — uses Application Default Credentials
        os.environ["VERTEX_AI"] = "true"
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "ti-stage")
        os.environ.setdefault("GOOGLE_CLOUD_REGION", "us-central1")

        # Force fresh Settings so stages pick up the temp storage path
        from app.config import get_settings
        get_settings.cache_clear()

        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

        from app.models import Base, ensure_micro_app_models
        from app.models.organization import Organization
        from app.models.user import User
        from app.models.micro_app import MicroApp
        from app.models.subscription import Subscription
        from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
        from app.micro_apps.title_intelligence.pipeline.stages import (
            stage_ingest,
            stage_render,
            stage_examine,
        )
        from app.services.storage import LocalStorage

        # Deterministic UUIDs
        org_id = uuid.uuid5(_NS, f"{dataset_name}.org")
        user_id = uuid.uuid5(_NS, f"{dataset_name}.user")
        app_id = uuid.uuid5(_NS, f"{dataset_name}.app")
        sub_id = uuid.uuid5(_NS, f"{dataset_name}.sub")
        pack_id = uuid.uuid5(_NS, f"{dataset_name}.pack")
        file_id = uuid.uuid5(_NS, f"{dataset_name}.file")

        # Setup DB
        ensure_micro_app_models()
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Setup storage — pass explicit base_path so it ignores Settings
        storage = LocalStorage(base_path=storage_path)
        pdf_storage_path = f"{org_id}/{pack_id}/files/input.pdf"
        await storage.save(pdf_storage_path, pdf_bytes)

        # Seed data
        async with session_factory() as db:
            db.add(Organization(id=org_id, name="eval-test", slug="eval-test"))
            db.add(User(
                id=user_id, auth_user_id=user_id, org_id=org_id,
                email="eval@test.com", full_name="Eval Test", role="owner",
            ))
            db.add(MicroApp(
                id=app_id, name="Title Intelligence",
                slug="title-intelligence", description="Eval", icon="file-search",
            ))
            db.add(Subscription(
                id=sub_id, org_id=org_id, app_id=app_id, status="active",
                purchased_at=datetime.now(timezone.utc),
                enabled_at=datetime.now(timezone.utc),
            ))
            db.add(Pack(id=pack_id, org_id=org_id, name=dataset_name, status="uploading"))
            db.add(PackFile(
                id=file_id, pack_id=pack_id, org_id=org_id,
                filename="input.pdf", storage_path=pdf_storage_path,
                file_size=len(pdf_bytes), content_hash=pdf_sha256,
            ))
            await db.commit()

        # Run pipeline stages
        async with session_factory() as db:
            await stage_ingest(pack_id, org_id, db, storage)
        async with session_factory() as db:
            await stage_render(pack_id, org_id, db, storage)
        async with session_factory() as db:
            await stage_examine(pack_id, org_id, db, storage)

        # Find AI cache file
        cache_data = None
        for cache_dir_name in ["examiner_native", "examiner"]:
            cache_dir = Path(storage_path) / str(org_id) / "ai_cache" / cache_dir_name
            if cache_dir.exists():
                cache_files = list(cache_dir.glob("v_*.json"))
                if cache_files:
                    cache_file = max(cache_files, key=lambda f: f.stat().st_mtime)
                    cache_data = json.loads(cache_file.read_text())
                    break

        await engine.dispose()

        if cache_data is None:
            pytest.fail(f"No AI cache file found after pipeline run for {dataset_name}")

        return {
            "triage": cache_data.get("page_types", []),
            "transcriptions": cache_data.get("page_transcriptions", []),
            "sections": cache_data.get("sections", []),
            "extractions": cache_data.get("extractions", []),
            "flags_raw": cache_data.get("flags_raw", []),
            "flags_normalized": cache_data.get("flags", []),
        }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Restore original env vars
        for k in _env_keys:
            if _saved_env[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = _saved_env[k]
        from app.config import get_settings
        get_settings.cache_clear()


# Cache pipeline results per dataset so we only run the pipeline once
_pipeline_cache: dict[str, dict] = {}


def _has_gemini_credentials() -> bool:
    """Check if Gemini credentials are available (Vertex AI ADC or API key)."""
    if os.environ.get("GOOGLE_API_KEY"):
        return True
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return True
    try:
        from app.config import get_settings
        s = get_settings()
        return s._has_gemini_credentials
    except Exception:
        return False


@pytest.fixture
async def pipeline_simple(golden_simple):
    """Run pipeline on simple_commitment PDF (cached across tests)."""
    if not golden_simple.has_pdf:
        pytest.skip("No input PDF in golden dataset")
    if not _has_gemini_credentials():
        pytest.skip("No Gemini credentials (GOOGLE_API_KEY or Vertex AI)")

    if "simple_commitment" not in _pipeline_cache:
        _pipeline_cache["simple_commitment"] = await _run_pipeline_for_dataset(
            "simple_commitment"
        )
    return _pipeline_cache["simple_commitment"]


# ---------------------------------------------------------------------------
# Golden set version checks (always run, no LLM needed)
# ---------------------------------------------------------------------------


class TestGoldenSetIntegrity:
    """Validate golden dataset structure and version compatibility."""

    def test_golden_sets_exist(self):
        """At least one golden dataset exists."""
        datasets = list_golden_sets()
        assert len(datasets) >= 1, "No golden datasets found"

    def test_golden_set_version_current(self):
        """All golden sets match current code versions."""
        for name in list_golden_sets():
            ds = load_golden_set(name)
            mismatches = validate_golden_set_versions(ds)
            assert not mismatches, (
                f"Golden set '{name}' has stale versions. "
                f"Regenerate with: python scripts/run_evals.py --update-golden\n"
                f"Mismatches: {mismatches}"
            )

    def test_golden_set_has_required_fields(self, golden_simple):
        """Golden dataset has all required fixture files."""
        ds = golden_simple
        assert ds.metadata is not None
        assert len(ds.sections) > 0, "Golden set should have sections"
        assert len(ds.extractions) > 0, "Golden set should have extractions"
        assert len(ds.flags_normalized) > 0, "Golden set should have normalized flags"


# ---------------------------------------------------------------------------
# Offline comparison tests (no LLM, validate eval framework itself)
# ---------------------------------------------------------------------------


class TestEvalFramework:
    """Test the comparison framework with known golden data."""

    def test_extraction_self_comparison(self, golden_simple):
        """Comparing golden extractions to themselves → 100% match."""
        diff = compare_extractions(golden_simple.extractions, golden_simple.extractions)
        assert diff.match_rate == 1.0
        assert len(diff.missing) == 0
        assert len(diff.extra) == 0

    def test_flag_self_comparison(self, golden_simple):
        """Comparing golden flags to themselves → 100% match."""
        diff = compare_flags(golden_simple.flags_normalized, golden_simple.flags_normalized)
        assert diff.match_rate == 1.0
        assert len(diff.missing) == 0
        assert len(diff.extra) == 0

    def test_section_self_comparison(self, golden_simple):
        """Comparing golden sections to themselves → 100% match."""
        diff = compare_sections(golden_simple.sections, golden_simple.sections)
        assert diff.match_rate == 1.0

    def test_eval_report_passes_on_self(self, golden_simple):
        """Full eval report on self-comparison passes."""
        report = build_eval_report(
            "self_test",
            actual_extractions=golden_simple.extractions,
            expected_extractions=golden_simple.extractions,
            actual_flags=golden_simple.flags_normalized,
            expected_flags=golden_simple.flags_normalized,
            actual_sections=golden_simple.sections,
            expected_sections=golden_simple.sections,
        )
        assert report.passed
        assert "PASS" in report.summary()

    def test_eval_report_fails_on_empty(self, golden_simple):
        """Eval report with missing extractions fails thresholds."""
        report = build_eval_report(
            "fail_test",
            actual_extractions=[],
            expected_extractions=golden_simple.extractions,
        )
        assert not report.passed

    def test_fingerprint_deterministic(self, golden_simple):
        """Same data → same fingerprint 10x."""
        fps = [
            compute_eval_fingerprint(
                golden_simple.extractions,
                golden_simple.flags_normalized,
                golden_simple.sections,
            )
            for _ in range(10)
        ]
        assert len(set(fps)) == 1

    def test_fingerprint_changes_on_extra_flag(self, golden_simple):
        """Adding a flag changes the fingerprint."""
        fp_baseline = compute_eval_fingerprint(
            golden_simple.extractions,
            golden_simple.flags_normalized,
            golden_simple.sections,
        )
        extra_flags = golden_simple.flags_normalized + [{
            "flag_type": "chain_of_title_gap",
            "severity": "high",
            "title": "Extra flag",
        }]
        fp_changed = compute_eval_fingerprint(
            golden_simple.extractions,
            extra_flags,
            golden_simple.sections,
        )
        assert fp_baseline != fp_changed


# ---------------------------------------------------------------------------
# LLM stability tests (require GOOGLE_API_KEY and input PDFs)
# ---------------------------------------------------------------------------


class TestLLMStability:
    """Run pipeline against golden datasets, compare to expected output.

    These tests require:
    1. GOOGLE_API_KEY environment variable
    2. Input PDFs in golden dataset directories
    3. Run with: pytest -m llm_eval

    Skipped automatically if prerequisites are missing.
    """

    async def test_simple_commitment_extractions(self, golden_simple, pipeline_simple):
        """Extractions for simple commitment match golden set."""
        diff = compare_extractions(pipeline_simple["extractions"], golden_simple.extractions)
        t = DEFAULT_THRESHOLDS
        assert diff.match_rate >= t.extraction_match_rate, (
            f"Extraction match rate {diff.match_rate:.0%} < {t.extraction_match_rate:.0%}. "
            f"Missing: {len(diff.missing)}, Extra: {len(diff.extra)}"
        )
        assert diff.missing_rate <= t.extraction_max_missing, (
            f"Missing rate {diff.missing_rate:.0%} > {t.extraction_max_missing:.0%}"
        )

    async def test_simple_commitment_flags(self, golden_simple, pipeline_simple):
        """Flags for simple commitment match golden set."""
        diff = compare_flags(pipeline_simple["flags_normalized"], golden_simple.flags_normalized)
        t = DEFAULT_THRESHOLDS
        assert diff.match_rate >= t.flag_match_rate, (
            f"Flag match rate {diff.match_rate:.0%} < {t.flag_match_rate:.0%}. "
            f"Missing: {len(diff.missing)}, Extra: {len(diff.extra)}"
        )
        assert diff.missing_rate <= t.flag_max_missing, (
            f"Missing rate {diff.missing_rate:.0%} > {t.flag_max_missing:.0%}"
        )

    async def test_simple_commitment_sections(self, golden_simple, pipeline_simple):
        """Sections for simple commitment match golden set."""
        diff = compare_sections(pipeline_simple["sections"], golden_simple.sections)
        t = DEFAULT_THRESHOLDS
        assert diff.match_rate >= t.section_match_rate, (
            f"Section match rate {diff.match_rate:.0%} < {t.section_match_rate:.0%}. "
            f"Missing: {len(diff.missing)}, Extra: {len(diff.extra)}"
        )

    async def test_simple_commitment_transcriptions(self, golden_simple, pipeline_simple):
        """Transcriptions for simple commitment match golden set."""
        if not golden_simple.transcriptions:
            pytest.skip("No golden transcriptions to compare")
        diff = compare_transcriptions(
            pipeline_simple["transcriptions"], golden_simple.transcriptions
        )
        t = DEFAULT_THRESHOLDS
        assert diff.average_similarity >= t.transcription_min_similarity, (
            f"Avg transcription similarity {diff.average_similarity:.3f} "
            f"< {t.transcription_min_similarity}. "
            f"{len(diff.low_similarity_pages)} pages below threshold"
        )

    async def test_simple_commitment_triage(self, golden_simple, pipeline_simple):
        """Triage classifications match golden set."""
        if not golden_simple.triage:
            pytest.skip("No golden triage to compare")
        expected_map = {t["page_number"]: t["page_type"] for t in golden_simple.triage}
        actual_map = {t["page_number"]: t["page_type"] for t in pipeline_simple["triage"]}
        total = len(expected_map)
        matched = sum(
            1 for pn, pt in expected_map.items()
            if actual_map.get(pn) == pt
        )
        match_rate = matched / total if total else 1.0
        t = DEFAULT_THRESHOLDS
        assert match_rate >= t.triage_match_rate, (
            f"Triage match rate {match_rate:.0%} < {t.triage_match_rate:.0%}. "
            f"{total - matched} pages differ"
        )

    async def test_simple_commitment_full_report(self, golden_simple, pipeline_simple):
        """Full eval report for simple commitment passes all thresholds."""
        report = build_eval_report(
            "simple_commitment",
            actual_extractions=pipeline_simple["extractions"],
            expected_extractions=golden_simple.extractions,
            actual_flags=pipeline_simple["flags_normalized"],
            expected_flags=golden_simple.flags_normalized,
            actual_sections=pipeline_simple["sections"],
            expected_sections=golden_simple.sections,
            actual_transcriptions=pipeline_simple["transcriptions"],
            expected_transcriptions=golden_simple.transcriptions,
        )
        print(f"\n{report.summary()}")
        assert report.passed, f"Eval report FAILED:\n{report.summary()}"
