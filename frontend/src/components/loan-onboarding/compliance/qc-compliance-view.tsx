"use client";

import { useMemo, useState } from "react";
import {
  AlertOctagon,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import type {
  ComplianceFinding,
  ComplianceReport,
  ComplianceSeverity,
  DocCheckRow,
  QcCategoryGroup,
  QcSummaryTile,
} from "@/lib/loan-onboarding/compliance";
import { LOAN_DOC_TYPE_LABELS } from "@/lib/loan-onboarding/constants";
import { cn } from "@/lib/utils";
import {
  Pagination,
  usePagination,
} from "@/components/title-intelligence/pagination";

const PAGE_SIZE = 10;
const CATEGORY_PAGE_SIZE = 5;

const SEVERITY_STYLE: Record<
  ComplianceSeverity,
  { chip: string; dot: string; label: string }
> = {
  critical: {
    chip: "bg-red-50 text-red-700 ring-1 ring-red-200",
    dot: "bg-red-500",
    label: "Critical",
  },
  high: {
    chip: "bg-orange-50 text-orange-700 ring-1 ring-orange-200",
    dot: "bg-orange-500",
    label: "High",
  },
  medium: {
    chip: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
    dot: "bg-amber-500",
    label: "Medium",
  },
  low: {
    chip: "bg-yellow-50 text-yellow-800 ring-1 ring-yellow-200",
    dot: "bg-yellow-400",
    label: "Low",
  },
  info: {
    chip: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
    dot: "bg-sky-400",
    label: "Info",
  },
  pass: {
    chip: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    dot: "bg-emerald-500",
    label: "Pass",
  },
};

const TILE_TONE: Record<QcSummaryTile["key"], string> = {
  total: "bg-stone-50 ring-stone-200",
  critical: "bg-red-50 ring-red-200",
  high: "bg-orange-50 ring-orange-200",
  medium: "bg-amber-50 ring-amber-200",
  low: "bg-yellow-50 ring-yellow-200",
};

export function QcComplianceView({ report }: { report: ComplianceReport }) {
  return (
    <div className="space-y-6" data-testid="compliance-qc-view">
      <SummaryTiles tiles={report.qcView.summaryTiles} />
      <OpenCriticalsCallout findings={report.qcView.openCriticals} />
      <FindingsByCategory groups={report.qcView.byCategory} />
      <ApplicableRegulationsCard report={report} />
      <DocChecksCard report={report} />
    </div>
  );
}

function SummaryTiles({ tiles }: { tiles: QcSummaryTile[] }) {
  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-5 gap-3"
      data-testid="compliance-qc-tiles"
    >
      {tiles.map((t) => (
        <div
          key={t.key}
          className={cn(
            "rounded-md ring-1 px-4 py-3",
            TILE_TONE[t.key]
          )}
          data-testid={`compliance-qc-tile-${t.key}`}
        >
          <div className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
            {t.label}
          </div>
          <div className="text-2xl font-semibold tabular-nums mt-0.5 text-foreground">
            {t.count}
          </div>
        </div>
      ))}
    </div>
  );
}

