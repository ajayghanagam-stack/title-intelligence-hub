/**
 * Compliance report types + adapter from the backend payload.
 *
 * The compliance rule engine lives in the backend (`compliance_rules.py` +
 * `compliance_service.py`) — there is exactly one source of truth for the
 * rule library, severity weights, citations, and projections (LO view, QC
 * view, regulations, doc-checks). The frontend used to mirror that logic
 * here in TypeScript; that copy was deleted to eliminate drift.
 *
 * What remains:
 *  - The `ComplianceReport` type the LO + QC view components consume.
 *  - `adaptComplianceReport(payload, pkg)` — pure function that maps the
 *    backend wire payload (`ComplianceRunPayload`, defined in `api.ts`)
 *    into the legacy `ComplianceReport` shape so we can swap in the API
 *    without touching the rendering layer.
 *
 * The `ComplianceCategory` union was widened to `string` because the backend
 * rule library owns the category vocabulary and adds new categories (e.g.
 * "Confidence", "Package Completeness", "Data Integrity") without coordination
 * with this file.
 */
import type { ComplianceRunPayload } from "./api";
import type { LoanPackage } from "./types";

export type ComplianceSeverity =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "info"
  | "pass";

/**
 * Free-form regulatory category label. The backend rule library is the source
 * of truth (e.g. "TRID Disclosures", "Ability-to-Repay (ATR/QM)", "FHA
 * Program", "State Overlays", "Confidence", "Package Completeness", "Data
 * Integrity"). We intentionally widened this from a strict union so adding a
 * new backend category doesn't require a frontend type change.
 */
export type ComplianceCategory = string;

export interface ComplianceFinding {
  id: string;
  ruleId: string;
  category: ComplianceCategory;
  severity: ComplianceSeverity;
  title: string;
  detail: string;
  citation: string;
  remediation: string;
  affectedDocs: string[];
}

export interface RegulationSummary {
  id: ComplianceCategory;
  name: string;
  citation: string;
  applicable: boolean;
  rationale: string;
}

export interface DocCheckRow {
  docKey: string;
  docLabel: string;
  required: boolean;
  submitted: boolean;
  pageCount: number;
  confidence: number | null;
  status: "ok" | "missing" | "low_confidence" | "needs_review";
  notes: string[];
}

export type OverallStatus = "pass" | "needs_attention" | "fail";

/** Traffic-light closeability tone — render-side enum. */
export type CloseabilityTone = "ready" | "review" | "blocked";

export interface CloseabilityState {
  tone: CloseabilityTone;
  label: string;
  headline: string;
  detail: string;
  criticalCount: number;
  highCount: number;
}

/** A finding the LO needs to act on before submitting. Subset of ComplianceFinding. */
export interface DealKiller {
  id: string;
  title: string;
  category: ComplianceCategory;
  severity: ComplianceSeverity;
  remediation: string;
  citation: string;
}

/** A document the borrower should produce (derived from missing required docs). */
export interface BorrowerAsk {
  docKey: string;
  docLabel: string;
  reason: string;
}

/** Loan Officer–oriented projection of the report. */
export interface LoView {
  closeability: CloseabilityState;
  dealKillers: DealKiller[];
  borrowerAsks: BorrowerAsk[];
}

/** A summary tile for the QC dashboard. */
export interface QcSummaryTile {
  key: "total" | "critical" | "high" | "medium" | "low";
  label: string;
  count: number;
}

/** A grouped findings bucket for QC review. */
export interface QcCategoryGroup {
  category: ComplianceCategory;
  categoryName: string;
  findings: ComplianceFinding[];
}

/** QC / Compliance reviewer–oriented projection of the report. */
export interface QcView {
  summaryTiles: QcSummaryTile[];
  openCriticals: ComplianceFinding[];
  byCategory: QcCategoryGroup[];
}

