"""Loan Onboarding test fixtures."""
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.doc_type_config import LODocTypeConfig
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
    reset_version_info_cache,
)
from app.models.micro_app import MicroApp
from app.models.subscription import Subscription

from tests.conftest import TEST_ORG_ID, TEST_USER_ID


@pytest.fixture(autouse=True)
def _wipe_lo_ai_cache():
    """Ensure every LO test starts with a clean AI cache directory.

    The storage singleton persists across tests and `./test_storage/` is not
    cleaned between runs, so without this a prior test that wrote cached
    classify/validate/review JSON can mask mocks on a later test (cache hit
    skips the LLM call entirely). We also reset the process-cached
    version_info so each test sees a freshly-computed version snapshot.

    Two cache layouts to scrub:
    1. Legacy org-scoped: `{org_id}/ai_cache/...` (still used by TI/TSA
       and any LO code paths that route through the shared helper)
    2. Package-scoped: `{org_id}/{package_id}/ai_cache/...` (LO writes
       here via `_lo_cache_path()` so package deletion is self-cleaning)
    """
    def _wipe():
        storage_path = Path(get_settings().STORAGE_PATH)
        org_dir = storage_path / str(TEST_ORG_ID)
        # Legacy org-scoped cache
        legacy = org_dir / "ai_cache"
        if legacy.exists():
            shutil.rmtree(legacy, ignore_errors=True)
        # Package-scoped caches under any package id in this org
        if org_dir.exists():
            for child in org_dir.iterdir():
                pkg_cache = child / "ai_cache"
                if pkg_cache.exists():
                    shutil.rmtree(pkg_cache, ignore_errors=True)

    reset_version_info_cache()
    _wipe()
    yield
    _wipe()

# LO-specific test UUIDs (use a distinct range from TI/TSA)
TEST_LO_APP_ID = uuid.UUID("00000000-0000-0000-0000-000000003000")
TEST_PACKAGE_ID = uuid.UUID("00000000-0000-0000-0001-000000010000")
TEST_PACKAGE_FILE_ID = uuid.UUID("00000000-0000-0000-0001-000000020000")
TEST_PAGE_ID = uuid.UUID("00000000-0000-0000-0001-000000030000")
TEST_STACK_ID = uuid.UUID("00000000-0000-0000-0001-000000040000")
TEST_CLASSIFICATION_ID = uuid.UUID("00000000-0000-0000-0001-000000050000")
TEST_VALIDATION_ID = uuid.UUID("00000000-0000-0000-0001-000000060000")


@pytest_asyncio.fixture
async def lo_app_and_subscription(db_session: AsyncSession, seed_data):
    """Register the Loan Onboarding micro-app + active subscription for the test org."""
    lo_app = MicroApp(
        id=TEST_LO_APP_ID,
        name="Loan Onboarding",
        slug="loan-onboarding",
        description="Mortgage loan package processing",
        icon="folder-open",
    )
    db_session.add(lo_app)

    sub = Subscription(
        org_id=TEST_ORG_ID,
        app_id=TEST_LO_APP_ID,
        status="active",
        purchased_at=datetime.now(timezone.utc),
        enabled_at=datetime.now(timezone.utc),
    )
    db_session.add(sub)
    await db_session.commit()
    return lo_app


@pytest_asyncio.fixture
async def sample_package(db_session: AsyncSession, lo_app_and_subscription):
    """Create a baseline package with a doc-type config and one preset rule."""
    package = LOPackage(
        id=TEST_PACKAGE_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        name="Smith Loan #1001",
        borrower_name="Jane Smith",
        loan_reference="LN-1001",
        hitl_threshold=0.75,
        status="uploading",
    )
    db_session.add(package)
    await db_session.flush()

    config = LODocTypeConfig(
        org_id=TEST_ORG_ID,
        package_id=package.id,
        doc_types=[
            {"key": "urla_1003", "label": "Uniform Residential Loan App (1003)", "required": True},
            {"key": "paystub", "label": "Pay Stub", "required": True},
            {"key": "w2", "label": "W-2", "required": False},
        ],
    )
    db_session.add(config)

    rule = LOValidationRule(
        org_id=TEST_ORG_ID,
        package_id=package.id,
        rule_source="preset",
        rule_id="missing_signatures",
        description="Flag stacks with unsigned pages",
        config={},
        enabled=True,
    )
    db_session.add(rule)

    await db_session.commit()
    return package
