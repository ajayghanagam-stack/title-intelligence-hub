"""Unit tests for the persona-aware compliance rule engine.

Pure-Python tests; no DB, no test client. The engine itself is pure (no I/O),
so these directly assert:
  - LoanContext (de)serialization round-trip
  - validate_loan_context error reporting for unknown enums
  - evaluate_compliance status semantics for ALL / ANY / PROCESS modes
  - `when` predicate filtering (FHA / VA / USDA / NY / TX / streamlines / PIW
    / scenario flags)
  - summarize_compliance counts + open_criticals
  - derive_lo_view closeability tones + deal-killer ordering + borrower asks
  - compute_rule_set_hash determinism + sensitivity
  - Determinism of `evaluate_compliance` output (same inputs → identical
    findings JSONB, byte-for-byte)
"""
from __future__ import annotations

import json

import pytest

from app.micro_apps.loan_onboarding.services import compliance_rules as cr


# ── LoanContext ────────────────────────────────────────────────────────────


def test_loan_context_round_trip_camel_case():
    """from_dict accepts camelCase wire keys; to_dict emits camelCase."""
    raw = {
        "program": "fha",
        "purpose": "purchase",
        "occupancy": "primary",
        "state": "CT",
        "scenarioFlags": ["gift_funds", "first_time"],
        "ausEngine": "du",
        "ausWaivers": ["piw"],
        "loanAmount": 350000.0,
        "propertyValue": 425000.0,
    }
    ctx = cr.LoanContext.from_dict(raw)
    assert ctx.program == "fha"
    assert ctx.scenario_flags == ("first_time", "gift_funds")  # sorted-deduped
    assert ctx.aus_waivers == ("piw",)
    assert ctx.loan_amount == 350000.0
    out = ctx.to_dict()
    # Round-trip on the closed-set fields
    for k in ("program", "purpose", "occupancy", "state", "ausEngine"):
        assert out[k] == raw[k]
    assert sorted(out["scenarioFlags"]) == sorted(raw["scenarioFlags"])
    assert out["ausWaivers"] == raw["ausWaivers"]


def test_loan_context_round_trip_snake_case():
    """from_dict also accepts snake_case keys (defensive — older wire formats)."""
    raw = {
        "program": "conv",
        "scenario_flags": ["self_employed"],
        "aus_engine": "lpa",
        "aus_waivers": ["no_ftax"],
        "loan_amount": 500000,
        "property_value": 600000,
    }
    ctx = cr.LoanContext.from_dict(raw)
    assert ctx.scenario_flags == ("self_employed",)
    assert ctx.aus_engine == "lpa"
    assert ctx.aus_waivers == ("no_ftax",)
    assert ctx.loan_amount == 500000.0


def test_loan_context_defaults_for_empty_input():
    ctx = cr.LoanContext.from_dict({})
    assert ctx.program == "conv"
    assert ctx.purpose == "purchase"
    assert ctx.occupancy == "primary"
    assert ctx.state == "CT"
    assert ctx.scenario_flags == ()
    assert ctx.aus_engine == "du"
    assert ctx.aus_waivers == ()


def test_loan_context_dedupes_and_sorts_flags():
    ctx = cr.LoanContext.from_dict({"scenarioFlags": ["b", "a", "a"]})
    assert ctx.scenario_flags == ("a", "b")


# ── validate_loan_context ──────────────────────────────────────────────────


def test_validate_loan_context_no_errors_for_defaults():
    assert cr.validate_loan_context(cr.LoanContext()) == []


def test_validate_loan_context_reports_unknown_enums():
    ctx = cr.LoanContext(
        program="bogus_program",
        purpose="bogus_purpose",
        occupancy="bogus_occ",
        state="ZZ",
        scenario_flags=("not_a_flag",),
        aus_engine="bogus_aus",
        aus_waivers=("not_a_waiver",),
    )
    errs = cr.validate_loan_context(ctx)
    joined = " | ".join(errs)
    for needle in (
        "Unknown loan program",
        "Unknown loan purpose",
        "Unknown occupancy",
        "Unknown state",
        "Unknown scenario flags",
        "Unknown AUS engine",
        "Unknown AUS waivers",
    ):
        assert needle in joined


# ── evaluate_compliance: requires_mode semantics ───────────────────────────


def _find(findings, rule_id):
    for f in findings:
        if f.id == rule_id:
            return f
    raise AssertionError(f"finding {rule_id!r} not present")


def test_requires_mode_all_compliant_when_all_present():
    # cmp_app_urla: requires=("Form 1003",), mode=ALL
    findings = cr.evaluate_compliance(["Form 1003"], cr.LoanContext())
    assert _find(findings, "cmp_app_urla").status == cr.Status.COMPLIANT.value


def test_requires_mode_all_partial_when_some_present():
    # cmp_fha_amend: requires=("Amendatory Clause", "Real Estate Certification"), mode=ALL
    findings = cr.evaluate_compliance(
        ["Amendatory Clause", "Form 1003"],
        cr.LoanContext(program="fha", purpose="purchase"),
    )
    assert _find(findings, "cmp_fha_amend").status == cr.Status.PARTIAL.value


def test_requires_mode_all_missing_when_none_present():
    findings = cr.evaluate_compliance([], cr.LoanContext())
    assert _find(findings, "cmp_app_urla").status == cr.Status.MISSING.value


def test_requires_mode_any_compliant_when_one_present():
    # cmp_atr_income: requires has 4 options, mode=ANY
    findings = cr.evaluate_compliance(["Paystubs"], cr.LoanContext())
    f = _find(findings, "cmp_atr_income")
    assert f.status == cr.Status.COMPLIANT.value
    assert "Paystubs" in f.matched