export interface ComplianceReport {
  packageId: string;
  packageName: string;
  loanReference: string | null;
  borrowerName: string | null;
  /** ISO timestamp — wall-clock, NOT part of the determinism contract. */
  generatedAt: string;
  /** Backend rules engine version (`lo_compliance_rules_v2` etc.). */
  rulesVersion: string;
  /** Backend rule_set_hash — content fingerprint over the rule library. */
  contentHash: string;
  summary: {
    overallStatus: OverallStatus;
    findingsBySeverity: Record<ComplianceSeverity, number>;
    totalFindings: number;
  };
  regulations: RegulationSummary[];
  findings: ComplianceFinding[];
  docChecks: DocCheckRow[];
  /** Loan Officer view — what to fix and what to ask the borrower for. */
  loView: LoView;
  /** QC / Compliance reviewer view — audit-style breakdown by category. */
  qcView: QcView;
}

const SEVERITY_RANK: Record<ComplianceSeverity, number> = {
  critical: 5,
  high: 4,
  medium: 3,
  low: 2,
  info: 1,
  pass: 0,
};

export function severityRank(s: ComplianceSeverity): number {
  return SEVERITY_RANK[s];
}

// ── Adapter: backend ComplianceRunPayload → frontend ComplianceReport ────

const TONE_MAP: Record<"green" | "yellow" | "red", CloseabilityTone> = {
  green: "ready",
  yellow: "review",
  red: "blocked",
};

function _mapFinding(
  f: ComplianceRunPayload["findings"][number]
): ComplianceFinding {
  // affectedDocs prefers the matched-doc list (compliant or partial findings
  // already carry the matched names) and falls back to `requires` so the
  // finding always carries some doc context for the QC reviewer.
  const docs = f.matched.length ? f.matched : f.requires;
  return {
    id: f.id,
    ruleId: f.id,
    category: f.category,
    severity: f.severity,
    title: f.requirement,
    detail: f.details,
    citation: f.regulation,
    remediation: f.remediation,
    affectedDocs: docs,
  };
}

function _deriveOverallStatus(
  findings: ComplianceFinding[]
): OverallStatus {
  let hasCritical = false;
  let hasOpen = false;
  for (const f of findings) {
    if (f.severity === "critical") {
      hasCritical = true;
    }
    if (
      f.severity === "critical" ||
      f.severity === "high" ||
      f.severity === "medium"
    ) {
      hasOpen = true;
    }
  }
  if (hasCritical) return "fail";
  if (hasOpen) return "needs_attention";
  return "pass";
}

function _findingsBySeverity(
  findings: ComplianceFinding[]
): Record<ComplianceSeverity, number> {
  const acc: Record<ComplianceSeverity, number> = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    info: 0,
    pass: 0,
  };
  for (const f of findings) {
    acc[f.severity] = (acc[f.severity] ?? 0) + 1;
  }
  return acc;
}

function _summaryTiles(
  bySeverity: Record<ComplianceSeverity, number>,
  total: number
): QcSummaryTile[] {
  return [
    { key: "total", label: "Total", count: total },
    { key: "critical", label: "Critical", count: bySeverity.critical },
    { key: "high", label: "High", count: bySeverity.high },
    { key: "medium", label: "Medium", count: bySeverity.medium },
    { key: "low", label: "Low", count: bySeverity.low },
  ];
}

function _byCategoryGroups(
  byCategory: Record<string, ComplianceRunPayload["findings"]>
): QcCategoryGroup[] {
  const out: QcCategoryGroup[] = [];
  // Sort categories alphabetically so render order is stable between runs.
  const cats = Object.keys(byCategory).sort();
  for (const cat of cats) {
    const findings = (byCategory[cat] ?? []).map(_mapFinding);
    if (findings.length === 0) continue;
    out.push({
      category: cat,
      categoryName: cat, // backend already supplies a human-readable label
      findings,
    });
  }
  return out;
}

function _dealKillerFromFinding(
  f: ComplianceRunPayload["findings"][number]
): DealKiller {
  return {
    id: f.id,
    title: f.requirement,
    category: f.category,
    severity: f.severity,
    remediation: f.remediation,
    citation: f.regulation,
  };
}