function OpenCriticalsCallout({ findings }: { findings: ComplianceFinding[] }) {
  const [page, setPage] = useState(1);
  const { paginate, totalPages } = usePagination(findings, PAGE_SIZE);
  const visible = useMemo(() => paginate(page), [paginate, page]);

  if (findings.length === 0) {
    return (
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 flex items-start gap-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600 mt-0.5 shrink-0" />
        <div>
          <div className="font-medium text-emerald-900">
            No open critical findings
          </div>
          <div className="text-sm text-emerald-800/80">
            File has no must-fix issues. Continue with standard QC review.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div
      className="bg-red-50 border border-red-200 rounded-lg p-5"
      data-testid="compliance-qc-criticals"
    >
      <div className="flex items-center gap-2">
        <AlertOctagon className="h-5 w-5 text-red-600" />
        <div className="font-medium text-red-900">
          Open Critical Findings — must resolve before closing
        </div>
        <div className="ml-auto font-mono text-[10px] tracking-[0.15em] uppercase text-red-700 tabular-nums">
          {findings.length} item{findings.length === 1 ? "" : "s"}
        </div>
      </div>
      <ul className="mt-3 space-y-2">
        {visible.map((f) => (
          <li
            key={f.id}
            className="bg-white/80 rounded-md p-3 ring-1 ring-red-200"
          >
            <div className="flex items-start gap-2">
              <span className="h-2 w-2 rounded-full bg-red-500 mt-1.5 shrink-0" />
              <div className="min-w-0">
                <div className="font-medium text-[13px] text-foreground">
                  {f.title}
                </div>
                <div className="text-[12px] text-muted-foreground mt-0.5">
                  {f.detail}
                </div>
                <div className="font-mono text-[10px] text-muted-foreground mt-1">
                  {f.citation}
                </div>
              </div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3">
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalItems={findings.length}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}

function FindingsByCategory({ groups }: { groups: QcCategoryGroup[] }) {
  const [page, setPage] = useState(1);
  const { paginate, totalPages } = usePagination(groups, CATEGORY_PAGE_SIZE);
  const visibleGroups = useMemo(() => paginate(page), [paginate, page]);

  if (groups.length === 0) {
    return (
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 flex items-center gap-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600" />
        <div className="text-sm text-emerald-900">
          No findings produced — every applicable rule passed.
        </div>
      </div>
    );
  }
  return (
    <div
      className="bg-white border border-border rounded-lg overflow-hidden"
      data-testid="compliance-qc-by-category"
    >
      <div className="px-5 py-3 border-b border-border">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-muted-foreground">
          Findings by Regulatory Category
        </div>
        <div className="text-sm text-foreground mt-0.5">
          Audit-style breakdown for QC review
        </div>
      </div>
      <ul>
        {visibleGroups.map((g) => (
          <CategoryGroupRow key={g.category} group={g} />
        ))}
      </ul>
      {totalPages > 1 && (
        <div className="border-t border-border px-5 py-2">
          <Pagination
            currentPage={page}
            totalPages={totalPages}
            totalItems={groups.length}
            pageSize={CATEGORY_PAGE_SIZE}
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  );
}

function CategoryGroupRow({ group }: { group: QcCategoryGroup }) {
  const [open, setOpen] = useState(true);
  const [page, setPage] = useState(1);
  const { paginate, totalPages } = usePagination(group.findings, PAGE_SIZE);
  const visible = useMemo(() => paginate(page), [paginate, page]);
  const counts = group.findings.reduce<Record<ComplianceSeverity, number>>(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] ?? 0) + 1;
      return acc;
    },
    { critical: 0, high: 0, medium: 0, low: 0, info: 0, pass: 0 }
  );
  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center gap-3 hover:bg-stone-50 text-left"
        data-testid={`compliance-qc-group-${group.category}`}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
        <div className="font-medium text-[14px] text-foreground">
          {group.categoryName}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {(["critical", "high", "medium", "low", "info"] as ComplianceSeverity[])
            .filter((s) => counts[s] > 0)
            .map((s) => (
              <span
                key={s}
                className={cn(
                  "font-mono text-[9px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded",
                  SEVERITY_STYLE[s].chip
                )}
              >
                {counts[s]} {SEVERITY_STYLE[s].label}
              </span>
            ))}
        </div>
      </button>
      {open && (
        <div className="bg-stone-50/40">
          <ul>
            {visible.map((f) => (
              <FindingRow key={f.id} finding={f} />
            ))}
          </ul>
          {totalPages > 1 && (
            <div className="px-8 pb-3">
              <Pagination
                currentPage={page}
                totalPages={totalPages}
                totalItems={group.findings.length}
                pageSize={PAGE_SIZE}
                onPageChange={setPage}
              />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function FindingRow({ finding: f }: { finding: ComplianceFinding }) {
  const sev = SEVERITY_STYLE[f.severity];
  return (
    <li
      className="px-8 py-3 border-t border-border first:border-t-0"
      data-testid={`compliance-finding-${f.ruleId}`}
    >
      <div className="flex items-start gap-3">
        <span className={cn("h-2.5 w-2.5 rounded-full mt-1.5 shrink-0", sev.dot)} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                "font-mono text-[9px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded",
                sev.chip
              )}
            >
              {sev.label}
            </span>
          </div>
          <div className="font-medium text-[14px] text-foreground mt-1.5 leading-snug">
            {f.title}
          </div>
          <div className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
            {f.detail}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5 mt-2.5 text-[11px]">
            <div>
              <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground mr-1.5">
                Citation
              </span>
              <span className="font-mono text-foreground">{f.citation}</span>
            </div>
            <div>
              <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground mr-1.5">
                Remediation
              </span>
              <span className="text-foreground">{f.remediation}</span>
            </div>
          </div>
          {f.affectedDocs.length > 0 && (
            <div className="flex items-center gap-1.5 mt-2 flex-wrap">
              <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
                Documents
              </span>
              {f.affectedDocs.map((d) => (
                <span
                  key={d}
                  className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-stone-50 text-stone-700 ring-1 ring-stone-200"
                >
                  {LOAN_DOC_TYPE_LABELS[d] ?? d}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function ApplicableRegulationsCard({ report }: { report: ComplianceReport }) {
  const applicable = report.regulations.filter((r) => r.applicable);
  return (
    <div
      className="bg-white border border-border rounded-lg overflow-hidden"
      data-testid="compliance-regulations"
    >
      <div className="px-5 py-3 border-b border-border flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-muted-foreground">
            Applicable Regulatory Framework
          </div>
          <div className="text-sm text-foreground mt-0.5">
            Federal frameworks evaluated for this package
          </div>
        </div>
        <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-muted-foreground tabular-nums">
          {applicable.length} of {report.regulations.length}
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-0">
        {applicable.map((r, i) => (
          <div
            key={r.id}
            className={cn(
              "px-5 py-4 border-border",
              i % 2 === 0 ? "md:border-r" : "",
              "border-b last:border-b-0"
            )}
          >
            <div className="flex items-start gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <div className="font-medium text-sm text-foreground leading-tight">
                  {r.name}
                </div>
                <div className="font-mono text-[10px] text-muted-foreground mt-0.5">
                  {r.citation}
                </div>
                <div className="text-[12px] text-muted-foreground mt-1.5 leading-relaxed">
                  {r.rationale}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DocChecksCard({ report }: { report: ComplianceReport }) {
  const [page, setPage] = useState(1);
  const { paginate, totalPages } = usePagination(report.docChecks, PAGE_SIZE);
  const visible = useMemo(() => paginate(page), [paginate, page]);
  return (
    <div
      className="bg-white border border-border rounded-lg overflow-hidden"
      data-testid="compliance-doc-checks"
    >
      <div className="px-5 py-3 border-b border-border flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-muted-foreground">
            Document-level Compliance Checklist
          </div>
          <div className="text-sm text-foreground mt-0.5">
            Per-doc-type status against the package&apos;s required-doc list
          </div>
        </div>
        <div className="font-mono text-[10px] tracking-[0.15em] uppercase text-muted-foreground tabular-nums">
          {report.docChecks.filter((d) => d.submitted).length}/
          {report.docChecks.length} submitted
        </div>
      </div>
      <table className="w-full text-sm">
        <thead className="bg-stone-50 border-b border-border">
          <tr className="text-left">
            <th className="px-5 py-2 font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
              Document
            </th>
            <th className="px-3 py-2 font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
              Required
            </th>
            <th className="px-3 py-2 font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
              Submitted
            </th>
            <th className="px-3 py-2 font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground tabular-nums">
              Pages
            </th>
            <th className="px-3 py-2 font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground tabular-nums">
              Conf
            </th>
            <th className="px-3 py-2 font-mono text-[9px] tracking-[0.2em] uppercase text-muted-foreground">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {visible.map((d) => (
            <DocCheckRowEl key={d.docKey} row={d} />
          ))}
        </tbody>
      </table>
      <div className="px-5 py-3 border-t border-border">
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          totalItems={report.docChecks.length}
          pageSize={PAGE_SIZE}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}

function DocCheckRowEl({ row: d }: { row: DocCheckRow }) {
  const tone =
    d.status === "ok"
      ? "text-emerald-700"
      : d.status === "needs_review"
        ? "text-orange-700"
        : d.status === "low_confidence"
          ? "text-amber-700"
          : "text-red-700";
  return (
    <tr className="border-b border-border last:border-b-0 hover:bg-stone-50/50">
      <td className="px-5 py-2.5">
        <div className="font-medium text-foreground">{d.docLabel}</div>
        {d.notes.length > 0 && (
          <div className="text-[11px] text-muted-foreground mt-0.5">
            {d.notes.join(" · ")}
          </div>
        )}
      </td>
      <td className="px-3 py-2.5">
        {d.required ? (
          <span className="font-mono text-[10px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded bg-stone-100 text-stone-700 ring-1 ring-stone-200">
            Required
          </span>
        ) : (
          <span className="text-stone-400 text-xs">Optional</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {d.submitted ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        ) : (
          <XCircle className="h-4 w-4 text-stone-300" />
        )}
      </td>
      <td className="px-3 py-2.5 font-mono text-xs tabular-nums text-muted-foreground">
        {d.pageCount || "—"}
      </td>
      <td className="px-3 py-2.5 font-mono text-xs tabular-nums text-muted-foreground">
        {d.confidence !== null ? `${Math.round(d.confidence * 100)}%` : "—"}
      </td>
      <td className={cn("px-3 py-2.5 text-xs font-medium", tone)}>
        {d.status === "ok"
          ? "OK"
          : d.status === "needs_review"
            ? "Needs review"
            : d.status === "low_confidence"
              ? "Low confidence"
              : "Missing"}
      </td>
    </tr>
  );
}
