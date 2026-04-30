"""Tests for the compliance API routes.

Covers:
  - GET /compliance — auto-evaluate when no run exists; return latest otherwise
  - POST /compliance/evaluate — force a fresh evaluation, persist a new run
  - PATCH /compliance/context — validate enums, echo persisted snapshot
  - GET /compliance/report.pdf — returns application/pdf bytes
  - 404 for unknown package, 422 for unknown enum value
  - Tenant isolation — requesting org without a subscription is blocked by
    the access middleware (403)
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.compliance import LOComplianceRun
from app.micro_apps.loan_onboarding.models.stack import LOStack
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID

BASE = "/api/v1/apps/loan-onboarding"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


async def _seed_compliance_stacks(
    db: AsyncSession, doc_types: list[str]
) -> None:
    """Seed minimal `LOStack` rows so the service has a doc inventory."""
    for i, dt in enumerate(doc_types):
        db.add(LOStack(
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            stack_index=i,
            doc_type=dt,
            page_numbers=[i + 1],
            first_page=i + 1,
            last_page=i + 1,
            classification_confidence=0.95,
            overall_confidence=0.95,
            status="accepted",
            requires_hitl=False,
        ))
    await db.commit()


# ── GET /compliance ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_compliance_auto_evaluates_when_no_run_exists(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    await _seed_compliance_stacks(db_session, ["Form 1003", "Paystubs"])
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance", headers=HEADERS
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["package_id"] == str(TEST_PACKAGE_ID)
    assert body["rules_version"]
    assert len(body["rule_set_hash"]) == 64
    assert body["doc_inventory_snapshot"] == ["Form 1003", "Paystubs"]
    # cmp_app_urla and cmp_atr_income should be compliant.
    by_id = {f["id"]: f for f in body["findings"]}
    assert by_id["cmp_app_urla"]["status"] == "compliant"
    assert by_id["cmp_atr_income"]["status"] == "compliant"
    # lo_view contract — closeability + deal_killers + borrower_asks present.
    assert {"closeability", "deal_killers", "borrower_asks"} <= set(body["lo_view"])

    # And a row was persisted.
    rows = (await db_session.execute(
        select(LOComplianceRun).where(
            LOComplianceRun.package_id == TEST_PACKAGE_ID
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_compliance_returns_existing_run_without_re_evaluating(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    await _seed_compliance_stacks(db_session, ["Form 1003"])
    # First call seeds a run.
    r1 = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance", headers=HEADERS
    )
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]

    # Second call must return the same run, not create a new one.
    r2 = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance", headers=HEADERS
    )
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id

    rows = (await db_session.execute(
        select(LOComplianceRun).where(
            LOComplianceRun.package_id == TEST_PACKAGE_ID
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_compliance_404_for_unknown_package(
    client: AsyncClient, lo_app_and_subscription
):
    bogus = uuid.uuid4()
    resp = await client.get(
        f"{BASE}/packages/{bogus}/compliance", headers=HEADERS
    )
    assert resp.status_code == 404


# ── POST /compliance/evaluate ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_evaluate_creates_new_run_each_call(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    await _seed_compliance_stacks(db_session, ["Form 1003"])
    r1 = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/evaluate", headers=HEADERS
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/evaluate", headers=HEADERS
    )
    assert r2.status_code == 200
    assert r1.json()["run_id"] != r2.json()["run_id"]

    rows = (await db_session.execute(
        select(LOComplianceRun).where(
            LOComplianceRun.package_id == TEST_PACKAGE_ID
        )
    )).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_post_evaluate_404_for_unknown_package(
    client: AsyncClient, lo_app_and_subscription
):
    bogus = uuid.uuid4()
    resp = await client.post(
        f"{BASE}/packages/{bogus}/compliance/evaluate", headers=HEADERS
    )
    assert resp.status_code == 404


# ── PATCH /compliance/context ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_context_persists_and_echoes(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    payload = {
        "program": "fha",
        "purpose": "purchase",
        "occupancy": "primary",
        "state": "NY",
        "scenarioFlags": ["gift_funds", "first_time"],
        "ausEngine": "du",
        "ausWaivers": [],
        "loanAmount": 350000,
        "propertyValue": 425000,
    }
    resp = await client.patch(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/context",
        json=payload,
        headers=HEADERS,
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["program"] == "fha"
    assert out["state"] == "NY"
    assert sorted(out["scenarioFlags"]) == ["first_time", "gift_funds"]


@pytest.mark.asyncio
async def test_patch_context_422_on_unknown_enum(
    client: AsyncClient, sample_package
):
    payload = {
        "program": "not_a_real_program",
        "purpose": "purchase",
        "occupancy": "primary",
        "state": "CT",
        "scenarioFlags": [],
        "ausEngine": "du",
        "ausWaivers": [],
    }
    resp = await client.patch(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/context",
        json=payload,
        headers=HEADERS,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_context_422_on_unknown_state(
    client: AsyncClient, sample_package
):
    payload = {
        "program": "conv",
        "purpose": "purchase",
        "occupancy": "primary",
        "state": "ZZ",
        "scenarioFlags": [],
        "ausEngine": "du",
        "ausWaivers": [],
    }
    resp = await client.patch(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/context",
        json=payload,
        headers=HEADERS,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_context_404_for_unknown_package(
    client: AsyncClient, lo_app_and_subscription
):
    bogus = uuid.uuid4()
    resp = await client.patch(
        f"{BASE}/packages/{bogus}/compliance/context",
        json={
            "program": "conv", "purpose": "purchase", "occupancy": "primary",
            "state": "CT", "scenarioFlags": [], "ausEngine": "du", "ausWaivers": [],
        },
        headers=HEADERS,
    )
    assert resp.status_code == 404


# ── GET /compliance/report.pdf ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_compliance_report_returns_pdf(
    client: AsyncClient, sample_package, db_session: AsyncSession
):
    await _seed_compliance_stacks(db_session, ["Form 1003", "Paystubs"])
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/report.pdf",
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    assert len(resp.content) > 1000  # Sanity — empty PDFs are <500 bytes
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert ".pdf" in cd


@pytest.mark.asyncio
async def test_download_compliance_report_404_for_unknown_package(
    client: AsyncClient, lo_app_and_subscription
):
    bogus = uuid.uuid4()
    resp = await client.get(
        f"{BASE}/packages/{bogus}/compliance/report.pdf", headers=HEADERS
    )
    assert resp.status_code == 404


# ── Tenant isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_get_blocked_for_other_org(
    client: AsyncClient, sample_package
):
    """Org B has no subscription → middleware blocks with 403 before route runs."""
    other = uuid.UUID("00000000-0000-0000-0000-00000000beef")
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance",
        headers={"X-Org-Id": str(other)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_compliance_evaluate_blocked_for_other_org(
    client: AsyncClient, sample_package
):
    other = uuid.UUID("00000000-0000-0000-0000-00000000beef")
    resp = await client.post(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/evaluate",
        headers={"X-Org-Id": str(other)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_compliance_pdf_blocked_for_other_org(
    client: AsyncClient, sample_package
):
    other = uuid.UUID("00000000-0000-0000-0000-00000000beef")
    resp = await client.get(
        f"{BASE}/packages/{TEST_PACKAGE_ID}/compliance/report.pdf",
        headers={"X-Org-Id": str(other)},
    )
    assert resp.status_code == 403