def test_requires_mode_any_missing_when_none_present():
    findings = cr.evaluate_compliance(["Title Commitment"], cr.LoanContext())
    assert _find(findings, "cmp_atr_income").status == cr.Status.MISSING.value


def test_requires_mode_process_always_attestation_required():
    # cmp_aml_bsa: requires=(), mode=PROCESS — applies to every scenario
    findings = cr.evaluate_compliance(
        ["Form 1003", "Paystubs", "Credit Report"], cr.LoanContext()
    )
    f = _find(findings, "cmp_aml_bsa")
    assert f.status == cr.Status.ATTESTATION_REQUIRED.value
    assert f.requires_mode == cr.RequiresMode.PROCESS.value


# ── `when` predicate filtering ─────────────────────────────────────────────


def test_fha_only_rules_excluded_for_conventional():
    findings = cr.evaluate_compliance([], cr.LoanContext(program="conv"))
    ids = {f.id for f in findings}
    assert "cmp_fha_case_no" not in ids
    assert "cmp_fha_caivrs" not in ids
    assert "cmp_fha_amend" not in ids


def test_fha_rules_included_for_fha():
    findings = cr.evaluate_compliance(
        [], cr.LoanContext(program="fha", purpose="purchase")
    )
    ids = {f.id for f in findings}
    assert {"cmp_fha_case_no", "cmp_fha_caivrs", "cmp_fha_amend"} <= ids


def test_fha_amend_excluded_for_fha_refi():
    """Amendatory clause is purchase-only."""
    findings = cr.evaluate_compliance(
        [], cr.LoanContext(program="fha", purpose="rt_refi")
    )
    ids = {f.id for f in findings}
    assert "cmp_fha_amend" not in ids


def test_va_rules_filter_correctly():
    pur = cr.evaluate_compliance([], cr.LoanContext(program="va_pur"))
    irrrl = cr.evaluate_compliance([], cr.LoanContext(program="va_irrrl"))
    assert "cmp_va_coe" in {f.id for f in pur}
    assert "cmp_va_nov" in {f.id for f in pur}
    # IRRRL is a streamline — NOV (purchase NOV) only fires for va_pur
    assert "cmp_va_coe" in {f.id for f in irrrl}
    assert "cmp_va_nov" not in {f.id for f in irrrl}


def test_streamline_waives_income_and_appraisal():
    findings = cr.evaluate_compliance(
        [], cr.LoanContext(program="fha_stream")
    )
    ids = {f.id for f in findings}
    assert "cmp_atr_income" not in ids
    assert "cmp_appraisal" not in ids


def test_piw_waives_appraisal():
    findings = cr.evaluate_compliance(
        [], cr.LoanContext(program="conv", aus_waivers=("piw",))
    )
    ids = {f.id for f in findings}
    assert "cmp_appraisal" not in ids


def test_dscr_skips_atr_income():
    """DSCR loans qualify on rents — income docs not required."""
    findings = cr.evaluate_compliance([], cr.LoanContext(program="nonqm_dscr"))
    ids = {f.id for f in findings}
    assert "cmp_atr_income" not in ids
    # but the DSCR-specific lease rule fires
    assert "cmp_dscr_lease" in ids


def test_gift_funds_scenario_adds_gift_letter_rule():
    no_gift = cr.evaluate_compliance([], cr.LoanContext())
    with_gift = cr.evaluate_compliance(
        [], cr.LoanContext(scenario_flags=("gift_funds",))
    )
    assert "cmp_gift_letter" not in {f.id for f in no_gift}
    assert "cmp_gift_letter" in {f.id for f in with_gift}


def test_state_overlay_ny_only_fires_in_ny():
    ny = cr.evaluate_compliance([], cr.LoanContext(state="NY"))
    ct = cr.evaluate_compliance([], cr.LoanContext(state="CT"))
    assert "cmp_state_ny_6l" in {f.id for f in ny}
    assert "cmp_state_ny_6l" not in {f.id for f in ct}


def test_state_overlay_tx_only_fires_for_cashout_in_tx():
    tx_co = cr.evaluate_compliance(
        [], cr.LoanContext(state="TX", purpose="co_refi")
    )
    tx_purchase = cr.evaluate_compliance(
        [], cr.LoanContext(state="TX", purpose="purchase")
    )
    assert "cmp_state_tx_50a6" in {f.id for f in tx_co}
    assert "cmp_state_tx_50a6" not in {f.id for f in tx_purchase}


def test_high_cost_scenario_adds_hoepa():
    findings = cr.evaluate_compliance(
        [], cr.LoanContext(scenario_flags=("high_cost",))
    )
    assert "cmp_hoepa_32" in {f.id for f in findings}


def test_broken_when_predicate_excludes_rule():
    """A predicate raising an exception must not crash evaluation; rule is skipped."""
    bad = cr.ComplianceRule(
        id="cmp_test_broken",
        category="Test",
        regulation="Test",
        requirement="Test",
        requires=("X",),
        requires_mode=cr.RequiresMode.ALL,
        severity=cr.Severity.LOW,
        details="",
        remediation="",
        when=lambda ctx: 1 / 0,  # explodes
    )
    assert cr._rule_applies(bad, cr.LoanContext()) is False


# ── summarize_compliance ───────────────────────────────────────────────────


def test_summarize_counts_by_status_and_collects_open_criticals():
    ctx = cr.LoanContext(program="fha", purpose="purchase")
    # Provide nothing → every applicable rule is missing/attestation_required.
    findings = cr.evaluate_compliance([], ctx)
    summary = cr.summarize_compliance(findings)
    assert summary["total"] == len(findings)
    assert (
        summary["compliant"] + summary["partial"]
        + summary["missing"] + summary["attestation_required"]
    ) == summary["total"]
    # All open criticals must have severity=critical and status != compliant.
    for f in summary["open_criticals"]:
        assert f["severity"] == cr.Severity.CRITICAL.value
        assert f["status"] != cr.Status.COMPLIANT.value
    assert summary["open_criticals_count"] == len(summary["open_criticals"])


