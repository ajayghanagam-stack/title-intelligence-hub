"""Persona-aware compliance rule engine for Loan Onboarding.

Pure Python — no LLM, no I/O. One deterministic rule library, evaluated against
the document types present on a package and the captured loan context (program,
purpose, occupancy, state, scenario flags, AUS engine + waivers).

`RULES_VERSION` must be bumped whenever any rule's identity, severity, requires
list, requiresMode, or `when` predicate logic changes. The rule_set_hash is a
content fingerprint over every rule's static fields plus the IDs of rules that
declare a `when` predicate; combined with `RULES_VERSION` this is what feeds
into `LOComplianceRun.rule_set_hash` for byte-deterministic re-runs.

Source-of-truth prototype: /private/tmp/claude/claude/loan-onboarding-preview/
src/LoanOnboarding.jsx (lines 380-823 + 3389-3441).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable

# ── Versioning ─────────────────────────────────────────────────────────────

RULES_VERSION = "lo_compliance_rules_v3"
# v3: Phase A — Origination audit gaps from PM list. Adds 14 rules covering
#     UDAAP, Fair Housing Act, Pre-Funding QC, Loan File Doc Audit, Fannie/
#     Freddie Loan Quality, Repurchase/Buyback Risk, RESPA AfBA + Servicing
#     Transfer + Initial Escrow, TILA Right of Rescission, HMDA LAR
#     completeness, ECOA Notice of Incompleteness + Joint Intent, and TRID
#     fee-tolerance buckets. All Phase A rules are advisory (Severity.INFO +
#     RequiresMode.PROCESS) — they don't change closeability arithmetic; they
#     surface as `attestation_required` so QC/LO must check off the procedural
#     item. New categories introduced: "UDAAP", "Fair Lending & Fair Housing",
#     "Loan Quality & QC", "RESPA Disclosures".
# v2: added Severity.INFO + 5 advisory rules (LE timing, CD 3-day, Privacy
#     notice ack, Adverse Action timing, ECOA Valuations 3-day delivery).
# v1: initial port of prototype COMPLIANCE_CHECKS.


# ── Closed-set enums ───────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    # Advisory: rule is informational ("present-but-verify"). Doesn't count
    # toward closeability open_critical_count, doesn't appear in deal_killers.
    INFO = "info"


class Status(str, Enum):
    COMPLIANT = "compliant"
    PARTIAL = "partial"
    MISSING = "missing"
    ATTESTATION_REQUIRED = "attestation_required"


class RequiresMode(str, Enum):
    ALL = "all"
    ANY = "any"
    PROCESS = "process"


SEVERITY_ORDER: dict[str, int] = {
    Severity.CRITICAL.value: 0,
    Severity.HIGH.value: 1,
    Severity.MEDIUM.value: 2,
    Severity.LOW.value: 3,
    Severity.INFO.value: 4,
}

STATUS_WEIGHT: dict[str, int] = {
    Status.MISSING.value: 0,
    Status.PARTIAL.value: 1,
    Status.ATTESTATION_REQUIRED.value: 2,
    Status.COMPLIANT.value: 3,
}

STATUS_LABEL: dict[str, str] = {
    Status.COMPLIANT.value: "Compliant",
    Status.PARTIAL.value: "Partial",
    Status.MISSING.value: "Missing",
    Status.ATTESTATION_REQUIRED.value: "Attestation required",
}


# ── Loan-context vocabularies (mirror prototype lines 380-430) ─────────────

LOAN_PROGRAMS: list[dict[str, str]] = [
    {"id": "conv",       "label": "Conventional Conforming",     "group": "Conventional"},
    {"id": "conv_hb",    "label": "Conventional High-Balance",   "group": "Conventional"},
    {"id": "fha",        "label": "FHA 203(b)",                  "group": "Government"},
    {"id": "fha_203k",   "label": "FHA 203(k) Renovation",       "group": "Government"},
    {"id": "fha_stream", "label": "FHA Streamline Refinance",    "group": "Government"},
    {"id": "va_pur",     "label": "VA Purchase / Cash-Out",      "group": "Government"},
    {"id": "va_irrrl",   "label": "VA IRRRL (Streamline)",       "group": "Government"},
    {"id": "usda",       "label": "USDA Section 502 Guaranteed", "group": "Government"},
    {"id": "jumbo",      "label": "Jumbo Prime",                 "group": "Jumbo"},
    {"id": "nonqm_bs",   "label": "Non-QM Bank Statement",       "group": "Non-QM"},
    {"id": "nonqm_dscr", "label": "Non-QM DSCR (Investment)",    "group": "Non-QM"},
]

LOAN_PURPOSES: list[dict[str, str]] = [
    {"id": "purchase", "label": "Purchase"},
    {"id": "rt_refi",  "label": "Rate-and-Term Refinance"},
    {"id": "co_refi",  "label": "Cash-Out Refinance"},
    {"id": "c2p",      "label": "Construction-to-Perm"},
]

OCCUPANCY_TYPES: list[dict[str, str]] = [
    {"id": "primary",    "label": "Primary residence"},
    {"id": "second",     "label": "Second home"},
    {"id": "investment", "label": "Investment property"},
]

SCENARIO_FLAGS: list[dict[str, str]] = [
    {"id": "self_employed", "label": "Self-employed"},
    {"id": "gift_funds",    "label": "Gift funds"},
    {"id": "rental_income", "label": "Rental income used to qualify"},
    {"id": "co_borrower",   "label": "Co-borrower on loan"},
    {"id": "first_time",    "label": "First-time homebuyer"},
    {"id": "high_cost",     "label": "High-cost APR (HOEPA §32 territory)"},
]

AUS_ENGINES: list[dict[str, str]] = [
    {"id": "du",     "label": "Fannie Mae DU"},
    {"id": "lpa",    "label": "Freddie Mac LPA"},
    {"id": "gus",    "label": "USDA GUS"},
    {"id": "manual", "label": "Manual underwrite"},
]

AUS_WAIVER_OPTIONS: list[dict[str, str]] = [
    {"id": "piw",     "label": "PIW / Appraisal waiver"},
    {"id": "no_ftax", "label": "Tax transcript (4506-C) waiver"},
    {"id": "asset_v", "label": "Asset verification waiver"},
]

US_STATES: list[str] = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY",
]

_PROGRAM_IDS = {p["id"] for p in LOAN_PROGRAMS}
_PURPOSE_IDS = {p["id"] for p in LOAN_PURPOSES}
_OCCUPANCY_IDS = {o["id"] for o in OCCUPANCY_TYPES}
_SCENARIO_IDS = {f["id"] for f in SCENARIO_FLAGS}
_AUS_ENGINE_IDS = {a["id"] for a in AUS_ENGINES}
_AUS_WAIVER_IDS = {w["id"] for w in AUS_WAIVER_OPTIONS}
_STATE_SET = set(US_STATES)


# ── Loan context shape ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class LoanContext:
    """Snapshot of the loan scenario captured at upload time.

    Frozen so a single context can be safely shared across rule predicates
    and the `evaluate` call. All optional fields have safe defaults; the
    predicates do their own membership checks.
    """
    program: str = "conv"
    purpose: str = "purchase"
    occupancy: str = "primary"
    state: str = "CT"
    scenario_flags: tuple[str, ...] = ()
    aus_engine: str = "du"
    aus_waivers: tuple[str, ...] = ()
    loan_amount: float | None = None
    property_value: float | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "LoanContext":
        d = data or {}
        flags = d.get("scenarioFlags") or d.get("scenario_flags") or []
        waivers = d.get("ausWaivers") or d.get("aus_waivers") or []
        engine = d.get("ausEngine") or d.get("aus_engine") or "du"
        loan_amount = d.get("loanAmount") if d.get("loanAmount") is not None else d.get("loan_amount")
        property_value = (
            d.get("propertyValue")
            if d.get("propertyValue") is not None
            else d.get("property_value")
        )
        return cls(
            program=d.get("program", "conv"),
            purpose=d.get("purpose", "purchase"),
            occupancy=d.get("occupancy", "primary"),
            state=d.get("state", "CT"),
            scenario_flags=tuple(sorted(set(flags))),
            aus_engine=engine,
            aus_waivers=tuple(sorted(set(waivers))),
            loan_amount=float(loan_amount) if loan_amount is not None else None,
            property_value=float(property_value) if property_value is not None else None,
        )

    def to_dict(self) -> dict:
        return {
            "program": self.program,
            "purpose": self.purpose,
            "occupancy": self.occupancy,
            "state": self.state,
            "scenarioFlags": list(self.scenario_flags),
            "ausEngine": self.aus_engine,
            "ausWaivers": list(self.aus_waivers),
            "loanAmount": self.loan_amount,
            "propertyValue": self.property_value,
        }


def validate_loan_context(ctx: LoanContext) -> list[str]:
    """Return human-readable errors for unknown enum values; empty if valid."""
    errors: list[str] = []
    if ctx.program and ctx.program not in _PROGRAM_IDS:
        errors.append(f"Unknown loan program: {ctx.program}")
    if ctx.purpose and ctx.purpose not in _PURPOSE_IDS:
        errors.append(f"Unknown loan purpose: {ctx.purpose}")
    if ctx.occupancy and ctx.occupancy not in _OCCUPANCY_IDS:
        errors.append(f"Unknown occupancy: {ctx.occupancy}")
    if ctx.state and ctx.state not in _STATE_SET:
        errors.append(f"Unknown state: {ctx.state}")
    if ctx.aus_engine and ctx.aus_engine not in _AUS_ENGINE_IDS:
        errors.append(f"Unknown AUS engine: {ctx.aus_engine}")
    bad_flags = [f for f in ctx.scenario_flags if f not in _SCENARIO_IDS]
    if bad_flags:
        errors.append(f"Unknown scenario flags: {', '.join(bad_flags)}")
    bad_waivers = [w for w in ctx.aus_waivers if w not in _AUS_WAIVER_IDS]
    if bad_waivers:
        errors.append(f"Unknown AUS waivers: {', '.join(bad_waivers)}")
    return errors


# ── Program-family predicates ──────────────────────────────────────────────

def is_government(program: str) -> bool:
    return program in {"fha", "fha_203k", "fha_stream", "va_pur", "va_irrrl", "usda"}


def is_fha(program: str) -> bool:
    return bool(program) and program.startswith("fha")


def is_va(program: str) -> bool:
    return bool(program) and program.startswith("va_")


def is_usda(program: str) -> bool:
    return program == "usda"


def is_jumbo(program: str) -> bool:
    return program == "jumbo"


def is_nonqm(program: str) -> bool:
    return bool(program) and program.startswith("nonqm_")


def is_streamline(program: str) -> bool:
    return program in {"fha_stream", "va_irrrl"}


# ── Rule definition ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ComplianceRule:
    """Single compliance check.

    `requires` lists the document-type labels that satisfy this rule. The
    interaction between `requires` and `requires_mode` is:
        - `process` (or empty `requires`): no doc satisfies; status is always
          `attestation_required` (LOS / process attestation must cover it)
        - `any`: at least one of `requires` present → compliant
        - `all`: every entry of `requires` present → compliant; some present →
          partial; none → missing
    `when` is an optional predicate over `LoanContext`. If it returns False the
    rule is excluded from the evaluation entirely (it does not apply to this
    scenario), keeping the LO view clean of irrelevant items.
    """
    id: str
    category: str
    regulation: str
    requirement: str
    requires: tuple[str, ...]
    requires_mode: RequiresMode
    severity: Severity
    details: str
    remediation: str
    when: Callable[[LoanContext], bool] | None = None


def _rule_applies(rule: ComplianceRule, ctx: LoanContext) -> bool:
    if rule.when is None:
        return True
    try:
        return bool(rule.when(ctx))
    except Exception:
        # A predicate exception must not crash the whole evaluation; skip the
        # rule (conservative — won't surface a finding from a broken predicate).
        return False


# ── Rule library — verbatim port of prototype COMPLIANCE_CHECKS ────────────

COMPLIANCE_CHECKS: list[ComplianceRule] = [
    ComplianceRule(
        id="cmp_app_urla",
        category="Application & Pricing",
        regulation="ECOA Reg B 1002.5; HMDA Reg C 1003",
        requirement="Uniform Residential Loan Application (Form 1003) on file",
        requires=("Form 1003",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.CRITICAL,
        details=(
            "The 1003 establishes the application date that triggers Reg B "
            "adverse-action timing (30 days) and Reg Z Loan Estimate delivery "
            "(3 business days). The Government Monitoring Information section "
            "drives HMDA LAR reporting."
        ),
        remediation=(
            "Obtain a fully executed URLA (current FNMA/FHLMC redesigned 1003) "
            "from the borrower before underwriting; confirm Section 9 GMI completion."
        ),
    ),
    ComplianceRule(
        id="cmp_atr_income",
        category="Ability-to-Repay (ATR/QM)",
        regulation="12 CFR 1026.43(c); FNMA Selling Guide B3-3",
        requirement="Verified current income (paystubs, W-2, VOE, or self-employed 1040)",
        requires=("Paystubs", "W-2", "Verification of Employment", "Form 1040"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "Reg Z 1026.43 requires creditors to verify current and reasonably "
            "expected income or assets using third-party records. Acceptable: "
            "paystubs covering ≥30 days, two most recent W-2s, written/verbal VOE, "
            "or two years of signed personal returns for self-employed borrowers."
        ),
        remediation=(
            "Collect at least one income document type. For QM safe harbor, "
            "document fully-indexed-rate DTI ≤43% or qualifying GSE eligibility."
        ),
        # Streamlines waive income; DSCR qualifies on rents.
        when=lambda ctx: not is_streamline(ctx.program) and ctx.program != "nonqm_dscr",
    ),
    ComplianceRule(
        id="cmp_atr_assets",
        category="Ability-to-Repay (ATR/QM)",
        regulation="12 CFR 1026.43(c)(2)(viii)",
        requirement="Asset / down-payment verification (bank statements ≥2 months)",
        requires=("Bank Statements",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.HIGH,
        details=(
            "Down-payment, closing costs, and reserves must be verified. Two most "
            "recent statements (all pages) are standard. Large deposits inconsistent "
            "with income require source-of-funds documentation per AML and FNMA B3-4."
        ),
        remediation=(
            "Request 2 most recent bank statements, all pages; document any large/"
            "irregular deposits."
        ),
    ),
    ComplianceRule(
        id="cmp_credit_pull",
        category="Credit & FCRA",
        regulation="FCRA 15 USC 1681m; Reg V 1022.72 (Risk-Based Pricing)",
        requirement="Tri-merge credit report on file; RBPN or credit-score exception delivered",
        requires=("Credit Report",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.CRITICAL,
        details=(
            "A permissible-purpose credit pull is required. If APR is materially less "
            "favorable than for a substantial proportion of consumers, a Risk-Based "
            "Pricing Notice is required; most lenders use the credit-score disclosure "
            "exception (1022.74) and deliver scores at application."
        ),
        remediation=(
            "Pull tri-merge credit (Experian/Equifax/TransUnion); deliver credit-score "
            "disclosure (Notice H-3) with the LE."
        ),
    ),
    ComplianceRule(
        id="cmp_appraisal",
        category="Appraisal Independence",
        regulation="ECOA 1002.14; Dodd-Frank §1471 (TILA 129H); AIR Code",
        requirement="Form 1004 appraisal with documented AIR-compliant ordering",
        requires=("Form 1004", "Form 1004 Appraisal"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "Reg B 1002.14 requires appraisal copies to be delivered promptly upon "
            "completion or three business days before consummation, whichever is "
            "earlier. The Appraiser Independence Requirements (AIR) require a "
            "firewall between sales/production staff and appraiser selection."
        ),
        remediation=(
            "Order independent appraisal (URAR Form 1004) via AMC or AIR-compliant "
            "panel; deliver to borrower with timestamped acknowledgement at least "
            "3 business days before closing."
        ),
        # Streamlines waive appraisal; DU/LPA PIW also suppresses.
        when=lambda ctx: not is_streamline(ctx.program) and "piw" not in ctx.aus_waivers,
    ),
    ComplianceRule(
        id="cmp_title",
        category="Title & Settlement",
        regulation="RESPA Reg X 1024; 1024.15 (AfBA)",
        requirement="Title commitment on file before CD issuance",
        requires=("Title Commitment",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.HIGH,
        details=(
            "Title work is a settlement service under RESPA. If the title provider is "
            "affiliated with the lender, an Affiliated Business Arrangement (AfBA) "
            "disclosure is required. Section 9 of RESPA prohibits the seller from "
            "requiring the use of a particular title insurer."
        ),
        remediation=(
            "Obtain title commitment from a borrower-selected (or properly disclosed) "
            "settlement agent; ensure AfBA on file if applicable."
        ),
    ),
    ComplianceRule(
        id="cmp_trid_cd",
        category="TRID Disclosures",
        regulation="TRID 1026.19(f); 1026.38",
        requirement="Closing Disclosure issued ≥3 business days before consummation",
        requires=("HUD-1 / Closing Disclosure", "Closing Disclosure"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "The Closing Disclosure must be received by the consumer no later than "
            "three business days before consummation. Triggering changes (APR > 1/8% "
            "for fixed / 1/4% for ARM, change in loan product, prepay-penalty addition) "
            "restart the 3-day clock."
        ),
        remediation="Issue/re-issue CD and re-time closing if a triggering change occurs.",
    ),
    ComplianceRule(
        id="cmp_trid_purchase",
        category="TRID Disclosures",
        regulation="RESPA 1024.7; TRID 1026.19",
        requirement="Executed purchase contract supporting the transaction",
        requires=("Purchase Agreement",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.HIGH,
        details=(
            "Sales price drives LTV, escrow, and TRID tolerance buckets. Required for "
            "purchase-money loans; refis require alternate evidence of property value "
            "and occupancy."
        ),
        remediation="Obtain fully-executed purchase contract; verify earnest-money source.",
    ),
    ComplianceRule(
        id="cmp_hoi",
        category="Insurance & Flood",
        regulation="FNMA Selling Guide B7-3; Reg Z 1026.35 escrow",
        requirement="Hazard insurance binder/declarations page evidencing coverage at closing",
        requires=("Homeowners Insurance",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.CRITICAL,
        details=(
            "Lender must ensure dwelling coverage at least equal to the lesser of the "
            "loan balance or replacement cost, with first-year premium paid at closing. "
            "Mortgagee clause must name the lender ISAOA/ATIMA."
        ),
        remediation=(
            "Collect HOI declarations page with effective date prior to consummation "
            "and lender mortgagee clause."
        ),
    ),
    ComplianceRule(
        id="cmp_flood",
        category="Insurance & Flood",
        regulation="42 USC 4012a; Biggert-Waters; HFIAA",
        requirement="Standard Flood Hazard Determination (SFHDF); flood insurance if SFHA",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.HIGH,
        details=(
            "Lender must obtain SFHDF for every secured property. If property is in a "
            "Special Flood Hazard Area, NFIP-equivalent flood insurance must be in "
            "place prior to closing; the borrower must receive the Notice of Special "
            "Flood Hazards at least 10 days before closing."
        ),
        remediation=(
            "Order SFHDF; if SFHA, deliver Notice and bind flood insurance prior to closing."
        ),
    ),
    ComplianceRule(
        id="cmp_hmda_gmi",
        category="HMDA / Fair Lending",
        regulation="HMDA Reg C 1003; ECOA Reg B 1002.13",
        requirement="Government Monitoring Information (Section 9 of 1003) collected",
        requires=("Form 1003",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.HIGH,
        details=(
            "GMI fields (ethnicity/race/sex) must be solicited. If the applicant "
            "declines and the application was taken in person, the loan officer must "
            "collect by visual observation/surname. All HMDA reportable transactions "
            "must populate the LAR within HMDA-required timeframes."
        ),
        remediation=(
            "Confirm Section 9 completion on the URLA; if missing, document attempted "
            "collection or LO visual observation."
        ),
    ),
    ComplianceRule(
        id="cmp_aml_bsa",
        category="AML / BSA / OFAC",
        regulation="USA PATRIOT Act §326; FinCEN 31 CFR 1029",
        requirement="Customer Identification Program (CIP) and OFAC SDN screening",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.CRITICAL,
        details=(
            "Non-bank residential mortgage lenders/originators are subject to AML "
            "program rules under FinCEN 31 CFR 1029, including CIP, SAR filing, and "
            "OFAC screening of borrower (and seller for purchases) against the SDN "
            "list before closing."
        ),
        remediation=(
            "Verify CIP completion in LOS; rerun OFAC against current SDN list within "
            "24 hours of closing."
        ),
    ),
    ComplianceRule(
        id="cmp_tax_returns",
        category="Income Verification",
        regulation="FNMA Selling Guide B3-3.2; FHA 4000.1 II.A.4.c",
        requirement="Tax returns (Form 1040) for self-employed or supplemental-income borrowers",
        requires=("Form 1040",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.MEDIUM,
        details=(
            "Self-employed borrowers, those with commission >25% of base, or "
            "rental-income earners require two years of signed personal returns plus "
            "YTD profit-and-loss. W-2 wage-earners may not require returns unless "
            "investor overlay applies."
        ),
        remediation=(
            "Obtain 2 years signed 1040s with all schedules; obtain 4506-C transcript "
            "authorization for IRS verification."
        ),
        when=lambda ctx: ("self_employed" in ctx.scenario_flags) or ("rental_income" in ctx.scenario_flags),
    ),
    ComplianceRule(
        id="cmp_voe",
        category="Income Verification",
        regulation="FNMA Selling Guide B3-3.1; FHA 4000.1",
        requirement="Verbal/written Verification of Employment within 10 days of closing",
        requires=("Verification of Employment",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.MEDIUM,
        details=(
            "A VOE is required to confirm continuance of employment near closing. "
            "Verbal VOE is acceptable but must be documented (employer phone, contact "
            "name, date); written VOE is standard for self-employed borrowers via CPA "
            "or business license."
        ),
        remediation=(
            "Conduct VOE within 10 business days of note date; retain VOE evidence in "
            "the loan file."
        ),
    ),
    ComplianceRule(
        id="cmp_glba",
        category="Privacy & Data",
        regulation="GLBA 15 USC 6801-6809; Reg P 1016",
        requirement="Privacy notice delivered at customer relationship inception",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.LOW,
        details=(
            "A Reg P privacy notice (or model 'short-form' notice) must be delivered "
            "to the consumer at the time the customer relationship is established. "
            "Re-delivery is required if practices change materially."
        ),
        remediation=(
            "Confirm initial privacy notice was delivered with the LE; retain proof of "
            "delivery."
        ),
    ),
    # ── Program-specific ───────────────────────────────────────────────────
    ComplianceRule(
        id="cmp_fha_case_no",
        category="FHA Program",
        regulation="HUD Handbook 4000.1 II.A.1; FHA Connection",
        requirement="FHA Case Number Assignment on file",
        requires=("FHA Case Number Assignment",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.CRITICAL,
        details=(
            "Every FHA-insured loan requires a Case Number Assignment from FHA "
            "Connection before underwriting. The Case Number Assignment confirms "
            "property eligibility, drives MIP calculations, and is required for "
            "endorsement."
        ),
        remediation=(
            "Order Case Number through FHA Connection; retain the assignment "
            "screen-print in the loan file."
        ),
        when=lambda ctx: is_fha(ctx.program),
    ),
    ComplianceRule(
        id="cmp_fha_caivrs",
        category="FHA Program",
        regulation="HUD Handbook 4000.1 II.A.1.b.iv",
        requirement="CAIVRS clearance for all borrowers",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.CRITICAL,
        details=(
            "The Credit Alert Verification Reporting System (CAIVRS) must be queried "
            "for every borrower on an FHA loan. A delinquent federal-debt hit "
            "disqualifies the borrower until cleared."
        ),
        remediation=(
            "Pull CAIVRS via FHA Connection for each borrower; resolve any "
            "delinquencies before submitting for endorsement."
        ),
        when=lambda ctx: is_fha(ctx.program),
    ),
    ComplianceRule(
        id="cmp_fha_amend",
        category="FHA Program",
        regulation="HUD Handbook 4000.1 II.A.1.b.iii",
        requirement="Amendatory Clause and Real Estate Certification (purchase only)",
        requires=("Amendatory Clause", "Real Estate Certification"),
        requires_mode=RequiresMode.ALL,
        severity=Severity.HIGH,
        details=(
            "FHA purchase transactions require a signed Amendatory Clause (allows the "
            "borrower to withdraw if the appraisal is below contract price) and a "
            "Real Estate Certification signed by buyer, seller, and agent."
        ),
        remediation=(
            "Add the Amendatory Clause to the purchase contract; obtain signed Real "
            "Estate Certification before closing."
        ),
        when=lambda ctx: is_fha(ctx.program) and ctx.purpose == "purchase",
    ),
    ComplianceRule(
        id="cmp_va_coe",
        category="VA Program",
        regulation="VA Lender's Handbook M26-7 Ch. 2",
        requirement="Certificate of Eligibility (COE) on file",
        requires=("VA Certificate of Eligibility", "Certificate of Eligibility"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "Every VA-guaranteed loan requires a current Certificate of Eligibility "
            "evidencing the veteran's entitlement. The COE drives the funding fee "
            "calculation and is required for guaranty."
        ),
        remediation=(
            "Request COE through WebLGY (LGY Hub); confirm entitlement amount supports "
            "the loan."
        ),
        when=lambda ctx: is_va(ctx.program),
    ),
    ComplianceRule(
        id="cmp_va_nov",
        category="VA Program",
        regulation="VA Lender's Handbook M26-7 Ch. 10",
        requirement="Notice of Value (NOV) issued by VA-assigned appraiser",
        requires=("VA Notice of Value", "Notice of Value"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "VA purchase loans require a Notice of Value from a VA panel appraiser. "
            "Tidewater initiative applies if appraised value will be below contract "
            "price — the appraiser must contact the lender before issuing the NOV."
        ),
        remediation=(
            "Order appraisal through VA Portal; review NOV against contract; respond "
            "to Tidewater within 2 business days if applicable."
        ),
        when=lambda ctx: ctx.program == "va_pur",
    ),
    ComplianceRule(
        id="cmp_usda_gus",
        category="USDA Program",
        regulation="USDA RD HB-1-3555 Ch. 5",
        requirement="GUS Findings + Final Submission documented",
        requires=("USDA GUS Findings", "GUS Findings"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "USDA Guaranteed loans require a GUS (Guaranteed Underwriting System) "
            "Findings report and a Final Submission upload before Conditional "
            "Commitment. Manual underwrites require additional documentation per "
            "HB-1-3555 Ch. 5."
        ),
        remediation=(
            "Run GUS, address all findings, then perform Final Submission to obtain "
            "Conditional Commitment."
        ),
        when=lambda ctx: is_usda(ctx.program),
    ),
    ComplianceRule(
        id="cmp_jumbo_2nd_appr",
        category="Jumbo Overlays",
        regulation="Investor overlay (loan amount > $1,000,000)",
        requirement="Two appraisals required for high-balance jumbo loans",
        requires=("Form 1004", "Second Appraisal", "Form 1004 Appraisal"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.HIGH,
        details=(
            "Most jumbo investors require a second independent appraisal (or field "
            "review) when the loan amount exceeds $1M or $1.5M depending on investor "
            "matrix. Both reports must be reconciled to the lower of the two values."
        ),
        remediation=(
            "Order a second appraisal from a different AMC; reconcile values per "
            "investor guideline before closing."
        ),
        when=lambda ctx: is_jumbo(ctx.program),
    ),
    ComplianceRule(
        id="cmp_nonqm_bank_stmts",
        category="Non-QM Documentation",
        regulation="Investor program guideline",
        requirement="12 or 24 months of business + personal bank statements",
        requires=("Bank Statements", "12-Month Bank Statements", "24-Month Bank Statements"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "Non-QM Bank Statement programs qualify self-employed borrowers from "
            "deposit history. Most investors require 12 or 24 months of business "
            "statements plus 2 months of personal statements; deposits are scrubbed "
            "for legitimacy and a P&L (often CPA-prepared) reconciles to deposits."
        ),
        remediation=(
            "Collect required months of statements; obtain CPA-prepared P&L reconciling "
            "to deposit history."
        ),
        when=lambda ctx: ctx.program == "nonqm_bs",
    ),
    ComplianceRule(
        id="cmp_dscr_lease",
        category="Non-QM Documentation",
        regulation="Investor DSCR program guideline",
        requirement="Lease agreements or 1007/216 market-rent addendum",
        requires=("Lease Agreement", "Form 1007", "Form 216"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.CRITICAL,
        details=(
            "DSCR loans qualify on the rental income of the subject property. "
            "Investors require either executed leases (current rents) or a 1007/216 "
            "appraisal addendum (market rents) to compute the Debt Service Coverage "
            "Ratio."
        ),
        remediation=(
            "Provide executed leases for occupied units; for vacant units, request "
            "1007/216 from appraiser."
        ),
        when=lambda ctx: ctx.program == "nonqm_dscr",
    ),
    # ── Scenario-driven ────────────────────────────────────────────────────
    ComplianceRule(
        id="cmp_gift_letter",
        category="Asset Documentation",
        regulation="FNMA Selling Guide B3-4.3-04; FHA 4000.1 II.A.4.d.iii",
        requirement="Gift letter and donor evidence for gift funds",
        requires=("Gift Letter",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.HIGH,
        details=(
            "Any gift used toward down payment, closing costs, or reserves requires a "
            "signed gift letter (donor name, relationship, amount, no repayment) plus "
            "evidence of donor's ability and the transfer of funds."
        ),
        remediation=(
            "Collect signed gift letter, donor bank statement showing source, and "
            "evidence of transfer to borrower account."
        ),
        when=lambda ctx: "gift_funds" in ctx.scenario_flags,
    ),
    ComplianceRule(
        id="cmp_rental_schedule_e",
        category="Income Verification",
        regulation="FNMA Selling Guide B3-3.1-08",
        requirement="Schedule E (Form 1040) for rental income",
        requires=("Form 1040", "Schedule E"),
        requires_mode=RequiresMode.ANY,
        severity=Severity.HIGH,
        details=(
            "When rental income is used to qualify, two years of Schedule E from "
            "personal returns (or current lease + market rent) is required. Vacancy "
            "is netted at 25% per Fannie / 75% per Freddie."
        ),
        remediation=(
            "Collect 2 years of Schedule E; for properties owned <2 years, use current "
            "lease net of vacancy."
        ),
        when=lambda ctx: "rental_income" in ctx.scenario_flags,
    ),
    # ── State overlays ─────────────────────────────────────────────────────
    ComplianceRule(
        id="cmp_state_ny_6l",
        category="State Overlays",
        regulation="NY Banking Law §6-l (Subprime/High-Cost)",
        requirement="NY §6-l high-cost test passed",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.HIGH,
        details=(
            "New York §6-l defines 'high-cost' and 'subprime' home loans using "
            "APR-vs-treasury and points-and-fees thresholds. High-cost loans require "
            "borrower counseling, prohibit certain terms (prepay penalty, balloon), "
            "and impose enhanced ATR."
        ),
        remediation=(
            "Run pricing through §6-l APR/fee test in your LOS; document counseling "
            "certificate if loan meets high-cost threshold."
        ),
        when=lambda ctx: ctx.state == "NY",
    ),
    ComplianceRule(
        id="cmp_state_tx_50a6",
        category="State Overlays",
        regulation="TX Constitution Article 16 §50(a)(6)",
        requirement="Texas Section 50(a)(6) home equity disclosures",
        requires=("Texas 50(a)(6) Disclosure",),
        requires_mode=RequiresMode.ALL,
        severity=Severity.CRITICAL,
        details=(
            "Texas constitution Section 50(a)(6) governs home-equity / cash-out loans "
            "on a Texas homestead: 80% LTV cap, 12-day notice, 3% fee cap, no closing "
            "at home, only one 50(a)(6) per 12 months."
        ),
        remediation=(
            "Provide 12-day notice; close at title company / attorney office; verify "
            "80% LTV and fee cap; obtain notarized acknowledgement."
        ),
        when=lambda ctx: ctx.state == "TX" and ctx.purpose == "co_refi",
    ),
    ComplianceRule(
        id="cmp_hoepa_32",
        category="High-Cost / HPML",
        regulation="HOEPA / Reg Z §1026.32",
        requirement="HOEPA §32 test (APR/APOR + points-and-fees)",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.CRITICAL,
        details=(
            "A loan that exceeds the §1026.32 APR-over-APOR or points-and-fees "
            "thresholds becomes a §32 high-cost loan: enhanced ATR, pre-loan counseling "
            "required, prohibitions on balloon/prepay-penalty, 3-day right of "
            "rescission, and special disclosures."
        ),
        remediation=(
            "Re-price below §32 thresholds, deliver counseling cert if proceeding, and "
            "use the §32-compliant disclosure stack."
        ),
        when=lambda ctx: "high_cost" in ctx.scenario_flags,
    ),
    # ── Advisory ("present-but-verify") rules ───────────────────────────────
    # Severity.INFO + RequiresMode.PROCESS — they always evaluate to
    # `attestation_required` and never count toward closeability criticals.
    # Their job is to remind the LO/QC team to *verify* a procedural item
    # (timing, acknowledgement) that no single document fully captures.
    ComplianceRule(
        id="cmp_advisory_le_timing",
        category="TRID Disclosures",
        regulation="TRID 1026.19(e)(1)(iii)",
        requirement="Loan Estimate delivered within 3 business days of application",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Reg Z requires the Loan Estimate to be delivered or placed in the mail "
            "no later than the third business day after receipt of the application "
            "(URLA Section 1 fields complete). This is a timing rule — a present LE "
            "does not by itself prove timely delivery."
        ),
        remediation=(
            "Verify the LE delivery date in the LOS audit trail; ensure 3-business-day "
            "rule met from date of application."
        ),
    ),
    ComplianceRule(
        id="cmp_advisory_cd_3day",
        category="TRID Disclosures",
        regulation="TRID 1026.19(f)(1)(ii)",
        requirement="Closing Disclosure 3-business-day waiting period observed",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "The Closing Disclosure must be received by the consumer no later than "
            "three business days before consummation. This is procedural — if a "
            "triggering change occurs (APR > 1/8% fixed / 1/4% ARM, loan-product change, "
            "prepayment-penalty addition), the 3-day clock restarts."
        ),
        remediation=(
            "Confirm CD receipt date and any redisclosure events. If a triggering change "
            "occurred, verify the new 3-day clock was honored before closing."
        ),
    ),
    ComplianceRule(
        id="cmp_advisory_privacy_ack",
        category="Privacy & Data",
        regulation="GLBA Reg P 1016.5",
        requirement="Initial privacy-notice delivery acknowledged in file",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Reg P requires delivery of an initial privacy notice no later than when "
            "the customer relationship is established. The notice itself may be in the "
            "disclosure packet, but the file should contain dated proof of delivery "
            "(borrower acknowledgement, e-sign audit trail, or mail log)."
        ),
        remediation=(
            "Pull the e-sign audit trail or mailing log evidencing initial privacy "
            "notice delivery; retain in the loan file."
        ),
    ),
    ComplianceRule(
        id="cmp_advisory_adverse_action_timing",
        category="Credit & FCRA",
        regulation="ECOA Reg B 1002.9; FCRA 1681m",
        requirement="Adverse Action notice issued within 30 days of completed application",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "If the application is denied, withdrawn after counter-offer, or otherwise "
            "results in adverse action, Reg B requires notification within 30 days of "
            "receipt of a completed application. FCRA further requires that any credit-"
            "report-derived denial cite the consumer-reporting agency."
        ),
        remediation=(
            "If the file is heading toward adverse action, queue the AAN with the 30-"
            "day clock visible. Verify the FCRA disclosure block on the AAN cites the "
            "specific CRA(s)."
        ),
    ),
    ComplianceRule(
        id="cmp_advisory_ecoa_valuations",
        category="Appraisal Independence",
        regulation="ECOA Reg B 1002.14(a)(1)",
        requirement="Appraisal copy delivered ≥3 business days before consummation",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "The ECOA Valuations Rule requires the lender to provide the consumer a "
            "copy of all appraisals and other written valuations promptly upon "
            "completion, or three business days before consummation, whichever is "
            "earlier. The consumer may waive the 3-day timing only with a written "
            "waiver received ≥3 business days before consummation."
        ),
        remediation=(
            "Verify the appraisal-delivery timestamp and any timing-waiver document. "
            "If neither path is satisfied, re-time consummation."
        ),
        # Skip this advisory when no appraisal is required (streamlines + PIW).
        when=lambda ctx: not is_streamline(ctx.program) and "piw" not in ctx.aus_waivers,
    ),
    # ── Phase A: Origination audit gaps (v3) ────────────────────────────────
    # Mirrors the PM's audit catalog. All advisory (INFO + PROCESS) so they
    # surface as `attestation_required` rather than blocking closeability —
    # most are program-level/process audits no single document can prove.
    ComplianceRule(
        id="cmp_udaap_review",
        category="UDAAP",
        regulation="Dodd-Frank §§1031, 1036; CFPB Bulletin 2013-07",
        requirement="UDAAP review of advertising, disclosures, and loan terms",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "The CFPB prohibits unfair, deceptive, or abusive acts or practices "
            "across the loan lifecycle — marketing, application, disclosures, "
            "servicing transitions. A UDAAP review confirms representations are "
            "substantiated, fee descriptions are accurate, comparison advertising "
            "is not misleading, and consumer-choice language is not coerced."
        ),
        remediation=(
            "Run the file through the UDAAP review checklist (advertising "
            "claims, fee descriptions, prepayment/ARM terms). Document the "
            "reviewer, date, and any remediated language."
        ),
    ),
    ComplianceRule(
        id="cmp_fair_housing_act",
        category="Fair Lending & Fair Housing",
        regulation="Fair Housing Act 42 USC §3601; ECOA Reg B 1002.4(b); HUD",
        requirement="Equal Housing Opportunity disclosure + non-discrimination review",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "The Fair Housing Act prohibits discrimination in residential "
            "lending based on race, color, national origin, religion, sex, "
            "familial status, or disability. The Equal Housing Opportunity "
            "logo/notice must appear on advertising and the application "
            "package. Pricing and underwriting decisions must be free of "
            "disparate treatment and unjustified disparate impact."
        ),
        remediation=(
            "Confirm Equal Housing Opportunity language in the application "
            "package; document fair-lending review of pricing exceptions and "
            "underwriting overlays for this file."
        ),
    ),
    ComplianceRule(
        id="cmp_pre_funding_qc",
        category="Loan Quality & QC",
        regulation="FNMA Selling Guide D1-2-01; FHLMC Guide 3402.5",
        requirement="Pre-funding QC review completed for sampled loans",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Fannie Mae and Freddie Mac require a pre-funding QC program that "
            "samples loans before closing to validate data integrity, AUS "
            "decision, income/asset/credit re-verification, and appraisal. "
            "Findings must be addressed before funding."
        ),
        remediation=(
            "If this file is in the pre-funding QC sample, attach the "
            "completed pre-funding QC checklist and resolve any outstanding "
            "defects before issuing closing instructions."
        ),
    ),
    ComplianceRule(
        id="cmp_loan_file_documentation",
        category="Loan Quality & QC",
        regulation="FNMA Selling Guide D1-3-04; FHLMC Guide 3402.7",
        requirement="Loan file documentation audit (completeness + integrity)",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "A loan-file documentation audit verifies every required document "
            "is present, executed, dated, legible, and consistent across the "
            "file (URLA vs. credit, appraisal vs. sales contract, income docs "
            "vs. AUS findings). It is the foundation for both pre-funding and "
            "post-closing QC reviews."
        ),
        remediation=(
            "Run the loan-file documentation checklist; reconcile any "
            "discrepancies between the URLA, credit report, appraisal, and "
            "income/asset documentation."
        ),
    ),
    ComplianceRule(
        id="cmp_fnma_loan_quality",
        category="Loan Quality & QC",
        regulation="FNMA Selling Guide D1-3 (Lender Post-Closing QC)",
        requirement="Fannie Mae loan quality / post-closing QC review",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Lenders selling to Fannie Mae must perform a post-closing QC "
            "review of a statistically valid sample (or 10% random) within "
            "120 days of month-end. The review re-verifies income, employment, "
            "assets, occupancy, and re-underwrites the credit decision."
        ),
        remediation=(
            "Confirm this loan is included in the FNMA post-closing QC sample "
            "queue; verify the sampling methodology and 120-day completion SLA."
        ),
        # DU-routed loans are the FNMA quality population.
        when=lambda ctx: ctx.aus_engine == "du",
    ),
    ComplianceRule(
        id="cmp_fhlmc_loan_quality",
        category="Loan Quality & QC",
        regulation="FHLMC Guide Chapter 3402 (Quality Control)",
        requirement="Freddie Mac quality control / post-closing review",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Sellers to Freddie Mac must perform post-closing QC on a "
            "statistically valid sample within 90 days of month-end (or 120 "
            "for random sampling). The review covers underwriting, "
            "documentation, property valuation, and data integrity."
        ),
        remediation=(
            "Confirm this loan is included in the FHLMC post-closing QC "
            "queue; verify sample selection rationale and SLA."
        ),
        # LPA-routed loans are the FHLMC quality population.
        when=lambda ctx: ctx.aus_engine == "lpa",
    ),
    ComplianceRule(
        id="cmp_repurchase_risk",
        category="Loan Quality & QC",
        regulation="FNMA Selling Guide A2-3; FHLMC Guide 1301 / 1302",
        requirement="Repurchase / buyback risk review against rep-and-warrant defects",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Selling representations and warranties create repurchase exposure "
            "if a defect is discovered post-sale. Common triggers: misrepresented "
            "income or occupancy, ineligible appraisal, missing required docs, "
            "data integrity errors on the LAR. A repurchase risk review scores "
            "the file against the defect taxonomy before delivery."
        ),
        remediation=(
            "Run the repurchase-risk checklist; clear any Level 1 (significant) "
            "defects before delivery and document mitigations for Level 2."
        ),
        # Investor-eligible programs only — Non-QM / DSCR aren't in the agency
        # rep-and-warrant frame.
        when=lambda ctx: ctx.program in {"conv", "conv_hb", "fha", "fha_203k", "fha_stream", "va_pur", "va_irrrl", "usda"},
    ),
    ComplianceRule(
        id="cmp_respa_afba",
        category="RESPA Disclosures",
        regulation="RESPA Reg X 1024.15 (AfBA)",
        requirement="Affiliated Business Arrangement disclosure on file when applicable",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "If the lender refers the borrower to a settlement-service provider "
            "(title, escrow, AMC, insurance) in which it has an ownership or "
            "beneficial interest, RESPA §8 requires a written AfBA disclosure "
            "delivered at or before the referral, listing the nature of the "
            "relationship and an estimated charge range."
        ),
        remediation=(
            "Identify any affiliated providers used on this file; confirm an "
            "AfBA disclosure is on file with delivery timestamp ≤ referral date."
        ),
    ),
    ComplianceRule(
        id="cmp_respa_servicing_transfer",
        category="RESPA Disclosures",
        regulation="RESPA Reg X 1024.33(a)",
        requirement="Servicing Transfer Disclosure (Section 6) provided at application",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "RESPA Section 6 requires lenders to provide an initial Servicing "
            "Disclosure Statement at application (or within 3 business days "
            "thereafter). The disclosure tells the borrower whether servicing "
            "may be transferred and the lender's transfer history. A separate "
            "Notice of Transfer is required if servicing actually transfers "
            "(15 days before by transferor, 15 days after by transferee)."
        ),
        remediation=(
            "Verify the Servicing Disclosure Statement is in the application "
            "packet and that the delivery date is within 3 business days of "
            "the application date."
        ),
    ),
    ComplianceRule(
        id="cmp_tila_rescission",
        category="TRID Disclosures",
        regulation="TILA Reg Z 1026.23",
        requirement="Notice of Right to Rescind delivered for refinance on primary residence",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Reg Z 1026.23 grants a 3-business-day right of rescission on "
            "non-purchase loans secured by the borrower's principal dwelling. "
            "Each consumer entitled to rescind must receive two copies of the "
            "Notice of Right to Cancel plus the material disclosures. The "
            "rescission period runs from the latest of consummation, delivery "
            "of the material disclosures, or delivery of the rescission notice."
        ),
        remediation=(
            "Confirm two copies of the Notice of Right to Cancel were delivered "
            "to each rescinding consumer at consummation, and that no funds "
            "were disbursed before the 3-business-day clock expired."
        ),
        # Rescission applies only to refinances of a principal dwelling.
        when=lambda ctx: ctx.purpose in {"rt_refi", "co_refi"} and ctx.occupancy == "primary",
    ),
    ComplianceRule(
        id="cmp_hmda_lar_completeness",
        category="HMDA / Fair Lending",
        regulation="HMDA Reg C 1003.4",
        requirement="HMDA LAR data fields complete and consistent with file",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Reg C 1003.4 requires reportable fields beyond GMI: Universal "
            "Loan Identifier, application/action-taken dates, loan type/"
            "purpose/amount, dwelling category, occupancy, property location "
            "(geocoded), pricing data (rate spread, HOEPA, lien status), "
            "credit score, AUS engine + decision, and denial reasons (if "
            "applicable). LAR field defects are the leading repurchase trigger."
        ),
        remediation=(
            "Run the LAR field-completeness check against the loan file; "
            "verify geocoding, action-taken date, and pricing fields against "
            "the LE/CD before submission."
        ),
    ),
    ComplianceRule(
        id="cmp_ecoa_incompleteness",
        category="Credit & FCRA",
        regulation="ECOA Reg B 1002.9(c)",
        requirement="Notice of Incompleteness sent within 30 days of incomplete application",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "If an application is incomplete regarding matters the applicant "
            "can complete, Reg B requires the creditor to send a written "
            "notice specifying the information needed and a reasonable "
            "completion deadline within 30 days of receiving the application. "
            "Failure to send the notice converts the file's adverse-action "
            "clock and creates an ECOA violation."
        ),
        remediation=(
            "If items remained outstanding 30 days after application, confirm "
            "a Notice of Incompleteness was sent with a reasonable deadline; "
            "retain the dated copy in the file."
        ),
    ),
    ComplianceRule(
        id="cmp_ecoa_joint_intent",
        category="Credit & FCRA",
        regulation="ECOA Reg B 1002.7(d)(1)",
        requirement="Written evidence of joint intent to apply at application",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "When two or more applicants apply jointly for credit, Reg B "
            "requires written evidence of joint intent dated at or before the "
            "time of application. A signed URLA section alone is insufficient "
            "if intent was not affirmed before/at application. This is a "
            "frequent ECOA fair-lending finding for spousal applicants."
        ),
        remediation=(
            "Verify the file contains a separate joint-intent affirmation "
            "(signed by all co-applicants) dated on or before the application "
            "date."
        ),
        when=lambda ctx: "co_borrower" in ctx.scenario_flags,
    ),
    ComplianceRule(
        id="cmp_trid_tolerances",
        category="TRID Disclosures",
        regulation="TRID 1026.19(e)(3)(i)–(iii)",
        requirement="Closing fee tolerance buckets (zero / 10% / unlimited) within limits",
        requires=(),
        requires_mode=RequiresMode.PROCESS,
        severity=Severity.INFO,
        details=(
            "Reg Z partitions closing charges into tolerance buckets. "
            "Zero-tolerance items (lender fees, fees for services the consumer "
            "could not shop for, transfer taxes) cannot increase from LE to CD. "
            "10% bucket items (recording fees, fees for services from a "
            "lender-permitted shopping list) cannot increase in aggregate by "
            "more than 10%. Unlimited bucket items (services the consumer "
            "shopped for outside the list, prepaids, escrow) have no cap but "
            "must be disclosed in good faith."
        ),
        remediation=(
            "Reconcile each LE-to-CD fee against its tolerance bucket; cure "
            "any zero-tolerance increase or 10%-aggregate breach by lender "
            "credit at or within 60 days of consummation."
        ),
    ),
]


# Sanity check — every rule ID must be unique. Catches copy-paste errors at
# import time so a typo can't silently shadow a rule in production.
_SEEN_IDS: set[str] = set()
for _r in COMPLIANCE_CHECKS:
    if _r.id in _SEEN_IDS:
        raise RuntimeError(f"Duplicate compliance rule id: {_r.id}")
    _SEEN_IDS.add(_r.id)
del _SEEN_IDS, _r


# ── Evaluation ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    """One evaluated rule against the package's documents."""
    id: str
    category: str
    regulation: str
    requirement: str
    requires: tuple[str, ...]
    requires_mode: str
    severity: str
    status: str
    matched: tuple[str, ...]
    missing_docs: tuple[str, ...]
    details: str
    remediation: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "regulation": self.regulation,
            "requirement": self.requirement,
            "requires": list(self.requires),
            "requiresMode": self.requires_mode,
            "severity": self.severity,
            "status": self.status,
            "matched": list(self.matched),
            "missingDocs": list(self.missing_docs),
            "details": self.details,
            "remediation": self.remediation,
        }


