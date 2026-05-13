"use client";

// Phase 5.2 screen #7 — Decision-Ready Preview.
//
// Last operator surface before issuing the LOS handoff. Surfaces what will
// be sent so the LO can sanity-check before pulling the trigger:
//   - Document inventory (accepted/validated stacks + total page count)
//   - Validation summary (hard stops, soft flags acked, passes)
//   - Confirm CTA → calls `useAdvanceLoan` (same backend route the
//     overview's footer uses; this page just gates the call behind a
//     confirm step the prototype's spec calls for).
//
// On success we route back to the overview where the green "Decision-ready"
// banner now shows. On block (e.g. unacked soft flag), we surface the
// blocked_reason inline.

import Link from "next/link";
import { useMemo } from "react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import {
  useAdvanceLoan,
  useLoanDocuments,
  useLoanValidations,
} from "@/hooks/use-loan-operator";
import { LoanHeader } from "@/components/loan-onboarding/logik-intake/loan-header";
import { cn } from "@/lib/utils";

export default function DecisionReadyPreviewPage({
  params,
}: {
  params: { loanId: string };
}) {
  const { loanId } = params;
  const { orgPath } = useOrgSlug();
  const { package: loan } = useLoanPackage(loanId);
  const { data: documents = [] } = useLoanDocuments(loanId);
  const { data: validations = [] } = useLoanValidations(loanId);
  const advance = useAdvanceLoan(loanId);

  const docSummary = useMemo(() => {
    let accepted = 0;
    let validated = 0;
    let needsReview = 0;
    let totalPages = 0;
    for (const d of documents) {
      totalPages += d.page_count;
      if (d.status === "accepted") accepted += 1;
      else if (d.status === "validated") validated += 1;
      else if (d.status === "needs_review") needsReview += 1;
    }
    return { accepted, validated, needsReview, totalPages };
  }, [documents]);

  const ruleSummary = useMemo(() => {
    let hardStops = 0;
    let softFlags = 0;
    let acked = 0;
    let passed = 0;
    for (const vr of validations) {
      for (const r of vr.rules_evaluated || []) {
        const isHard = (r.severity || r.type || "").toLowerCase() === "hard";
        if (r.passed) passed += 1;
        else if (isHard) hardStops += 1;
        else if (r.acknowledged) acked += 1;
        else softFlags += 1;
      }
    }
    return { hardStops, softFlags, acked, passed };
  }, [validations]);

  const blocked = ruleSummary.hardStops > 0 || ruleSummary.softFlags > 0;
  const alreadyAdvanced = loan?.status === "decision_ready";

  if (!loan) {
    return (
      <div className="mx-auto max-w-7xl px-2 py-8">
        <p className="text-sm text-muted-foreground">Loading loan file…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-2 py-2">
      <LoanHeader loan={loan} />

      <header>
        <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-brand-purple">
          LogikIntake · Handoff
        </p>
        <h2 className="mt-1 text-xl font-bold tracking-tight">
          Decision-Ready Preview
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Confirm the loan file inventory and validation status before issuing
          the LOS handoff.
        </p>
      </header>

      <section className="grid gap-3 md:grid-cols-4">
        <Tile label="Documents accepted" value={String(docSummary.accepted)} />
        <Tile
          label="Validated (auto)"
          value={String(docSummary.validated)}
        />
        <Tile
          label="Pages total"
          value={String(docSummary.totalPages)}
        />
        <Tile
          label="Needs review"
          value={String(docSummary.needsReview)}
          tone={docSummary.needsReview > 0 ? "destructive" : "default"}
        />
      </section>

      <section className="card-warm p-5">
        <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
          Validation summary
        </h3>
        <ul className="mt-3 grid gap-2 md:grid-cols-2">
          <SummaryRow
            label="Checks passed"
            value={ruleSummary.passed}
            tone="success"
          />
          <SummaryRow
            label="Soft flags acknowledged"
            value={ruleSummary.acked}
            tone="info"
          />
          <SummaryRow
            label="Soft flags open"
            value={ruleSummary.softFlags}
            tone={ruleSummary.softFlags > 0 ? "warn" : "muted"}
          />
          <SummaryRow
            label="Hard stops open"
            value={ruleSummary.hardStops}
            tone={ruleSummary.hardStops > 0 ? "destructive" : "muted"}
          />
        </ul>
      </section>

      <section className="card-warm p-5">
        <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
          Document inventory
        </h3>
        <ul className="mt-3 divide-y rounded-lg border bg-card">
          {documents.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted-foreground">
              No documents in this loan file.
            </li>
          ) : (
            documents.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between px-3 py-2 text-xs"
              >
                <span className="font-medium">{d.doc_type || "Unclassified"}</span>
                <span className="text-muted-foreground">
                  Pages {d.first_page}–{d.last_page} · {d.status.replace(/_/g, " ")}
                </span>
              </li>
            ))
          )}
        </ul>
      </section>

      {advance.data?.advanced === false && advance.data.blocked_reason && (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          Blocked: {advance.data.blocked_reason}
        </p>
      )}
      {advance.error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {advance.error.message}
        </p>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t pt-5">
        <Link
          href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
          className="text-sm font-semibold text-muted-foreground hover:text-foreground hover:underline"
        >
          ← Back to overview
        </Link>
        <button
          type="button"
          className="btn-cta"
          disabled={advance.isPending || alreadyAdvanced || blocked}
          onClick={() => advance.mutate()}
        >
          {alreadyAdvanced
            ? "Already decision-ready"
            : advance.isPending
              ? "Issuing handoff…"
              : blocked
                ? "Resolve blockers first"
                : "Confirm & issue handoff"}
        </button>
      </footer>
    </div>
  );
}

function Tile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "destructive";
}) {
  return (
    <div
      className={cn(
        "card-warm border-t-4 px-4 py-3",
        tone === "destructive"
          ? "border-t-destructive text-destructive"
          : "border-t-brand-teal text-brand-teal"
      )}
    >
      <p className="font-mono text-2xl font-bold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[10px] font-bold uppercase tracking-wider opacity-80">
        {label}
      </p>
    </div>
  );
}

function SummaryRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "success" | "info" | "warn" | "destructive" | "muted";
}) {
  const toneCls: Record<typeof tone, string> = {
    success: "text-emerald-700",
    info: "text-brand-teal",
    warn: "text-brand-charcoal",
    destructive: "text-destructive",
    muted: "text-muted-foreground",
  };
  return (
    <li className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-mono tabular-nums font-bold", toneCls[tone])}>
        {value}
      </span>
    </li>
  );
}