def test_summarize_excludes_compliant_criticals_from_open_list():
    findings = cr.evaluate_compliance(
        ["Form 1003", "Paystubs", "Credit Report"], cr.LoanContext()
    )
    summary = cr.summarize_compliance(findings)
    # cmp_app_urla, cmp_atr_income, cmp_credit_pull are now compliant — none of
    # them should be in open_criticals.
    open_ids = {f["id"] for f in summary["open_criticals"]}
    assert "cmp_app_urla" not in open_ids
    assert "cmp_atr_income" not in open_ids
    assert "cmp_credit_pull" not in open_ids


# ── derive_lo_view ─────────────────────────────────────────────────────────


def test_lo_view_yellow_when_few_open_criticals():
    """All doc-driven critical rules satisfied → only PROCESS attestations open (yellow).

    `cmp_aml_bsa` is CRITICAL+PROCESS so it's always `attestation_required`
    (= not compliant); a fully-document-papered conv/purchase scenario lands
    at exactly 1 open critical → yellow tone.
    """
    inv = [
        "Form 1003", "Paystubs", "Credit Report", "Form 1004",
        "Closing Disclosure", "Homeowners Insurance",
    ]
    findings = cr.evaluate_compliance(inv, cr.LoanContext(program="conv"))
    view = cr.derive_lo_view(findings)
    assert view["closeability"]["tone"] == "yellow"
    assert view["closeability"]["open_critical_count"] in (1, 2)


def test_lo_view_red_when_many_open_criticals():
    findings = cr.evaluate_compliance([], cr.LoanContext(program="fha", purpose="purchase"))
    view = cr.derive_lo_view(findings)
    assert view["closeability"]["tone"] == "red"
    assert view["closeability"]["open_critical_count"] >= 3


def test_lo_view_deal_killers_capped_at_three_and_sorted():
    findings = cr.evaluate_compliance([], cr.LoanContext())
    view = cr.derive_lo_view(findings)
    assert len(view["deal_killers"]) <= 3
    sev_order = [
        cr.SEVERITY_ORDER[f["severity"]] for f in view["deal_killers"]
    ]
    assert sev_order == sorted(sev_order)


def test_lo_view_borrower_asks_skip_process_rules():
    """Process rules (no documents) never appear as borrower asks."""
    findings = cr.evaluate_compliance([], cr.LoanContext())
    view = cr.derive_lo_view(findings)
    process_ids = {
        r.id for r in cr.COMPLIANCE_CHECKS
        if r.requires_mode == cr.RequiresMode.PROCESS
    }
    for ask in view["borrower_asks"]:
        assert ask["id"] not in process_ids
        assert ask["docs"]  # must always list at least one doc


# ── compute_rule_set_hash ──────────────────────────────────────────────────


def test_rule_set_hash_is_stable():
    h1 = cr.compute_rule_set_hash()
    h2 = cr.compute_rule_set_hash()
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_rule_set_hash_changes_when_rule_set_mutated():
    """Mutating the in-memory rule list flips the hash; restored after."""
    original = cr.compute_rule_set_hash()
    # Append a synthetic rule, recompute, then pop it back.
    cr.COMPLIANCE_CHECKS.append(cr.ComplianceRule(
        id="cmp_test_mutation_only",
        category="Test", regulation="Test", requirement="Test",
        requires=("X",), requires_mode=cr.RequiresMode.ALL,
        severity=cr.Severity.LOW, details="", remediation="",
    ))
    try:
        mutated = cr.compute_rule_set_hash()
        assert mutated != original
    finally:
        cr.COMPLIANCE_CHECKS.pop()
    assert cr.compute_rule_set_hash() == original


# ── Determinism of evaluate_compliance ─────────────────────────────────────