def evaluate_compliance(
    present_doc_types: Iterable[str],
    ctx: LoanContext,
) -> list[Finding]:
    """Evaluate every applicable rule against the document inventory.

    `present_doc_types` is a flat iterable of human-readable doc-type labels
    (e.g. `["Form 1003", "Paystubs"]`). The caller is responsible for resolving
    package stacks → labels (the mapping is stable: `LOStack.doc_type` already
    holds the human-readable label per the prototype).
    """
    present = set(present_doc_types)
    findings: list[Finding] = []
    for rule in COMPLIANCE_CHECKS:
        if not _rule_applies(rule, ctx):
            continue
        requires = rule.requires
        matched = tuple(r for r in requires if r in present)
        missing = tuple(r for r in requires if r not in present)
        if rule.requires_mode == RequiresMode.PROCESS or not requires:
            status = Status.ATTESTATION_REQUIRED.value
        elif rule.requires_mode == RequiresMode.ANY:
            status = Status.COMPLIANT.value if matched else Status.MISSING.value
        else:  # ALL
            if len(matched) == len(requires):
                status = Status.COMPLIANT.value
            elif matched:
                status = Status.PARTIAL.value
            else:
                status = Status.MISSING.value
        findings.append(Finding(
            id=rule.id,
            category=rule.category,
            regulation=rule.regulation,
            requirement=rule.requirement,
            requires=requires,
            requires_mode=rule.requires_mode.value,
            severity=rule.severity.value,
            status=status,
            matched=matched,
            missing_docs=missing,
            details=rule.details,
            remediation=rule.remediation,
        ))
    return findings