function _borrowerAsk(
  ask: ComplianceRunPayload["lo_view"]["borrower_asks"][number]
): BorrowerAsk {
  // Backend emits `docs: string[]` per ask; the LO view shows one line per
  // doc, so fan a multi-doc ask into multiple rows on the caller side. Here
  // we collapse to the first doc to keep the type contract; the backend
  // already groups by rule so multiple docs per ask is rare in practice.
  const docKey = ask.docs[0] ?? "";
  return {
    docKey,
    docLabel: docKey,
    reason: ask.reason,
  };
}

function _expandBorrowerAsks(
  asks: ComplianceRunPayload["lo_view"]["borrower_asks"]
): BorrowerAsk[] {
  // Fan out: one row per (rule, doc) pair so the LO sees every doc explicitly.
  const out: BorrowerAsk[] = [];
  for (const a of asks) {
    if (a.docs.length === 0) {
      out.push(_borrowerAsk(a));
      continue;
    }
    for (const doc of a.docs) {
      out.push({ docKey: doc, docLabel: doc, reason: a.reason });
    }
  }
  return out;
}

/**
 * Map the backend compliance payload into the `ComplianceReport` shape the
 * LO + QC views consume. Pure function — no state, no I/O. Safe to call from
 * `useEffect` and from server-rendered code.
 *
 * `pkg` is optional; when present it backfills the package_name / borrower /
 * loan_reference fields if the backend response omits them (older runs).
 */
export function adaptComplianceReport(
  payload: ComplianceRunPayload,
  pkg?: LoanPackage | null
): ComplianceReport {
  const findings = payload.findings.map(_mapFinding);
  const bySeverity = _findingsBySeverity(findings);
  const overallStatus = _deriveOverallStatus(findings);

  const closeability: CloseabilityState = {
    tone: TONE_MAP[payload.lo_view.closeability.tone] ?? "review",
    label: payload.lo_view.closeability.label,
    headline: payload.lo_view.closeability.label,
    detail: payload.lo_view.closeability.message,
    criticalCount: payload.lo_view.closeability.open_critical_count,
    highCount: bySeverity.high,
  };

  const dealKillers = payload.lo_view.deal_killers.map(_dealKillerFromFinding);
  const borrowerAsks = _expandBorrowerAsks(payload.lo_view.borrower_asks);

  const qcOpenCriticals = (payload.qc_view?.open_criticals ?? []).map(
    _mapFinding
  );
  const qcByCategory = _byCategoryGroups(payload.qc_view?.by_category ?? {});

  const summaryTiles = _summaryTiles(
    bySeverity,
    payload.qc_view?.summary_tiles.total ?? findings.length
  );

  const docChecks: DocCheckRow[] = (payload.doc_checks ?? []).map((d) => ({
    docKey: d.docKey,
    docLabel: d.docLabel,
    required: d.required,
    submitted: d.submitted,
    pageCount: d.pageCount,
    confidence: d.confidence,
    status: d.status,
    notes: d.notes,
  }));

  const regulations: RegulationSummary[] = (payload.regulations ?? []).map(
    (r) => ({
      id: r.id,
      name: r.name,
      citation: r.citation,
      applicable: r.applicable,
      rationale: r.rationale,
    })
  );

  return {
    packageId: payload.package_id,
    packageName:
      payload.package_name ?? pkg?.name ?? "",
    loanReference:
      payload.loan_reference ?? pkg?.loan_reference ?? null,
    borrowerName:
      payload.borrower_name ?? pkg?.borrower_name ?? null,
    generatedAt: payload.created_at ?? new Date().toISOString(),
    rulesVersion: payload.rules_version,
    contentHash: payload.rule_set_hash,
    summary: {
      overallStatus,
      findingsBySeverity: bySeverity,
      totalFindings: payload.summary.total,
    },
    regulations,
    findings,
    docChecks,
    loView: {
      closeability,
      dealKillers,
      borrowerAsks,
    },
    qcView: {
      summaryTiles,
      openCriticals: qcOpenCriticals,
      byCategory: qcByCategory,
    },
  };
}
