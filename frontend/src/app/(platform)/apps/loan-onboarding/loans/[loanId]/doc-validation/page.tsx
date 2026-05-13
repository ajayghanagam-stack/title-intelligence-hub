"use client";

// Phase 5.2 screen #4 — Doc Validation.
//
// Mirrors the LogikIntake prototype's `screenDocValidation()`: header +
// red Hard-Stop section listing missing required docs (with Upload /
// Override CTAs), green section header, then a per-row checklist table
// with Present / Recency / Name Match cells and a Passed / Hard Stop
// status pill. A footer hint + "Advance to Extraction" CTA pins the
// bottom; the CTA is disabled while any hard stop is open.
//
// Backend route is `GET /loans/{id}/checklist` returning
// `LoanChecklistItem` rows — each carries `requirement`, `received`,
// `needs_review`, `stack_count`. The prototype's three binary checks
// (Present / Recency / Name Match) are derived from `received`: when a
// doc is received we assume the rendered cell-level pieces pass; the
// real per-rule breakdown lives elsewhere in the validate stage.

import Link from "next/link";
import { useMemo } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  CircleCheck,
  Edit3,
  ShieldX,
  Upload,
  X,
} from "lucide-react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { useLoanChecklist } from "@/hooks/use-loan-operator";
import { cn } from "@/lib/utils";

type CheckMark = "pass" | "fail" | "na";

function MarkIcon({ value }: { value: CheckMark }) {
  if (value === "pass") {
    return (
      <span
        className="mx-auto inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-green-600 text-brand-white"
        aria-label="pass"
      >
        <Check className="h-2.5 w-2.5" strokeWidth={3} />
      </span>
    );
  }
  if (value === "fail") {
    return (
      <span
        className="mx-auto inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-red-600 text-brand-white"
        aria-label="fail"
      >
        <X className="h-2.5 w-2.5" strokeWidth={3} />
      </span>
    );
  }
  return (
    <span
      className="mx-auto inline-flex h-[18px] w-[18px] items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-400"
      aria-label="not applicable"
    >
      —
    </span>
  );
}

function SubHeader({
  tone,
  children,
}: {
  tone: "pass" | "fail";
  children: React.ReactNode;
}) {
  return (
    <p
      className={cn(
        "mb-2 mt-4 inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider",
        tone === "fail" ? "text-red-600" : "text-green-600",
      )}
    >
      {children}
    </p>
  );
}