def summarize_compliance(findings: list[Finding]) -> dict:
    """Summary counts + open critical list (matches prototype shape)."""
    counts = {
        Status.COMPLIANT.value: 0,
        Status.PARTIAL.value: 0,
        Status.MISSING.value: 0,
        Status.ATTESTATION_REQUIRED.value: 0,
    }
    open_criticals: list[Finding] = []
    for f in findings:
        counts[f.status] = counts.get(f.status, 0) + 1
        if f.severity == Severity.CRITICAL.value and f.status != Status.COMPLIANT.value:
            open_criticals.append(f)
    return {
        "total": len(findings),
        "compliant": counts[Status.COMPLIANT.value],
        "partial": counts[Status.PARTIAL.value],
        "missing": counts[Status.MISSING.value],
        "attestation_required": counts[Status.ATTESTATION_REQUIRED.value],
        "open_criticals": [f.to_dict() for f in open_criticals],
        "open_criticals_count": len(open_criticals),
    }


def derive_lo_view(findings: list[Finding]) -> dict:
    """Loan-officer render: closeability traffic light + top-3 deal-killers
    + plain-English borrower-asks. Mirrors prototype lines 3389-3441."""
    open_findings = [f for f in findings if f.status != Status.COMPLIANT.value]
    open_critical_count = sum(1 for f in open_findings if f.severity == Severity.CRITICAL.value)

    if open_critical_count == 0:
        closeability = {
            "tone": "green",
            "label": "Clear to close",
            "message": "No critical compliance gaps detected for this scenario. Proceed to underwriting.",
        }
    elif open_critical_count <= 2:
        closeability = {
            "tone": "yellow",
            "label": "Conditional",
            "message": (
                f"{open_critical_count} critical item"
                f"{'' if open_critical_count == 1 else 's'} outstanding. "
                "Resolve before clear-to-close."
            ),
        }
    else:
        closeability = {
            "tone": "red",
            "label": "Not closeable yet",
            "message": (
                f"{open_critical_count} critical items outstanding. "
                "This loan cannot proceed to closing as-is."
            ),
        }
    closeability["open_critical_count"] = open_critical_count
    closeability["open_findings_count"] = len(open_findings)

    deal_killers = sorted(
        open_findings,
        key=lambda f: (
            SEVERITY_ORDER.get(f.severity, 9),
            STATUS_WEIGHT.get(f.status, 9),
            f.id,  # tiebreak — keeps order stable across runs
        ),
    )[:3]

    borrower_asks: list[dict] = []
    for f in open_findings:
        if f.requires_mode == RequiresMode.PROCESS.value:
            continue
        if not f.missing_docs:
            continue
        borrower_asks.append({
            "id": f.id,
            "severity": f.severity,
            "docs": list(f.missing_docs),
            "reason": f.requirement,
            "remediation": f.remediation,
        })

    return {
        "closeability": closeability,
        "deal_killers": [f.to_dict() for f in deal_killers],
        "borrower_asks": borrower_asks,
    }


