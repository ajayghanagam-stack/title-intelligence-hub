"""Routes tests for the Phase 2 org-admin config CRUD surface.

Covers list + create + update for all four resources, plus the two
write paths that fire tighten-only validators (extraction schemas
version-bump on edit, profile shape + override checks).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.doc_type_catalog import LODocTypeCatalog
from app.micro_apps.loan_onboarding.models.extraction_schema import LOExtractionSchema
from app.micro_apps.loan_onboarding.models.program_profile import LOProgramProfile
from app.micro_apps.loan_onboarding.models.validation_rule_org import (
    LOValidationRuleOrg,
)
from tests.conftest import TEST_ORG_ID

BASE = "/api/v1/apps/loan-onboarding/admin/config"
HEADERS = {"X-Org-Id": str(TEST_ORG_ID)}


# ── Doc-type catalog ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_doc_type(
    client: AsyncClient, lo_app_and_subscription, db_session: AsyncSession,
):
    r = await client.post(
        f"{BASE}/doc-types",
        json={
            "key": "paystub",
            "name": "Paystub",
            "category": "income",
            "auto_classify_enabled": True,
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"] == "paystub"
    assert body["active"] is True

    listed = await client.get(f"{BASE}/doc-types", headers=HEADERS)
    assert listed.status_code == 200
    keys = [d["key"] for d in listed.json()]
    assert "paystub" in keys


@pytest.mark.asyncio
async def test_create_doc_type_rejects_duplicate_key(
    client: AsyncClient, lo_app_and_subscription,
):
    payload = {"key": "w2", "name": "W-2", "category": "income"}
    r1 = await client.post(f"{BASE}/doc-types", json=payload, headers=HEADERS)
    assert r1.status_code == 201
    r2 = await client.post(f"{BASE}/doc-types", json=payload, headers=HEADERS)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_patch_doc_type_can_deactivate(
    client: AsyncClient, lo_app_and_subscription, db_session: AsyncSession,
):
    create = await client.post(
        f"{BASE}/doc-types",
        json={"key": "old_form", "name": "Old", "category": "other"},
        headers=HEADERS,
    )
    doc_id = create.json()["id"]
    r = await client.patch(
        f"{BASE}/doc-types/{doc_id}", json={"active": False}, headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["active"] is False


# ── Extraction schemas ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_extraction_schema(
    client: AsyncClient, lo_app_and_subscription, db_session: AsyncSession,
):
    cat = await client.post(
        f"{BASE}/doc-types",
        json={"key": "paystub", "name": "Paystub", "category": "income"},
        headers=HEADERS,
    )
    doc_id = cat.json()["id"]

    r = await client.post(
        f"{BASE}/extraction-schemas",
        json={
            "doc_type_id": doc_id,
            "fields": [
                {"key": "borrower_name", "label": "Borrower",
                 "data_type": "string", "required": True, "min_confidence": 0.85},
            ],
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1


@pytest.mark.asyncio
async def test_patch_extraction_schema_bumps_version(
    client: AsyncClient, lo_app_and_subscription,
):
    cat = await client.post(
        f"{BASE}/doc-types",
        json={"key": "paystub", "name": "Paystub", "category": "income"},
        headers=HEADERS,
    )
    schema = await client.post(
        f"{BASE}/extraction-schemas",
        json={"doc_type_id": cat.json()["id"], "fields": []},
        headers=HEADERS,
    )
    sid = schema.json()["id"]
    assert schema.json()["version"] == 1

    r = await client.patch(
        f"{BASE}/extraction-schemas/{sid}",
        json={"fields": [
            {"key": "x", "label": "X", "data_type": "string"},
        ]},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2


@pytest.mark.asyncio
async def test_create_extraction_schema_rejects_unknown_doc_type(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/extraction-schemas",
        json={"doc_type_id": str(uuid.uuid4()), "fields": []},
        headers=HEADERS,
    )
    assert r.status_code == 404


# ── Org validation rules ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_org_rule(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/validation-rules",
        json={
            "scope": "package", "rule": "must_be_signed",
            "condition": "every stack signed", "severity": "hard",
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_create_org_rule_rejects_duplicate(
    client: AsyncClient, lo_app_and_subscription,
):
    payload = {"scope": "package", "rule": "x", "condition": ""}
    r1 = await client.post(f"{BASE}/validation-rules", json=payload, headers=HEADERS)
    assert r1.status_code == 201
    r2 = await client.post(f"{BASE}/validation-rules", json=payload, headers=HEADERS)
    assert r2.status_code == 409


# ── Program profiles ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_loan_program_profile(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/profiles",
        json={
            "name": "FHA 30yr", "type": "loan_program",
            "checklist": [{"doc_type_key": "paystub", "required": True}],
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_create_loan_program_with_stacks_with_rejected(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/profiles",
        json={
            "name": "Bad", "type": "loan_program",
            "stacks_with": str(uuid.uuid4()),
        },
        headers=HEADERS,
    )
    assert r.status_code == 400
    assert "loan-program" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_investor_overlay_requires_stacks_with(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/profiles",
        json={"name": "Bare overlay", "type": "investor_overlay"},
        headers=HEADERS,
    )
    assert r.status_code == 400
    assert "stacks_with" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_investor_overlay_with_base_program(
    client: AsyncClient, lo_app_and_subscription,
):
    base = await client.post(
        f"{BASE}/profiles",
        json={"name": "Conv 30yr", "type": "loan_program"},
        headers=HEADERS,
    )
    base_id = base.json()["id"]

    r = await client.post(
        f"{BASE}/profiles",
        json={
            "name": "Fannie DU", "type": "investor_overlay",
            "stacks_with": base_id,
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text
    assert r.json()["stacks_with"] == base_id


@pytest.mark.asyncio
async def test_profile_extraction_overrides_lower_confidence_rejected(
    client: AsyncClient, lo_app_and_subscription,
):
    cat = await client.post(
        f"{BASE}/doc-types",
        json={"key": "paystub", "name": "Paystub", "category": "income"},
        headers=HEADERS,
    )
    await client.post(
        f"{BASE}/extraction-schemas",
        json={
            "doc_type_id": cat.json()["id"],
            "fields": [
                {"key": "borrower_name", "label": "Borrower",
                 "data_type": "string", "required": True, "min_confidence": 0.85},
            ],
        },
        headers=HEADERS,
    )
    # Profile tries to LOWER min_confidence — must 400
    r = await client.post(
        f"{BASE}/profiles",
        json={
            "name": "Loose", "type": "loan_program",
            "extraction_overrides": {
                "paystub": {"borrower_name": {"min_confidence": 0.50}},
            },
        },
        headers=HEADERS,
    )
    assert r.status_code == 400
    assert "min_confidence" in r.json()["detail"]


@pytest.mark.asyncio
async def test_profile_extraction_overrides_raise_confidence_accepted(
    client: AsyncClient, lo_app_and_subscription,
):
    cat = await client.post(
        f"{BASE}/doc-types",
        json={"key": "paystub", "name": "Paystub", "category": "income"},
        headers=HEADERS,
    )
    await client.post(
        f"{BASE}/extraction-schemas",
        json={
            "doc_type_id": cat.json()["id"],
            "fields": [
                {"key": "borrower_name", "label": "Borrower",
                 "data_type": "string", "required": False, "min_confidence": 0.50},
            ],
        },
        headers=HEADERS,
    )
    r = await client.post(
        f"{BASE}/profiles",
        json={
            "name": "Strict", "type": "loan_program",
            "extraction_overrides": {
                "paystub": {"borrower_name": {"min_confidence": 0.92}},
            },
        },
        headers=HEADERS,
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_overlay_with_unknown_base_404(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.post(
        f"{BASE}/profiles",
        json={
            "name": "Orphan overlay", "type": "investor_overlay",
            "stacks_with": str(uuid.uuid4()),
        },
        headers=HEADERS,
    )
    assert r.status_code == 404


# ── Global settings ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_global_settings_autocreates_with_defaults(
    client: AsyncClient, lo_app_and_subscription,
):
    r = await client.get(f"{BASE}/global-settings", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()

    # AI Thresholds: single "Auto-Classification Thresholds" section with
    # three prototype rows (Auto-Classify / Review Band Lower Bound /
    # Below Review Band) — descriptions copied verbatim from the
    # LogikIntake HTML prototype.
    ai_sections = body["ai_thresholds"]["sections"]
    assert [s["title"] for s in ai_sections] == [
        "Auto-Classification Thresholds",
    ]
    auto_classify = ai_sections[0]["settings"][0]
    assert auto_classify["label"] == "Auto-Classify Threshold"
    assert auto_classify["value"] == 85
    assert "at or above this confidence" in auto_classify["description"]

    # STP Targets
    assert body["stp_targets"]["title"] == "STP Targets"
    stp_first = body["stp_targets"]["settings"][0]
    assert stp_first["label"] == "Day 1 STP Target"
    assert stp_first["value"] == 80
    assert "complete all stages automatically" in stp_first["description"]

    # Exception Defaults
    exc_settings = body["exception_defaults"]["settings"]
    eod = next(
        s for s in exc_settings if s["key"] == "eod_advisory_flag_behavior"
    )
    assert eod["type"] == "select"
    assert eod["value"].startswith("Hold")

    # Audit & Compliance — events_logged is read-only.
    audit_settings = body["audit"]["settings"]
    events = next(s for s in audit_settings if s["key"] == "events_logged")
    assert events["type"] == "readonly_badge"
    assert events["value"] == "All events — cannot disable"

    # Roles
    assert body["roles"]["title"] == "Role Definitions"
    assert [r["role"] for r in body["roles"]["items"]] == [
        "Operator",
        "Supervisor / QC Lead",
        "Admin",
        "Read-Only",
    ]

    # Notifications
    notify_events = [n["event"] for n in body["notifications"]["items"]]
    assert "File stuck in stage" in notify_events
    assert "Classification failure" in notify_events

    # Integrations
    integrations = body["integrations"]["items"]
    assert any(i["system"] == "LOS Connection" for i in integrations)
    assert any(i["status"] == "Not configured" for i in integrations)

    # Tenant
    tenant_settings = body["tenant"]["settings"]
    org_name = next(s for s in tenant_settings if s["key"] == "organization_name")
    assert org_name["type"] == "text"
    assert isinstance(org_name["value"], str) and len(org_name["value"]) > 0


@pytest.mark.asyncio
async def test_patch_global_settings_section_only_replaces_that_section(
    client: AsyncClient, lo_app_and_subscription,
):
    # First GET to seed defaults.
    initial = (await client.get(f"{BASE}/global-settings", headers=HEADERS)).json()

    # PATCH only STP targets — bump Day-1 to 85%. Other sections must remain intact.
    new_stp = {
        "title": "STP Targets",
        "settings": [
            {
                "key": "day1_stp_target",
                "label": "Day 1 STP Target",
                "description": "% of files that should complete all stages automatically without human intervention on Day 1",
                "type": "percent",
                "value": 85,
            },
            {
                "key": "day60_stp_target",
                "label": "60-Day STP Target",
                "description": "% of files that should reach Decision-Ready within 60 days",
                "type": "percent",
                "value": 92,
            },
        ],
    }
    r = await client.patch(
        f"{BASE}/global-settings",
        json={"stp_targets": new_stp},
        headers=HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stp_targets"]["settings"][0]["value"] == 85
    assert body["stp_targets"]["settings"][1]["value"] == 92
    # Untouched sections unchanged.
    assert body["ai_thresholds"] == initial["ai_thresholds"]
    assert body["exception_defaults"] == initial["exception_defaults"]
    assert body["roles"] == initial["roles"]


@pytest.mark.asyncio
async def test_patch_global_settings_rejects_non_object_section(
    client: AsyncClient, lo_app_and_subscription,
):
    # JSONB sections must be objects; sending a primitive 422s.
    r = await client.patch(
        f"{BASE}/global-settings",
        json={"ai_thresholds": "not-an-object"},
        headers=HEADERS,
    )
    assert r.status_code == 422