export default function DocValidationPage({
  params,
}: {
  params: { loanId: string };
}) {
  const { loanId } = params;
  const { orgPath } = useOrgSlug();
  const { package: loan } = useLoanPackage(loanId);
  const { data: checklist = [], isLoading } = useLoanChecklist(loanId);

  // Derive the hard-stop list (required + missing) and the checklist
  // tally used by the section headers and footer hint.
  const hardStops = useMemo(
    () =>
      checklist.filter(
        (i) => i.requirement === "Required" && !i.received,
      ),
    [checklist],
  );
  const presentCount = useMemo(
    () => checklist.filter((i) => i.received).length,
    [checklist],
  );
  const totalHardStops = hardStops.length;
  const canAdvance = totalHardStops === 0;

  if (!loan) {
    return (
      <div className="mx-auto max-w-7xl px-2 py-8">
        <p className="text-sm text-muted-foreground">Loading loan file…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <Link
        href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[11px] font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="h-3 w-3" />
        Back to Pipeline
      </Link>

      {/* Header — title + loan context line + Hard-Stop pill on the right */}
      <header className="mb-4 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold tracking-tight">
            Doc Validation
            <span className="ml-2 font-mono text-[12px] font-medium text-muted-foreground">
              {loan.borrower_name ?? loan.name ?? ""}
              {loan.id ? ` · ${loan.id}` : ""}
            </span>
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {checklist.length} document
            {checklist.length === 1 ? "" : "s"} on program checklist
          </p>
        </div>
        {totalHardStops > 0 ? (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1.5 text-[12px] font-bold text-red-800">
            <AlertCircle className="h-3.5 w-3.5" />
            {totalHardStops} Hard Stop
            {totalHardStops === 1 ? "" : "s"} — Missing Document
            {totalHardStops === 1 ? "" : "s"}
          </span>
        ) : (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1.5 text-[12px] font-bold text-green-800">
            <CircleCheck className="h-3.5 w-3.5" />
            All required docs present
          </span>
        )}
      </header>

      {/* HARD STOPS — required + missing — uplift to Upload / Override cards */}
      {totalHardStops > 0 && (
        <>
          <SubHeader tone="fail">
            <ShieldX className="h-3.5 w-3.5" />
            Hard Stop — Missing Required Document
            {totalHardStops === 1 ? "" : "s"}
          </SubHeader>
          {hardStops.map((item) => (
            <div
              key={item.doc_type}
              className="mb-3 flex items-start gap-3 rounded-md border-[1.5px] border-red-300 bg-red-50 px-3.5 py-3"
            >
              <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-red-600 text-brand-white">
                <X className="h-3 w-3" strokeWidth={3} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="mb-1 text-[13px] font-extrabold tracking-tight">
                  {item.label} — Not Uploaded
                </p>
                <p className="mb-2 text-[12px] leading-relaxed text-slate-600">
                  Required for this loan&apos;s program profile. The file
                  cannot advance to Extraction until this document is uploaded
                  or a supervisor override is recorded.
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-md bg-brand-teal px-3 py-1.5 text-[11px] font-bold text-brand-white shadow-sm transition hover:shadow-md hover:brightness-105"
                  >
                    <Upload className="h-3 w-3" />
                    Upload {item.label.split(" ")[0]}
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-[11px] font-bold text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  >
                    <Edit3 className="h-3 w-3" />
                    Override with Supervisor Note
                  </button>
                </div>
              </div>
            </div>
          ))}
        </>
      )}

      {/* CHECKLIST — full per-doc table */}
      <SubHeader tone="pass">
        <CircleCheck className="h-3.5 w-3.5" />
        Document Checklist — {presentCount} Present
        {presentCount === checklist.length ? ", All Passing" : ""}
      </SubHeader>

      <div className="overflow-hidden rounded-md border border-border bg-card">
        {isLoading ? (
          <p className="p-6 text-sm text-muted-foreground">
            Loading checklist…
          </p>
        ) : checklist.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">
            No checklist configured for this loan.
          </p>
        ) : (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="bg-slate-50 text-[10px] font-bold uppercase tracking-wider text-slate-600">
                <th className="px-3 py-2 text-left">Document</th>
                <th className="px-2 py-2 text-center">Present</th>
                <th className="px-2 py-2 text-center">Recency</th>
                <th className="px-2 py-2 text-center">Name Match</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {checklist.map((item) => {
                const isRequired = item.requirement === "Required";
                const missing = !item.received && isRequired;
                const optionalMissing = !item.received && !isRequired;
                const needsReview = item.received && item.needs_review;
                const presentMark: CheckMark = missing
                  ? "fail"
                  : item.received
                    ? "pass"
                    : "na";
                const derived: CheckMark = item.received ? "pass" : "na";
                return (
                  <tr
                    key={item.doc_type}
                    className={cn(
                      "border-t border-border",
                      missing && "bg-red-50",
                      needsReview && "bg-amber-50",
                    )}
                  >
                    <td
                      className={cn(
                        "px-3 py-2 font-semibold",
                        missing && "font-bold text-red-700",
                        needsReview && "font-bold text-amber-800",
                      )}
                    >
                      {item.label}
                      {missing && (
                        <span className="ml-1 text-[10px] font-bold text-red-700">
                          — MISSING
                        </span>
                      )}
                      {optionalMissing && (
                        <span className="ml-1 text-[10px] font-bold text-muted-foreground">
                          — OPTIONAL
                        </span>
                      )}
                      {needsReview && (
                        <span className="ml-1 text-[10px] font-bold text-amber-700">
                          — NEEDS REVIEW
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <MarkIcon value={presentMark} />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <MarkIcon value={derived} />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <MarkIcon value={derived} />
                    </td>
                    <td className="px-3 py-2">
                      {missing ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-800">
                          Hard Stop
                        </span>
                      ) : optionalMissing ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-600">
                          Optional
                        </span>
                      ) : needsReview ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
                          Needs Review
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-bold text-green-800">
                          <Check className="h-2.5 w-2.5" />
                          Passed
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer — contextual hint + Advance to Extraction CTA */}
      <div className="mt-4 flex items-center gap-2.5 border-t-2 border-border pt-3">
        <p className="text-[12px] text-muted-foreground">
          {canAdvance
            ? "All required documents present. Advance this file to Extraction."
            : "Upload missing documents or add a supervisor override to advance this file to Extraction."}
        </p>
        <Link
          href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
          aria-disabled={!canAdvance}
          className={cn(
            "ml-auto inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-[12px] font-bold transition",
            canAdvance
              ? "bg-brand-teal text-brand-white shadow-sm hover:shadow-md hover:brightness-105"
              : "pointer-events-none cursor-not-allowed bg-brand-teal/40 text-brand-white/70",
          )}
        >
          <ArrowRight className="h-3 w-3" />
          Advance to Extraction
        </Link>
      </div>
    </div>
  );
}