def derive_qc_view(findings: list[Finding]) -> dict:
    """QC/compliance render: summary tiles + open criticals + findings grouped
    by category. Frontend renders this directly — no recomputation needed.

    Shape:
      {
        "summary_tiles": {total, compliant, partial, missing, attestation_required, open_criticals_count},
        "open_criticals": [Finding.to_dict, ...]   # sorted by severity, status, id
        "by_category": {category_label: [Finding.to_dict, ...]}  # sorted within
      }
    """
    counts = {
        Status.COMPLIANT.value: 0,
        Status.PARTIAL.value: 0,
        Status.MISSING.value: 0,
        Status.ATTESTATION_REQUIRED.value: 0,
    }
    for f in findings:
        counts[f.status] = counts.get(f.status, 0) + 1

    open_criticals = sorted(
        [
            f for f in findings
            if f.severity == Severity.CRITICAL.value
            and f.status != Status.COMPLIANT.value
        ],
        key=lambda f: (
            STATUS_WEIGHT.get(f.status, 9),
            f.id,
        ),
    )

    by_category: dict[str, list[Finding]] = {}
    for f in findings:
        by_category.setdefault(f.category, []).append(f)
    # Sort within each category: severity asc, then status weight asc, then id.
    by_category_serialized = {
        cat: [
            f.to_dict()
            for f in sorted(
                items,
                key=lambda f: (
                    SEVERITY_ORDER.get(f.severity, 9),
                    STATUS_WEIGHT.get(f.status, 9),
                    f.id,
                ),
            )
        ]
        for cat, items in by_category.items()
    }

    return {
        "summary_tiles": {
            "total": len(findings),
            "compliant": counts[Status.COMPLIANT.value],
            "partial": counts[Status.PARTIAL.value],
            "missing": counts[Status.MISSING.value],
            "attestation_required": counts[Status.ATTESTATION_REQUIRED.value],
            "open_criticals_count": len(open_criticals),
        },
        "open_criticals": [f.to_dict() for f in open_criticals],
        "by_category": by_category_serialized,
    }


