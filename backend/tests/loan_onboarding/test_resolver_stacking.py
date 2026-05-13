"""Unit tests for the pure-CPU resolver stacking helpers.

Targets ``services/_resolver_stacking.py``. Uses ``SimpleNamespace``
stand-ins for the SQLAlchemy ORM rows — the helpers only read attribute
values, so we avoid the ORM/session boot just to assert merge semantics.

The four functions under test:
  - ``stack_doc_types`` — Global → program → overlay → loan
  - ``stack_schemas``   — Global field rows + profile overrides
  - ``stack_rules``     — Org library + profile + per-loan rule rows
  - ``compute_config_hash`` — deterministic SHA-256 over the resolved tuples
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.micro_apps.loan_onboarding.services._resolver_stacking import (
    compute_config_hash,
    stack_doc_types,
    stack_rules,
    stack_schemas,
)


# ── Helpers to build fake rows ────────────────────────────────────────


def _catalog_row(
    *,
    key: str,
    name: str | None = None,
    category: str = "income",
    auto_classify_enabled: bool = True,
    expected_min_pages: int | None = None,
    expected_max_pages: int | None = None,
    id: uuid.UUID | None = None,
):
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        key=key,
        name=name or key.title(),
        category=category,
        auto_classify_enabled=auto_classify_enabled,
        expected_min_pages=expected_min_pages,
        expected_max_pages=expected_max_pages,
    )


def _profile(
    *,
    type_: str = "loan_program",
    checklist: list | None = None,
    extraction_overrides: dict | None = None,
    rule_overrides: list | None = None,
    id: uuid.UUID | None = None,
):
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        type=type_,
        checklist=checklist or [],
        extraction_overrides=extraction_overrides or {},
        rule_overrides=rule_overrides or [],
    )


def _loan_doc_cfg(doc_types: list[dict] | None):
    return SimpleNamespace(doc_types=doc_types or [])


def _schema_row(*, doc_type_id: uuid.UUID, fields: list[dict], version: int = 1):
    return SimpleNamespace(doc_type_id=doc_type_id, fields=fields, version=version)


def _org_rule(*, scope: str, rule: str, condition: str = "",
              preset_id: str | None = None, severity: str = "hard"):
    return SimpleNamespace(
        scope=scope, rule=rule, condition=condition,
        preset_id=preset_id, severity=severity,
    )


def _loan_rule(*, rule_id: str, doc_type: str | None = None,
               description: str = "", rule_source: str = "custom"):
    return SimpleNamespace(
        rule_id=rule_id, doc_type=doc_type,
        description=description, rule_source=rule_source,
    )


# ── stack_doc_types ───────────────────────────────────────────────────


def test_stack_doc_types_global_only():
    catalog = [
        _catalog_row(key="paystub", name="Paystub", category="income"),
        _catalog_row(key="w2", name="W-2", category="income"),
    ]
    out = stack_doc_types(catalog, None, None, None)
    assert [d.key for d in out] == ["paystub", "w2"]
    # Default required=False everywhere — the catalog itself doesn't set it
    assert all(d.required is False for d in out)


def test_stack_doc_types_required_first_then_alphabetical():
    catalog = [
        _catalog_row(key="zeta"),
        _catalog_row(key="alpha"),
        _catalog_row(key="beta"),
    ]
    program = _profile(checklist=[
        {"doc_type_key": "zeta", "required": True},
        {"doc_type_key": "alpha", "required": False},  # leaves alpha optional
    ])
    out = stack_doc_types(catalog, program, None, None)
    # required first (alphabetical within bucket), then optional (alpha)
    assert [d.key for d in out] == ["zeta", "alpha", "beta"]
    assert out[0].required is True
    assert out[1].required is False


def test_stack_doc_types_overlay_can_promote_to_required():
    catalog = [_catalog_row(key="paystub")]
    program = _profile()  # no checklist
    overlay = _profile(
        type_="investor_overlay",
        checklist=[{"doc_type_key": "paystub", "required": True}],
    )
    out = stack_doc_types(catalog, program, overlay, None)
    assert out[0].required is True


def test_stack_doc_types_loan_layer_can_promote_but_not_demote():
    catalog = [_catalog_row(key="paystub")]
    program = _profile(checklist=[{"doc_type_key": "paystub", "required": True}])
    # Loan-layer entry tries to demote — resolver ignores it (tighten-only).
    loan_cfg = _loan_doc_cfg([{"key": "paystub", "required": False}])
    out = stack_doc_types(catalog, program, None, loan_cfg)
    assert out[0].required is True


def test_stack_doc_types_unknown_keys_dropped():
    """Profile-level keys that don't exist in the org catalog are skipped."""
    catalog = [_catalog_row(key="paystub")]
    program = _profile(checklist=[{"doc_type_key": "phantom", "required": True}])
    out = stack_doc_types(catalog, program, None, None)
    assert [d.key for d in out] == ["paystub"]