def test_findings_are_byte_deterministic_across_runs():
    """Same inputs → identical findings JSONB output."""
    inv = ["Form 1003", "Paystubs", "Credit Report", "Form 1004", "Bank Statements"]
    ctx = cr.LoanContext(
        program="fha",
        purpose="purchase",
        state="NY",
        scenario_flags=("gift_funds", "self_employed"),
        aus_waivers=("piw",),  # appraisal still suppressed because PIW
    )
    a = [f.to_dict() for f in cr.evaluate_compliance(inv, ctx)]
    b = [f.to_dict() for f in cr.evaluate_compliance(inv, ctx)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_findings_independent_of_inventory_order():
    """Sets of present docs only — re-ordering must not change findings."""
    ctx = cr.LoanContext()
    a = [f.to_dict() for f in cr.evaluate_compliance(
        ["Form 1003", "Paystubs", "Credit Report"], ctx
    )]
    b = [f.to_dict() for f in cr.evaluate_compliance(
        ["Credit Report", "Paystubs", "Form 1003"], ctx
    )]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_findings_iteration_order_matches_rule_library_order():
    """Findings stream out in COMPLIANCE_CHECKS order (modulo `when` filter)."""
    ctx = cr.LoanContext(program="conv")
    rule_order = [r.id for r in cr.COMPLIANCE_CHECKS if cr._rule_applies(r, ctx)]
    findings = cr.evaluate_compliance([], ctx)
    assert [f.id for f in findings] == rule_order


# ── derive_qc_view ─────────────────────────────────────────────────────────


def test_qc_view_summary_tiles_match_summarize_counts():
    """summary_tiles totals equal summarize_compliance counts."""
    ctx = cr.LoanContext(program="conv")
    findings = cr.evaluate_compliance(["Form 1003", "Paystubs"], ctx)
    summary = cr.summarize_compliance(findings)
    qc = cr.derive_qc_view(findings)
    tiles = qc["summary_tiles"]
    assert tiles["total"] == summary["total"]
    assert tiles["compliant"] == summary["compliant"]
    assert tiles["partial"] == summary["partial"]
    assert tiles["missing"] == summary["missing"]
    assert tiles["attestation_required"] == summary["attestation_required"]
    assert tiles["open_criticals_count"] == summary["open_criticals_count"]


def test_qc_view_open_criticals_only_includes_non_compliant_criticals():
    """A critical that is `compliant` must NOT show up in open_criticals."""
    # cmp_credit_pull is critical + ALL on "Credit Report"; supply it →
    # compliant. cmp_app_urla is critical + ALL on "Form 1003"; omit it →
    # missing. Expect only the URLA finding in open_criticals.
    ctx = cr.LoanContext(program="conv")
    findings = cr.evaluate_compliance(["Credit Report"], ctx)
    qc = cr.derive_qc_view(findings)
    ids = [f["id"] for f in qc["open_criticals"]]
    assert "cmp_credit_pull" not in ids
    assert "cmp_app_urla" in ids


def test_qc_view_groups_findings_by_category():
    """Every finding lands in `by_category[finding.category]`, no leaks."""
    ctx = cr.LoanContext(program="fha", purpose="purchase")
    findings = cr.evaluate_compliance([], ctx)
    qc = cr.derive_qc_view(findings)
    flat = [f["id"] for items in qc["by_category"].values() for f in items]
    assert sorted(flat) == sorted(f.id for f in findings)
    # FHA scenario must produce at least one FHA-program finding.
    assert "FHA Program" in qc["by_category"]


def test_qc_view_within_category_sort_is_severity_then_status_then_id():
    """Findings inside a category are sorted by severity, status, id."""
    ctx = cr.LoanContext(program="fha", purpose="purchase")
    findings = cr.evaluate_compliance([], ctx)
    qc = cr.derive_qc_view(findings)
    for items in qc["by_category"].values():
        keys = [
            (
                cr.SEVERITY_ORDER.get(f["severity"], 9),
                cr.STATUS_WEIGHT.get(f["status"], 9),
                f["id"],
            )
            for f in items
        ]
        assert keys == sorted(keys)


def test_qc_view_is_byte_deterministic():
    """Same findings → byte-identical qc_view JSON."""
    ctx = cr.LoanContext(program="va_pur", state="NY")
    findings = cr.evaluate_compliance(["Form 1003"], ctx)
    a = cr.derive_qc_view(findings)
    b = cr.derive_qc_view(findings)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ── derive_regulations ─────────────────────────────────────────────────────


def test_regulations_returns_one_row_per_unique_category():
    """One row per category present in COMPLIANCE_CHECKS."""
    ctx = cr.LoanContext(program="conv")
    regs = cr.derive_regulations(ctx)
    expected = {r.category for r in cr.COMPLIANCE_CHECKS}
    assert {row["name"] for row in regs} == expected


def test_regulations_fha_category_inapplicable_for_conventional():
    """FHA-only categories are flagged inapplicable on a conventional loan."""
    ctx = cr.LoanContext(program="conv")
    regs = {row["name"]: row for row in cr.derive_regulations(ctx)}
    assert regs["FHA Program"]["applicable"] is False


def test_regulations_fha_category_applicable_for_fha():
    """FHA category becomes applicable when ctx.program is FHA."""
    ctx = cr.LoanContext(program="fha", purpose="purchase")
    regs = {row["name"]: row for row in cr.derive_regulations(ctx)}
    assert regs["FHA Program"]["applicable"] is True


def test_regulations_state_overlay_ny_only_in_ny():
    """NY state overlay only marks State Overlays applicable when state=NY."""
    ct = cr.LoanContext(state="CT")
    ny = cr.LoanContext(state="NY")
    ct_regs = {row["name"]: row for row in cr.derive_regulations(ct)}
    ny_regs = {row["name"]: row for row in cr.derive_regulations(ny)}
    # CT triggers no state overlay rule → State Overlays inapplicable.
    assert ct_regs["State Overlays"]["applicable"] is False
    # NY hits cmp_state_ny_6l → applicable.
    assert ny_regs["State Overlays"]["applicable"] is True


def test_regulations_id_is_stable_slug():
    """`id` is a deterministic snake-case slug of `name`."""
    ctx = cr.LoanContext()
    regs = cr.derive_regulations(ctx)
    by_name = {r["name"]: r for r in regs}
    assert by_name["TRID Disclosures"]["id"] == "trid_disclosures"
    assert by_name["FHA Program"]["id"] == "fha_program"
    assert by_name["Ability-to-Repay (ATR/QM)"]["id"] == "ability_to_repay_atr_qm"


def test_regulations_is_byte_deterministic():
    """Same ctx → byte-identical regulations JSON."""
    ctx = cr.LoanContext(program="fha", state="TX", purpose="co_refi")
    a = cr.derive_regulations(ctx)
    b = cr.derive_regulations(ctx)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ── derive_doc_checks ──────────────────────────────────────────────────────


def _stack(doc_type, *, page_count=1, conf=0.99, status="accepted"):
    return {
        "doc_type": doc_type,
        "page_count": page_count,
        "overall_confidence": conf,
        "status": status,
        "stack_index": 0,
    }


def test_doc_checks_missing_required_lands_first():
    """A missing required doc precedes everything else in the sort order."""
    specs = [
        {"key": "paystub", "label": "Paystubs", "required": False},
        {"key": "urla_1003", "label": "Form 1003", "required": True},
    ]
    rows = cr.derive_doc_checks([], specs, hitl_threshold=0.75)
    assert rows[0]["docKey"] == "urla_1003"
    assert rows[0]["status"] == "missing"
    assert rows[0]["required"] is True
    assert "Required" in rows[0]["notes"][0]


def test_doc_checks_matches_stack_by_key_or_label():
    """Match works whether stack.doc_type is the spec key or the spec label."""
    specs = [
        {"key": "urla_1003", "label": "Form 1003", "required": True},
        {"key": "paystub", "label": "Paystubs", "required": True},
    ]
    rows = cr.derive_doc_checks(
        [_stack("urla_1003"), _stack("Paystubs")],  # one by key, one by label
        specs,
        hitl_threshold=0.75,
    )
    statuses = {r["docKey"]: r["status"] for r in rows}
    assert statuses["urla_1003"] == "ok"
    assert statuses["paystub"] == "ok"


def test_doc_checks_low_confidence_fires_below_threshold():
    """Confidence below threshold (and not yet `accepted`) → low_confidence."""
    specs = [{"key": "paystub", "label": "Paystubs", "required": True}]
    rows = cr.derive_doc_checks(
        [_stack("paystub", conf=0.5, status="validated")],
        specs,
        hitl_threshold=0.75,
    )
    assert rows[0]["status"] == "low_confidence"
    assert any("below" in n for n in rows[0]["notes"])


def test_doc_checks_accepted_overrides_low_confidence():
    """A reviewer-`accepted` stack stays `ok` even if confidence is low."""
    specs = [{"key": "paystub", "label": "Paystubs", "required": True}]
    rows = cr.derive_doc_checks(
        [_stack("paystub", conf=0.4, status="accepted")],
        specs,
        hitl_threshold=0.75,
    )
    assert rows[0]["status"] == "ok"


def test_doc_checks_needs_review_status_propagates():
    """A stack already routed to review surfaces as `needs_review`."""
    specs = [{"key": "paystub", "label": "Paystubs", "required": True}]
    rows = cr.derive_doc_checks(
        [_stack("paystub", conf=0.99, status="needs_review")],
        specs,
        hitl_threshold=0.75,
    )
    assert rows[0]["status"] == "needs_review"


def test_doc_checks_skips_others_bucket():
    """The `Others` reserved bucket is filtered out of doc_checks."""
    specs = [
        {"key": "Others", "label": "Others", "required": False},
        {"key": "urla_1003", "label": "Form 1003", "required": True},
    ]
    rows = cr.derive_doc_checks([], specs, hitl_threshold=0.75)
    assert [r["docKey"] for r in rows] == ["urla_1003"]


def test_doc_checks_required_outranks_optional_at_same_status():
    """Among `missing`, required docs come before optional ones."""
    specs = [
        {"key": "OPT", "label": "Opt", "required": False},
        {"key": "REQ", "label": "Req", "required": True},
    ]
    rows = cr.derive_doc_checks([], specs, hitl_threshold=0.75)
    assert [r["docKey"] for r in rows] == ["REQ", "OPT"]


def test_doc_checks_is_byte_deterministic():
    """Same inputs → byte-identical doc_checks JSON."""
    specs = [
        {"key": "urla_1003", "label": "Form 1003", "required": True},
        {"key": "paystub", "label": "Paystubs", "required": True},
    ]
    stacks = [_stack("urla_1003"), _stack("paystub", conf=0.5, status="validated")]
    a = cr.derive_doc_checks(stacks, specs, hitl_threshold=0.75)
    b = cr.derive_doc_checks(stacks, specs, hitl_threshold=0.75)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ── derive_validation_findings ─────────────────────────────────────────────


def _vr(stack_id, doc_type, *rules, overall_confidence=0.99, requires_hitl=False):
    """Build a flattened validation-result dict for tests."""
    return {
        "stack_id": stack_id,
        "doc_type": doc_type,
        "rules_evaluated": list(rules),
        "overall_confidence": overall_confidence,
        "requires_hitl": requires_hitl,
    }


def _rule(rule_id, *, passed, source="preset", evidence=""):
    return {
        "rule_id": rule_id,
        "rule_source": source,
        "passed": passed,
        "evidence": evidence,
    }


def test_validation_findings_empty_when_no_results():
    assert cr.derive_validation_findings([]) == []


def test_validation_findings_empty_when_all_passed():
    vrs = [_vr("s1", "Form 1003", _rule("missing_signatures", passed=True))]
    assert cr.derive_validation_findings(vrs) == []


def test_validation_findings_emits_one_per_failed_rule():
    vrs = [
        _vr(
            "s1", "Paystubs",
            _rule("missing_signatures", passed=False, evidence="No sig page"),
            _rule("missing_pages", passed=True),
        ),
    ]
    findings = cr.derive_validation_findings(vrs)
    assert len(findings) == 1
    f = findings[0]
    assert f.id == "validation_missing_signatures_s1"
    assert "missing_signatures" in f.requirement
    assert f.severity == cr.Severity.HIGH.value  # missing_signatures → HIGH
    assert f.category == "Package Completeness"
    assert f.status == cr.Status.MISSING.value
    assert f.requires == ("Paystubs",)
    assert f.requires_mode == cr.RequiresMode.PROCESS.value


def test_validation_findings_severity_map_for_presets():
    """missing_signatures + missing_pages → HIGH; missing_fields → MEDIUM."""
    vrs = [
        _vr(
            "s1", "Form 1003",
            _rule("missing_signatures", passed=False),
            _rule("missing_pages", passed=False),
            _rule("missing_fields", passed=False),
        ),
    ]
    findings = cr.derive_validation_findings(vrs)
    by_id = {f.id: f for f in findings}
    assert by_id["validation_missing_signatures_s1"].severity == cr.Severity.HIGH.value
    assert by_id["validation_missing_pages_s1"].severity == cr.Severity.HIGH.value
    assert by_id["validation_missing_fields_s1"].severity == cr.Severity.MEDIUM.value
    assert by_id["validation_missing_fields_s1"].category == "Data Integrity"


def test_validation_findings_custom_rules_get_default_severity():
    vrs = [_vr("s1", "Form 1003", _rule("custom_legal_addr_match", passed=False, source="custom"))]
    f = cr.derive_validation_findings(vrs)[0]
    assert f.severity == cr.Severity.MEDIUM.value
    assert f.category == "Package Completeness"
    assert "custom" in f.details


def test_validation_findings_unknown_preset_uses_default():
    """An unknown preset rule_id still surfaces — falls back to MEDIUM/Completeness."""
    vrs = [_vr("s1", "Form 1003", _rule("brand_new_preset", passed=False))]
    f = cr.derive_validation_findings(vrs)[0]
    assert f.severity == cr.Severity.MEDIUM.value
    assert f.category == "Package Completeness"


def test_validation_findings_skips_others_bucket():
    """Validation rules on the reserved Others bucket don't surface findings."""
    vrs = [_vr("s1", cr.OTHERS_DOC_TYPE_KEY, _rule("missing_signatures", passed=False))]
    assert cr.derive_validation_findings(vrs) == []


def test_validation_findings_separate_per_stack():
    """Multiple stacks failing the same rule each emit a distinct finding."""
    vrs = [
        _vr("s1", "Paystubs", _rule("missing_signatures", passed=False)),
        _vr("s2", "W-2", _rule("missing_signatures", passed=False)),
    ]
    findings = cr.derive_validation_findings(vrs)
    ids = sorted(f.id for f in findings)
    assert ids == [
        "validation_missing_signatures_s1",
        "validation_missing_signatures_s2",
    ]


def test_validation_findings_byte_deterministic():
    vrs = [
        _vr("s2", "W-2", _rule("missing_pages", passed=False, evidence="x")),
        _vr("s1", "Paystubs", _rule("missing_fields", passed=False)),
    ]
    a = [f.to_dict() for f in cr.derive_validation_findings(vrs)]
    b = [f.to_dict() for f in cr.derive_validation_findings(vrs)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_validation_findings_independent_of_input_order():
    """Re-ordering the validation_results list does not change findings JSON."""
    a_in = [
        _vr("s1", "Paystubs", _rule("missing_fields", passed=False)),
        _vr("s2", "W-2", _rule("missing_pages", passed=False)),
    ]
    b_in = list(reversed(a_in))
    a = [f.to_dict() for f in cr.derive_validation_findings(a_in)]
    b = [f.to_dict() for f in cr.derive_validation_findings(b_in)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ── derive_low_conf_stack_findings ─────────────────────────────────────────


def _stack_lc(
    stack_id, doc_type, conf, *,
    status="validated", stack_index=0,
):
    return {
        "stack_id": stack_id,
        "doc_type": doc_type,
        "overall_confidence": conf,
        "status": status,
        "stack_index": stack_index,
        "page_count": 1,
    }


def test_lowconf_findings_empty_when_all_above_threshold():
    stacks = [_stack_lc("s1", "Paystubs", 0.9), _stack_lc("s2", "W-2", 0.99)]
    assert cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75) == []


def test_lowconf_findings_emit_one_per_stack_below_threshold():
    stacks = [
        _stack_lc("s1", "Paystubs", 0.5, stack_index=0),
        _stack_lc("s2", "W-2", 0.99, stack_index=1),
        _stack_lc("s3", "Form 1003", 0.4, stack_index=2),
    ]
    findings = cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75)
    assert [f.id for f in findings] == ["lowconf_s1", "lowconf_s3"]
    assert all(f.severity == cr.Severity.MEDIUM.value for f in findings)
    assert all(f.status == cr.Status.MISSING.value for f in findings)
    assert all(f.requires_mode == cr.RequiresMode.PROCESS.value for f in findings)


def test_lowconf_findings_skip_accepted_stacks():
    """Reviewer-accepted stacks are final — no low-conf finding even if conf<threshold."""
    stacks = [_stack_lc("s1", "Paystubs", 0.4, status="accepted")]
    assert cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75) == []