# ── Cross-document consistency findings ────────────────────────────────────

# Candidate field labels to probe when looking for the borrower / applicant
# name on a stack — different doc types use different conventions.
_NAME_FIELD_CANDIDATES: tuple[str, ...] = (
    "Borrower Name",
    "Employee Name",
    "Account Holder",
    "Insured Name",
    "Buyer Name",
    "Taxpayer Name",
)


def _normalize_for_compare(value: str | None) -> str:
    """Normalize a string for cross-doc consistency comparison.

    Lower-cases and collapses runs of `[\\s,.\\-_/]` to single spaces, so
    "Jane M. Doe" / "jane m doe" / "Jane M Doe," all compare equal. Anything
    not in that punctuation set is preserved verbatim (so e.g. apartment
    glyphs survive).
    """
    if not value:
        return ""
    out: list[str] = []
    prev_space = False
    for ch in str(value).lower():
        if ch in " ,.-_/\t\n":
            if out and not prev_space:
                out.append(" ")
                prev_space = True
        else:
            out.append(ch)
            prev_space = False
    return "".join(out).strip()


def _effective_extraction_value(
    extraction: dict,
    field_name: str,
    override_map: dict[str, str],
) -> str | None:
    """Return the override > AI value for a named field on a stack, or None.

    Honors override semantics: an override with the empty string clears the
    AI value (the reviewer explicitly said "no value here"). Field rows with
    `status="missing"` are treated as absent.
    """
    key = f"{extraction.get('stack_id', '')}::{extraction.get('doc_type', '')}::{field_name}"
    if key in override_map:
        v = override_map[key]
        return v if v else None
    for row in extraction.get("fields") or []:
        # Field-name match is case-insensitive — different agents capitalize
        # differently and we don't want to require a one-true-spelling.
        if (row.get("name") or "").lower() != field_name.lower():
            continue
        if row.get("status") == "missing":
            return None
        v = row.get("value")
        return v if v else None
    return None