def test_stack_doc_types_min_max_pages_overridden_by_profile():
    catalog = [_catalog_row(
        key="paystub", expected_min_pages=1, expected_max_pages=2,
    )]
    program = _profile(checklist=[{
        "doc_type_key": "paystub",
        "required": True,
        "expected_min_pages": 2,
        "expected_max_pages": 4,
    }])
    out = stack_doc_types(catalog, program, None, None)
    assert out[0].expected_min_pages == 2
    assert out[0].expected_max_pages == 4


# ── stack_schemas ─────────────────────────────────────────────────────


def test_stack_schemas_global_only():
    paystub = _catalog_row(key="paystub")
    schema = _schema_row(
        doc_type_id=paystub.id,
        fields=[
            {"key": "borrower_name", "label": "Borrower",
             "data_type": "string", "required": True, "min_confidence": 0.85},
            {"key": "ytd_gross", "label": "YTD Gross",
             "data_type": "currency", "required": False, "min_confidence": 0.0},
        ],
    )
    out = stack_schemas([paystub], [schema], None, None)
    assert len(out) == 1
    assert out[0].doc_type_key == "paystub"
    # Fields sorted by key — borrower_name comes before ytd_gross
    assert [f.key for f in out[0].fields] == ["borrower_name", "ytd_gross"]
    assert out[0].fields[0].required is True
    assert out[0].fields[0].min_confidence == 0.85


def test_stack_schemas_profile_can_only_tighten_min_confidence():
    paystub = _catalog_row(key="paystub")
    schema = _schema_row(
        doc_type_id=paystub.id,
        fields=[
            {"key": "borrower_name", "label": "Borrower",
             "data_type": "string", "required": False, "min_confidence": 0.50},
        ],
    )
    # Tighten: 0.50 → 0.92 should win
    program = _profile(extraction_overrides={
        "paystub": {"borrower_name": {"min_confidence": 0.92, "required": True}},
    })
    out = stack_schemas([paystub], [schema], program, None)
    f = out[0].fields[0]
    assert f.min_confidence == 0.92
    assert f.required is True

    # Loosen attempt: 0.50 → 0.10 should be ignored (max wins)
    program_loosen = _profile(extraction_overrides={
        "paystub": {"borrower_name": {"min_confidence": 0.10}},
    })
    out2 = stack_schemas([paystub], [schema], program_loosen, None)
    assert out2[0].fields[0].min_confidence == 0.50


def test_stack_schemas_profile_adds_new_field():
    paystub = _catalog_row(key="paystub")
    schema = _schema_row(
        doc_type_id=paystub.id,
        fields=[{"key": "borrower_name", "label": "Borrower",
                 "data_type": "string", "required": True, "min_confidence": 0.85}],
    )
    program = _profile(extraction_overrides={
        "paystub": {
            "ytd_gross": {
                "label": "YTD Gross", "data_type": "currency",
                "required": True, "min_confidence": 0.80,
            },
        },
    })
    out = stack_schemas([paystub], [schema], program, None)
    field_keys = [f.key for f in out[0].fields]
    assert "ytd_gross" in field_keys


def test_stack_schemas_orphan_schema_row_skipped():
    """A schema row whose doc_type_id is not in the catalog is dropped."""
    schema = _schema_row(doc_type_id=uuid.uuid4(), fields=[
        {"key": "x", "label": "X", "data_type": "string"},
    ])
    out = stack_schemas([], [schema], None, None)
    assert out == ()