def test_lowconf_findings_skip_others_bucket():
    stacks = [_stack_lc("s1", cr.OTHERS_DOC_TYPE_KEY, 0.0)]
    assert cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75) == []


def test_lowconf_findings_threshold_is_inclusive_floor():
    """A stack at exactly the threshold passes (conf >= threshold)."""
    stacks = [_stack_lc("s1", "Paystubs", 0.75)]
    assert cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75) == []


def test_lowconf_findings_details_quote_threshold_and_value():
    stacks = [_stack_lc("s1", "Paystubs", 0.6)]
    f = cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75)[0]
    assert "60%" in f.details
    assert "75%" in f.details
    assert "Paystubs" in f.details


def test_lowconf_findings_byte_deterministic():
    stacks = [
        _stack_lc("s2", "W-2", 0.4, stack_index=1),
        _stack_lc("s1", "Paystubs", 0.5, stack_index=0),
    ]
    a = [f.to_dict() for f in cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75)]
    b = [f.to_dict() for f in cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_lowconf_findings_handles_missing_overall_confidence():
    """A None overall_confidence is treated as 0 → falls below any positive threshold."""
    stacks = [{
        "stack_id": "s1", "doc_type": "Paystubs",
        "overall_confidence": None, "status": "validated", "stack_index": 0,
    }]
    findings = cr.derive_low_conf_stack_findings(stacks, hitl_threshold=0.75)
    assert len(findings) == 1
    assert findings[0].id == "lowconf_s1"


# ── Advisory rules (v2) ────────────────────────────────────────────────────


_ADVISORY_IDS = {
    "cmp_advisory_le_timing",
    "cmp_advisory_cd_3day",
    "cmp_advisory_privacy_ack",
    "cmp_advisory_adverse_action_timing",
    "cmp_advisory_ecoa_valuations",
}


# Phase A rules added in v3 — Origination audit gaps from PM list.
_PHASE_A_IDS = {
    "cmp_udaap_review",
    "cmp_fair_housing_act",
    "cmp_pre_funding_qc",
    "cmp_loan_file_documentation",
    "cmp_fnma_loan_quality",
    "cmp_fhlmc_loan_quality",
    "cmp_repurchase_risk",
    "cmp_respa_afba",
    "cmp_respa_servicing_transfer",
    "cmp_tila_rescission",
    "cmp_hmda_lar_completeness",
    "cmp_ecoa_incompleteness",
    "cmp_ecoa_joint_intent",
    "cmp_trid_tolerances",
}


def test_rules_version_bumped_to_v3():
    assert cr.RULES_VERSION == "lo_compliance_rules_v3"


def test_severity_info_in_order_table():
    """SEVERITY_ORDER must contain INFO at the lowest priority slot."""
    assert cr.Severity.INFO.value == "info"
    assert cr.SEVERITY_ORDER["info"] == 4
    # All real severities are ranked.
    assert set(cr.SEVERITY_ORDER) == {"critical", "high", "medium", "low", "info"}


def test_advisory_rules_present_in_library():
    """All five advisory rules registered in the rule library."""
    ids = {r.id for r in cr.COMPLIANCE_CHECKS}
    assert _ADVISORY_IDS <= ids


def test_advisory_rules_are_info_severity_and_process_mode():
    advisories = [r for r in cr.COMPLIANCE_CHECKS if r.id in _ADVISORY_IDS]
    assert len(advisories) == 5
    for r in advisories:
        assert r.severity == cr.Severity.INFO
        assert r.requires_mode == cr.RequiresMode.PROCESS
        assert r.requires == ()


def test_advisory_findings_status_is_attestation_required():
    """Advisories evaluate to attestation_required (mode=PROCESS, no docs)."""
    findings = cr.evaluate_compliance(
        ["Form 1003", "Paystubs", "Credit Report"], cr.LoanContext()
    )
    by_id = {f.id: f for f in findings}
    for adv_id in _ADVISORY_IDS - {"cmp_advisory_ecoa_valuations"}:
        assert by_id[adv_id].status == cr.Status.ATTESTATION_REQUIRED.value
        assert by_id[adv_id].severity == "info"


def test_advisory_ecoa_valuations_skips_when_appraisal_waived():
    """ECOA Valuations advisory is suppressed for streamlines / PIW (no appraisal)."""
    streamline = cr.evaluate_compliance([], cr.LoanContext(program="va_irrrl"))
    piw = cr.evaluate_compliance(
        [], cr.LoanContext(program="conv", aus_waivers=("piw",))
    )
    assert "cmp_advisory_ecoa_valuations" not in {f.id for f in streamline}
    assert "cmp_advisory_ecoa_valuations" not in {f.id for f in piw}
    # But fires on a vanilla conv purchase.
    plain = cr.evaluate_compliance([], cr.LoanContext(program="conv"))
    assert "cmp_advisory_ecoa_valuations" in {f.id for f in plain}


def test_advisory_findings_dont_count_toward_open_criticals():
    """Adding 5 advisories (severity=info) leaves open_critical_count unchanged."""
    inv = ["Form 1003", "Paystubs", "Credit Report", "Form 1004",
           "Closing Disclosure", "Homeowners Insurance"]
    findings = cr.evaluate_compliance(inv, cr.LoanContext(program="conv"))
    summary = cr.summarize_compliance(findings)
    # No advisory should appear in open_criticals (they're info, not critical).
    open_ids = {f["id"] for f in summary["open_criticals"]}
    assert _ADVISORY_IDS.isdisjoint(open_ids)


def test_advisory_findings_excluded_from_lo_view_deal_killers():
    """Deal killers cap at 3 + sort by severity — advisories rank lowest."""
    findings = cr.evaluate_compliance(
        [], cr.LoanContext(program="fha", purpose="purchase")
    )
    view = cr.derive_lo_view(findings)
    deal_killer_ids = {f["id"] for f in view["deal_killers"]}
    assert _ADVISORY_IDS.isdisjoint(deal_killer_ids)


def test_advisory_findings_excluded_from_lo_view_borrower_asks():
    """Borrower asks need missing_docs — advisories never have any."""
    findings = cr.evaluate_compliance([], cr.LoanContext(program="conv"))
    view = cr.derive_lo_view(findings)
    ask_ids = {a["id"] for a in view["borrower_asks"]}
    assert _ADVISORY_IDS.isdisjoint(ask_ids)


def test_advisory_findings_appear_in_qc_view_by_category():
    """QC view groups by category — advisories should be visible there."""
    findings = cr.evaluate_compliance([], cr.LoanContext(program="conv"))
    qc = cr.derive_qc_view(findings)
    flat_ids = {f["id"] for items in qc["by_category"].values() for f in items}
    assert _ADVISORY_IDS - {"cmp_advisory_ecoa_valuations"} <= flat_ids
    # ECOA Valuations advisory is also present (conv is not streamline / no PIW).
    assert "cmp_advisory_ecoa_valuations" in flat_ids


def test_current_rule_set_hash_differs_from_v1_payload():
    """Adding rules + bumping version flips the rule_set_hash content fingerprint.

    Simulates the v1 baseline by transiently removing every rule added after
    v1 (advisories from v2 + Phase A rules from v3) and reverting the version
    string. The current hash must differ from that simulated v1 hash.
    """
    current_hash = cr.compute_rule_set_hash()
    post_v1_rules = [
        r for r in cr.COMPLIANCE_CHECKS
        if r.id in _ADVISORY_IDS or r.id in _PHASE_A_IDS
    ]
    for r in post_v1_rules:
        cr.COMPLIANCE_CHECKS.remove(r)
    original_version = cr.RULES_VERSION
    cr.RULES_VERSION = "lo_compliance_rules_v1"
    try:
        v1_hash = cr.compute_rule_set_hash()
    finally:
        cr.RULES_VERSION = original_version
        cr.COMPLIANCE_CHECKS.extend(post_v1_rules)
    assert v1_hash != current_hash


# ── Phase A rules (v3) ─────────────────────────────────────────────────────


def test_phase_a_rules_registered():
    """All Phase A rule IDs present in the live rule library."""
    ids = {r.id for r in cr.COMPLIANCE_CHECKS}
    assert _PHASE_A_IDS <= ids


def test_phase_a_rules_are_advisory_shape():
    """Phase A rules are INFO + PROCESS + empty requires (advisory contract)."""
    rules = [r for r in cr.COMPLIANCE_CHECKS if r.id in _PHASE_A_IDS]
    assert len(rules) == len(_PHASE_A_IDS)
    for r in rules:
        assert r.severity == cr.Severity.INFO, r.id
        assert r.requires_mode == cr.RequiresMode.PROCESS, r.id
        assert r.requires == (), r.id


def test_phase_a_rules_dont_inflate_open_criticals():
    """Adding 14 advisories (severity=info) leaves open_critical_count unchanged."""
    inv = ["Form 1003", "Paystubs", "Credit Report", "Form 1004",
           "Closing Disclosure", "Homeowners Insurance"]
    findings = cr.evaluate_compliance(inv, cr.LoanContext(program="conv"))
    summary = cr.summarize_compliance(findings)
    open_ids = {f["id"] for f in summary["open_criticals"]}
    assert _PHASE_A_IDS.isdisjoint(open_ids)


def test_fnma_loan_quality_only_when_du_engine():
    du = cr.evaluate_compliance([], cr.LoanContext(aus_engine="du"))
    lpa = cr.evaluate_compliance([], cr.LoanContext(aus_engine="lpa"))
    manual = cr.evaluate_compliance([], cr.LoanContext(aus_engine="manual"))
    assert "cmp_fnma_loan_quality" in {f.id for f in du}
    assert "cmp_fnma_loan_quality" not in {f.id for f in lpa}
    assert "cmp_fnma_loan_quality" not in {f.id for f in manual}


def test_fhlmc_loan_quality_only_when_lpa_engine():
    du = cr.evaluate_compliance([], cr.LoanContext(aus_engine="du"))
    lpa = cr.evaluate_compliance([], cr.LoanContext(aus_engine="lpa"))
    assert "cmp_fhlmc_loan_quality" not in {f.id for f in du}
    assert "cmp_fhlmc_loan_quality" in {f.id for f in lpa}


def test_repurchase_risk_skips_nonqm():
    """Non-QM/DSCR programs don't carry agency rep-and-warrant exposure."""
    nonqm_bs = cr.evaluate_compliance([], cr.LoanContext(program="nonqm_bs"))
    nonqm_dscr = cr.evaluate_compliance([], cr.LoanContext(program="nonqm_dscr"))
    jumbo = cr.evaluate_compliance([], cr.LoanContext(program="jumbo"))
    conv = cr.evaluate_compliance([], cr.LoanContext(program="conv"))
    fha = cr.evaluate_compliance([], cr.LoanContext(program="fha"))
    assert "cmp_repurchase_risk" not in {f.id for f in nonqm_bs}
    assert "cmp_repurchase_risk" not in {f.id for f in nonqm_dscr}
    assert "cmp_repurchase_risk" not in {f.id for f in jumbo}
    assert "cmp_repurchase_risk" in {f.id for f in conv}
    assert "cmp_repurchase_risk" in {f.id for f in fha}


def test_tila_rescission_only_for_refi_on_primary():
    """Right of rescission applies only to non-purchase loans on principal dwelling."""
    purchase = cr.evaluate_compliance(
        [], cr.LoanContext(purpose="purchase", occupancy="primary")
    )
    rt_refi_primary = cr.evaluate_compliance(
        [], cr.LoanContext(purpose="rt_refi", occupancy="primary")
    )
    co_refi_primary = cr.evaluate_compliance(
        [], cr.LoanContext(purpose="co_refi", occupancy="primary")
    )
    refi_second = cr.evaluate_compliance(
        [], cr.LoanContext(purpose="rt_refi", occupancy="second")
    )
    refi_investment = cr.evaluate_compliance(
        [], cr.LoanContext(purpose="co_refi", occupancy="investment")
    )
    assert "cmp_tila_rescission" not in {f.id for f in purchase}
    assert "cmp_tila_rescission" in {f.id for f in rt_refi_primary}
    assert "cmp_tila_rescission" in {f.id for f in co_refi_primary}
    assert "cmp_tila_rescission" not in {f.id for f in refi_second}
    assert "cmp_tila_rescission" not in {f.id for f in refi_investment}


def test_ecoa_joint_intent_only_when_co_borrower_flag():
    """Joint-intent rule fires only when scenario_flags includes co_borrower."""
    no_co = cr.evaluate_compliance([], cr.LoanContext())
    with_co = cr.evaluate_compliance(
        [], cr.LoanContext(scenario_flags=("co_borrower",))
    )
    assert "cmp_ecoa_joint_intent" not in {f.id for f in no_co}
    assert "cmp_ecoa_joint_intent" in {f.id for f in with_co}