def _consistency_finding(
    *,
    extractions: list[dict],
    override_map: dict[str, str],
    field_candidates: tuple[str, ...],
    finding_id: str,
    requirement: str,
    severity: Severity,
    regulation: str,
    remediation: str,
    detail_prefix: str,
) -> "Finding | None":
    """Inner: emit one Finding when ≥2 stacks disagree on a value.

    `field_candidates` is probed in order on each stack; the first non-None
    value wins. Skips the `Others` bucket since unclassified pages aren't
    expected to have authoritative field values.
    """
    samples: list[tuple[str, str, str]] = []  # (doc_type, raw, normalized)
    for e in extractions:
        doc_type = e.get("doc_type") or ""
        if doc_type == OTHERS_DOC_TYPE_KEY:
            continue
        for fname in field_candidates:
            v = _effective_extraction_value(e, fname, override_map)
            if v:
                samples.append((doc_type, v, _normalize_for_compare(v)))
                break
    if len(samples) < 2:
        return None
    distinct = {s[2] for s in samples if s[2]}
    if len(distinct) <= 1:
        return None
    # Sort sample list for stable detail text + affected ordering.
    samples.sort(key=lambda s: (s[0], s[1]))
    detail = detail_prefix + "; ".join(
        f'{doc}: "{raw}"' for doc, raw, _ in samples
    )
    affected = tuple(sorted({s[0] for s in samples}))
    return Finding(
        id=finding_id,
        category="Data Integrity",
        regulation=regulation,
        requirement=requirement,
        requires=affected,
        requires_mode=RequiresMode.PROCESS.value,
        severity=severity.value,
        status=Status.MISSING.value,
        matched=(),
        missing_docs=(),
        details=detail,
        remediation=remediation,
    )