# ── stack_rules ───────────────────────────────────────────────────────


def test_stack_rules_global_then_loan():
    org_rule = _org_rule(scope="package", rule="signed", severity="hard")
    loan_rule = _loan_rule(rule_id="custom_one", description="must be notarized")
    out = stack_rules([org_rule], None, None, [loan_rule])
    assert len(out) == 2
    # Sorted by (layer, scope, rule)
    assert out[0].layer == "global"
    assert out[1].layer == "loan"
    assert out[1].scope == "package"
    assert out[1].rule == "custom_one"


def test_stack_rules_dedup_by_scope_and_rule():
    org_rule = _org_rule(scope="package", rule="signed")
    program = _profile(rule_overrides=[
        {"scope": "package", "rule": "signed",
         "condition": "duplicate", "severity": "hard"},
    ])
    out = stack_rules([org_rule], program, None, [])
    assert len(out) == 1
    # Org wins (higher precedence)
    assert out[0].layer == "global"


def test_stack_rules_layer_ordering():
    out = stack_rules(
        [_org_rule(scope="package", rule="org_a")],
        _profile(rule_overrides=[
            {"scope": "package", "rule": "lp_a", "severity": "hard"},
        ]),
        _profile(
            type_="investor_overlay",
            rule_overrides=[{"scope": "package", "rule": "io_a", "severity": "hard"}],
        ),
        [_loan_rule(rule_id="loan_a")],
    )
    assert [r.layer for r in out] == [
        "global", "loan_program", "investor_overlay", "loan",
    ]


def test_stack_rules_loan_doc_type_scope_prefixed():
    rule = _loan_rule(rule_id="check_yt", doc_type="paystub")
    out = stack_rules([], None, None, [rule])
    assert out[0].scope == "doc_type:paystub"


# ── compute_config_hash ───────────────────────────────────────────────


def test_compute_config_hash_is_deterministic():
    catalog = [_catalog_row(key="paystub")]
    out_a = stack_doc_types(catalog, None, None, None)
    out_b = stack_doc_types(catalog, None, None, None)

    h1 = compute_config_hash(
        doc_types=out_a, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="lo_grounding_v2",
    )
    h2 = compute_config_hash(
        doc_types=out_b, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="lo_grounding_v2",
    )
    assert h1 == h2
    # SHA-256 hex
    assert len(h1) == 64


def test_compute_config_hash_changes_on_grounding_version_bump():
    catalog = [_catalog_row(key="paystub")]
    doc_types = stack_doc_types(catalog, None, None, None)

    h_v2 = compute_config_hash(
        doc_types=doc_types, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="lo_grounding_v2",
    )
    h_v3 = compute_config_hash(
        doc_types=doc_types, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="lo_grounding_v3",
    )
    assert h_v2 != h_v3


def test_compute_config_hash_changes_on_doc_type_required_flip():
    catalog = [_catalog_row(key="paystub")]
    program_optional = _profile(checklist=[
        {"doc_type_key": "paystub", "required": False},
    ])
    program_required = _profile(checklist=[
        {"doc_type_key": "paystub", "required": True},
    ])
    a = stack_doc_types(catalog, program_optional, None, None)
    b = stack_doc_types(catalog, program_required, None, None)

    h_a = compute_config_hash(
        doc_types=a, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="v2",
    )
    h_b = compute_config_hash(
        doc_types=b, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="v2",
    )
    assert h_a != h_b


def test_compute_config_hash_changes_on_profile_id():
    catalog = [_catalog_row(key="paystub")]
    doc_types = stack_doc_types(catalog, None, None, None)
    pid = uuid.uuid4()

    h_a = compute_config_hash(
        doc_types=doc_types, schemas=(), rules=(),
        program_profile_id=None, investor_overlay_id=None,
        grounding_contract_version="v2",
    )
    h_b = compute_config_hash(
        doc_types=doc_types, schemas=(), rules=(),
        program_profile_id=pid, investor_overlay_id=None,
        grounding_contract_version="v2",
    )
    assert h_a != h_b
