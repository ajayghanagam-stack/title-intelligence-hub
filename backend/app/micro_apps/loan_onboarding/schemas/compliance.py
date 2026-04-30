"""Pydantic schemas for the compliance API.

All enums are closed sets (`Literal[...]`) so the OpenAPI spec is precise and
the frontend can rely on a stable type surface. Wire format mirrors the
prototype's camelCase keys (`requiresMode`, `missingDocs`, `scenarioFlags`,
`ausWaivers`, etc.) to make the rendered payload drop-in compatible with the
existing UI logic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
Status = Literal["compliant", "partial", "missing", "attestation_required"]
RequiresMode = Literal["all", "any", "process"]


class LoanContextIn(BaseModel):
    """Editable loan context — what the loan officer sets on the upload form."""
    program: str = "conv"
    purpose: str = "purchase"
    occupancy: str = "primary"
    state: str = "CT"
    scenarioFlags: list[str] = Field(default_factory=list)
    ausEngine: str = "du"
    ausWaivers: list[str] = Field(default_factory=list)
    loanAmount: float | None = None
    propertyValue: float | None = None


class LoanContextOut(LoanContextIn):
    """Same shape as in — the API echoes the persisted snapshot."""
    pass


class Finding(BaseModel):
    id: str
    category: str
    regulation: str
    requirement: str
    requires: list[str]
    requiresMode: RequiresMode
    severity: Severity
    status: Status
    matched: list[str]
    missingDocs: list[str]
    details: str
    remediation: str


class CloseabilityCard(BaseModel):
    tone: Literal["green", "yellow", "red"]
    label: str
    message: str
    open_critical_count: int
    open_findings_count: int


class BorrowerAsk(BaseModel):
    id: str
    severity: Severity
    docs: list[str]
    reason: str
    remediation: str


class LOView(BaseModel):
    """LO render lens — closeability + top-3 deal-killers + borrower asks."""
    closeability: CloseabilityCard
    deal_killers: list[Finding]
    borrower_asks: list[BorrowerAsk]


class ComplianceSummary(BaseModel):
    total: int
    compliant: int
    partial: int
    missing: int
    attestation_required: int
    open_criticals: list[Finding]
    open_criticals_count: int


class QcSummaryTiles(BaseModel):
    total: int
    compliant: int
    partial: int
    missing: int
    attestation_required: int
    open_criticals_count: int


class QcView(BaseModel):
    """QC reviewer render lens — summary tiles + criticals + grouped findings."""
    summary_tiles: QcSummaryTiles
    open_criticals: list[Finding]
    # Free-form category labels (e.g. "TRID Disclosures") → findings in that
    # category. The frontend will widen its `ComplianceCategory` enum to
    # accept arbitrary strings; see compliance_rules.py for the source list.
    by_category: dict[str, list[Finding]]


class RegulationSummary(BaseModel):
    id: str
    name: str
    citation: str
    applicable: bool
    rationale: str


DocCheckStatus = Literal["ok", "missing", "low_confidence", "needs_review"]


class DocCheckRow(BaseModel):
    docKey: str
    docLabel: str
    required: bool
    submitted: bool
    pageCount: int
    confidence: float | None = None
    status: DocCheckStatus
    notes: list[str]


class ComplianceRunOut(BaseModel):
    """Full render payload returned by GET /compliance and POST /evaluate."""
    run_id: str | None = None
    package_id: str
    # Package identity — handy on the frontend so the report header doesn't
    # need a second fetch. Optional for backward compat with older callers.
    package_name: str | None = None
    loan_reference: str | None = None
    borrower_name: str | None = None
    rules_version: str
    rule_set_hash: str
    loan_context_snapshot: LoanContextOut
    doc_inventory_snapshot: list[str]
    summary: ComplianceSummary
    findings: list[Finding]
    lo_view: LOView
    qc_view: QcView | None = None
    regulations: list[RegulationSummary] | None = None
    doc_checks: list[DocCheckRow] | None = None
    created_at: datetime | None = None