def derive_cross_doc_findings(
    extractions: list[dict],
    overrides: list[dict],
) -> list["Finding"]:
    """Cross-document consistency checks across the package's extractions.

    Compares effective (override > AI) values across stacks for:
      1. Borrower / applicant name (probes a list of candidate field labels)
      2. Loan amount
      3. Subject property address

    Returns 0–3 `Finding`s under category "Data Integrity". Empty list when
    no mismatches are detected (or when fewer than 2 stacks have a value
    for the field). Pure function — no I/O.

    `extractions` shape: `[{stack_id, doc_type, fields: [{name, value, status}, ...]}, ...]`
    `overrides`   shape: `[{stack_id, doc_type, field_name, value}, ...]`
    """
    override_map: dict[str, str] = {
        f"{o['stack_id']}::{o['doc_type']}::{o['field_name']}": o["value"]
        for o in overrides
    }
    out: list[Finding] = []

    f = _consistency_finding(
        extractions=extractions,
        override_map=override_map,
        field_candidates=_NAME_FIELD_CANDIDATES,
        finding_id="data_integrity_name_mismatch",
        requirement="Borrower / applicant name consistent across documents",
        severity=Severity.MEDIUM,
        regulation="Underwriting / fraud-prevention standard",
        remediation=(
            "Confirm correct legal name on the URLA; obtain a Name Affidavit / "
            "AKA if needed; review for potential identity-theft red flags."
        ),
        detail_prefix="Different name spellings were extracted across documents: ",
    )
    if f is not None:
        out.append(f)

    f = _consistency_finding(
        extractions=extractions,
        override_map=override_map,
        field_candidates=("Loan Amount",),
        finding_id="data_integrity_loan_amount_mismatch",
        requirement="Loan amount consistent across documents",
        severity=Severity.HIGH,
        regulation="TRID tolerances; underwriting integrity",
        remediation=(
            "Reconcile the URLA, LE, CD, and Note. TRID zero / 10% tolerances "
            "may apply if the difference reflects a fee change."
        ),
        detail_prefix="Loan amount values differ across documents: ",
    )
    if f is not None:
        out.append(f)

    f = _consistency_finding(
        extractions=extractions,
        override_map=override_map,
        field_candidates=("Property Address",),
        finding_id="data_integrity_property_address_mismatch",
        requirement="Subject property address consistent across documents",
        severity=Severity.HIGH,
        regulation="Underwriting / collateral integrity",
        remediation=(
            "Reconcile against the appraisal and title commitment. The legal "
            "description on the deed/title controls; cosmetic differences "
            "(Apt vs #) can be reconciled with a name/address affidavit."
        ),
        detail_prefix="Subject property address values differ across documents: ",
    )
    if f is not None:
        out.append(f)

    return out


# ── Validation-failure passthrough findings ────────────────────────────────

# Map a failed preset rule_id → (compliance category, severity). Preset rules
# come from `services/validation_presets.py`; if a new preset is added there
# without an entry here, the rule still surfaces as a finding but uses the
# `_VALIDATION_DEFAULT_*` fallback so the loan officer still sees it.
_PRESET_FINDING_MAP: dict[str, tuple[str, "Severity"]] = {
    "missing_signatures": ("Package Completeness", Severity.HIGH),
    "missing_pages": ("Package Completeness", Severity.HIGH),
    "missing_fields": ("Data Integrity", Severity.MEDIUM),
}

# Custom (NL) validation rules don't have a fixed severity — they're authored
# per-package by the LO. Treat them as Package-Completeness/MEDIUM by default.
_CUSTOM_VALIDATION_CATEGORY = "Package Completeness"
_CUSTOM_VALIDATION_SEVERITY = Severity.MEDIUM

# Fallback for unknown preset rule_ids (defensive — keeps the finding visible
# rather than silently dropping it).
_VALIDATION_DEFAULT_CATEGORY = "Package Completeness"
_VALIDATION_DEFAULT_SEVERITY = Severity.MEDIUM


def derive_validation_findings(
    validation_results: list[dict],
) -> list["Finding"]:
    """Surface failed per-stack validation rules as compliance findings.

    `validation_results` is a list of pre-flattened LOValidationResult dicts:
        [
          {
            "stack_id": str,
            "doc_type": str,
            "rules_evaluated": [
                {"rule_id": str, "rule_source": "preset"|"custom",
                 "passed": bool, "evidence": str, ...},
                ...
            ],
            ...
          },
          ...
        ]

    One finding is emitted per failed rule. Findings are deterministic — sorted
    by `(stack_id, rule_id)` so the JSON-serialized output is byte-stable for
    identical inputs. The `Others` reserved bucket is skipped (its presets
    short-circuit to `passed=True` in validation_presets — defense in depth).
    """
    out: list[Finding] = []
    # Sort by (stack_id, rule_id) for deterministic ordering.
    rows = sorted(
        validation_results or [],
        key=lambda r: (str(r.get("stack_id") or ""), str(r.get("doc_type") or "")),
    )
    for vr in rows:
        stack_id = str(vr.get("stack_id") or "")
        doc_type = vr.get("doc_type") or ""
        if doc_type == OTHERS_DOC_TYPE_KEY:
            continue
        rules = sorted(
            vr.get("rules_evaluated") or [],
            key=lambda r: (str(r.get("rule_source") or ""), str(r.get("rule_id") or "")),
        )
        for rule in rules:
            if rule.get("passed", True):
                continue
            rule_id = str(rule.get("rule_id") or "")
            rule_source = str(rule.get("rule_source") or "preset")
            evidence = str(rule.get("evidence") or "")
            if rule_source == "custom":
                category = _CUSTOM_VALIDATION_CATEGORY
                severity = _CUSTOM_VALIDATION_SEVERITY
            else:
                category, severity = _PRESET_FINDING_MAP.get(
                    rule_id,
                    (_VALIDATION_DEFAULT_CATEGORY, _VALIDATION_DEFAULT_SEVERITY),
                )
            requirement = (
                f"Validation rule '{rule_id}' must pass for {doc_type}"
                if doc_type
                else f"Validation rule '{rule_id}' must pass"
            )
            details = (
                f"Stack failed validation rule '{rule_id}' ({rule_source}). "
                f"Evidence: {evidence}"
            ) if evidence else (
                f"Stack failed validation rule '{rule_id}' ({rule_source})."
            )
            remediation = (
                "Resolve the failing validation rule on the stack, then re-run "
                "validation. If the failure is incorrect, route to human review."
            )
            # Stable, scoped id — multiple stacks failing the same rule each
            # produce a separate finding.
            finding_id = f"validation_{rule_id}_{stack_id}"
            out.append(Finding(
                id=finding_id,
                category=category,
                regulation="Per-package validation rules",
                requirement=requirement,
                requires=(doc_type,) if doc_type else (),
                requires_mode=RequiresMode.PROCESS.value,
                severity=severity.value,
                status=Status.MISSING.value,
                matched=(),
                missing_docs=(),
                details=details[:500],
                remediation=remediation,
            ))
    return out


def derive_low_conf_stack_findings(
    stack_data: list[dict],
    hitl_threshold: float,
) -> list["Finding"]:
    """Emit one finding per stack whose overall_confidence is below threshold.

    `stack_data` is the same flattened shape consumed by `derive_doc_checks`
    plus a `stack_id` key — caller is responsible for including the id when
    flattening LOStack rows.

    Skips:
      - The `Others` reserved bucket (HITL is forced upstream).
      - Stacks already `accepted` by a reviewer (decision is final).

    Findings are sorted by `(stack_index, stack_id)` for byte-deterministic
    output across runs.
    """
    out: list[Finding] = []
    rows = sorted(
        stack_data or [],
        key=lambda s: (int(s.get("stack_index") or 0), str(s.get("stack_id") or "")),
    )
    for s in rows:
        doc_type = s.get("doc_type") or ""
        if doc_type == OTHERS_DOC_TYPE_KEY:
            continue
        status_lower = str(s.get("status") or "").lower()
        if status_lower == "accepted":
            continue
        conf_value = float(s.get("overall_confidence") or 0.0)
        if conf_value >= hitl_threshold:
            continue
        stack_id = str(s.get("stack_id") or "")
        finding_id = f"lowconf_{stack_id}" if stack_id else f"lowconf_idx_{s.get('stack_index')}"
        details = (
            f"Stack confidence {conf_value * 100:.0f}% is below the "
            f"{hitl_threshold * 100:.0f}% HITL threshold for {doc_type or 'this stack'}."
        )
        out.append(Finding(
            id=finding_id,
            category="Confidence",
            regulation="Internal QC threshold",
            requirement="Stack confidence at or above HITL threshold",
            requires=(doc_type,) if doc_type else (),
            requires_mode=RequiresMode.PROCESS.value,
            severity=Severity.MEDIUM.value,
            status=Status.MISSING.value,
            matched=(),
            missing_docs=(),
            details=details,
            remediation=(
                "Route the stack to human review (HITL queue) for accept / "
                "reject / reclassify; reviewer acceptance closes this finding."
            ),
        ))
    return out


# ── Regulations + doc-check projections ────────────────────────────────────

# Reserved bucket for pages the classifier couldn't slot into a configured
# doc type; mirrors the frontend `OTHERS_DOC_TYPE_KEY` constant. Doc checks
# always skip this bucket — it isn't a document the borrower can supply.
OTHERS_DOC_TYPE_KEY = "Others"


def _slugify_category(category: str) -> str:
    """Stable id for a regulatory category — lowercase, underscores, ascii.

    Used as the `id` field on `RegulationSummary` rows so the frontend can
    key on a non-localized identifier even though the human label may evolve.
    """
    out: list[str] = []
    prev_us = False
    for ch in category.lower():
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif out and not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_") or "uncategorized"


def derive_regulations(ctx: LoanContext) -> list[dict]:
    """Project the rule library into a per-category regulation summary.

    Categories are derived from `COMPLIANCE_CHECKS`; a category is `applicable`
    when at least one rule in it passes `_rule_applies(rule, ctx)`. Citations
    inside a category are deduped + sorted so the output is byte-stable for
    the same `(rules, ctx)` pair.

    Shape (one row per category):
      {id, name, citation, applicable, rationale}
    """
    by_cat: dict[str, list[ComplianceRule]] = {}
    for rule in COMPLIANCE_CHECKS:
        by_cat.setdefault(rule.category, []).append(rule)

    rows: list[dict] = []
    for category in sorted(by_cat.keys()):
        rules = by_cat[category]
        applicable_rules = [r for r in rules if _rule_applies(r, ctx)]
        applicable = bool(applicable_rules)
        citations = sorted({r.regulation for r in rules})
        if not applicable:
            rationale = "Does not apply to this loan scenario."
        elif len(applicable_rules) == len(rules):
            rationale = (
                "Always applicable to consumer mortgages."
                if len(rules) == 1
                else f"All {len(rules)} rules in this category apply."
            )
        else:
            rationale = (
                f"{len(applicable_rules)} of {len(rules)} rules in this "
                "category apply to this scenario."
            )
        rows.append({
            "id": _slugify_category(category),
            "name": category,
            "citation": "; ".join(citations),
            "applicable": applicable,
            "rationale": rationale,
        })
    return rows


# Sort weight for `derive_doc_checks` rows: missing-required first, then
# needs_review, low_confidence, ok. Required docs of a given status outrank
# optional docs of the same status (the `-0.5` adjustment in the sort key).
_DOC_CHECK_STATUS_ORDER: dict[str, int] = {
    "missing": 0,
    "needs_review": 1,
    "low_confidence": 2,
    "ok": 3,
}


def derive_doc_checks(
    stack_data: list[dict],
    doc_type_specs: list[dict],
    hitl_threshold: float,
) -> list[dict]:
    """Map the per-package doc-type spec onto the actual stacks produced.

    `stack_data` is a list of pre-serialized stack dicts (the service layer
    flattens `LOStack` rows so this module stays I/O-free). Each entry must
    have keys `doc_type`, `page_count`, `overall_confidence`, `status`.

    `doc_type_specs` is the per-package config: `[{key, label, required}, ...]`
    (matches `LODocTypeConfig.doc_types`). Missing required docs surface at the
    top of the returned list — the loan officer's "borrower asks" list.

    The `Others` bucket is intentionally skipped — it's the catch-all for
    unclassified pages, not a document type the borrower can supply.
    """
    # Match by key first, fall back to label. Both conventions exist depending
    # on whether the classifier wrote the spec key or the human label.
    by_doc_type: dict[str, dict] = {}
    for s in stack_data:
        dt = s.get("doc_type")
        if dt:
            # First write wins — preserves earliest stack_index.
            by_doc_type.setdefault(dt, s)

    rows: list[dict] = []
    for spec in doc_type_specs:
        key = (spec.get("key") or "").strip()
        label = (spec.get("label") or key).strip()
        required = bool(spec.get("required", False))
        if key == OTHERS_DOC_TYPE_KEY or label == OTHERS_DOC_TYPE_KEY:
            continue

        stack = by_doc_type.get(key) or by_doc_type.get(label)
        notes: list[str] = []
        if stack is None:
            status = "missing"
            page_count = 0
            confidence: float | None = None
            if required:
                notes.append("Required by package configuration")
        else:
            page_count = int(stack.get("page_count") or 0)
            confidence = stack.get("overall_confidence")
            stack_status = (stack.get("status") or "").lower()
            conf_value = float(confidence or 0.0)
            if stack_status == "needs_review":
                status = "needs_review"
                notes.append("Routed to review queue")
            elif conf_value < hitl_threshold and stack_status != "accepted":
                status = "low_confidence"
                notes.append(
                    f"Confidence {conf_value * 100:.0f}% below "
                    f"{hitl_threshold * 100:.0f}% threshold"
                )
            else:
                status = "ok"

        rows.append({
            "docKey": key,
            "docLabel": label,
            "required": required,
            "submitted": stack is not None,
            "pageCount": page_count,
            "confidence": confidence,
            "status": status,
            "notes": notes,
        })

    # Sort: missing-required first, then needs_review, low_confidence, ok.
    # Required docs of a given status outrank optional docs of the same status.
    rows.sort(
        key=lambda r: (
            _DOC_CHECK_STATUS_ORDER.get(r["status"], 9) - (0.5 if r["required"] else 0.0),
            r["docLabel"],
        )
    )
    return rows


# ── Determinism: rule_set_hash ─────────────────────────────────────────────

def compute_rule_set_hash() -> str:
    """Content fingerprint over every rule's static fields.

    Note: `when` predicates are lambdas and intentionally excluded from the
    digest. To preserve determinism, the convention is:
      - Any change to a `when` predicate's logic MUST bump `RULES_VERSION`.
      - Adding/removing a rule, or changing requires/requires_mode/severity/
        category/regulation/requirement/details/remediation flips this hash
        automatically.
      - The hash also includes whether each rule has a `when` (a marker bit)
        so adding/removing the predicate itself is detected.

    Persisted on `LOComplianceRun.rule_set_hash` alongside `RULES_VERSION` and
    a snapshot of the loan context + doc inventory; all four together are the
    determinism contract for re-runs.
    """
    payload = {
        "rules_version": RULES_VERSION,
        "rules": [
            {
                "id": r.id,
                "category": r.category,
                "regulation": r.regulation,
                "requirement": r.requirement,
                "requires": list(r.requires),
                "requires_mode": r.requires_mode.value,
                "severity": r.severity.value,
                "details": r.details,
                "remediation": r.remediation,
                "has_when": r.when is not None,
            }
            for r in COMPLIANCE_CHECKS
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()




