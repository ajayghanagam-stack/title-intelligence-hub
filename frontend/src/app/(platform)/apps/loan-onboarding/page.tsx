"use client";

// Phase 5.2 — LogikIntake operator queue (screen #1).
//
// Replaces the legacy "Loan Onboarding" hero. Wires to the Phase 4 `/loans`
// alias via @tanstack/react-query so the data path is independent from the
// `/packages/*` URLs (which the Phase 4.9 redirect will eventually retire).
//
// Status / action derivations follow the prototype's `deriveStatus` /
// `deriveAction` shape but adapt to the *backend* status strings rather than
// the prototype's mock-store enum. Backend status values today:
//   - `uploading` / `processing` / `awaiting_review` / `completed`
//     / `failed` / `decision_ready`
// We treat `awaiting_review`/`failed` as "needs attention" and
// `decision_ready`/`completed` as "ready to view". Richer fields the
// LogikIntake spec calls for (program, hardStops, softFlags, daysInPipeline)
// are not yet on the list endpoint — the queue degrades gracefully when
// they're absent and we'll light them up when the list response is
// extended in a follow-up.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { useDeleteLoan, useLoans } from "@/hooks/use-loans";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { LoanPackageListItem } from "@/lib/loan-onboarding/types";

type StageFilter =
  | "all"
  | "ingest"
  | "classify"
  | "stack"
  | "validate"
  | "review";

const STAGE_OPTIONS: { value: StageFilter; label: string }[] = [
  { value: "all", label: "All Stages" },
  { value: "classify", label: "Classification" },
  { value: "stack", label: "Doc Validation" },
  { value: "validate", label: "Data Validation" },
  { value: "review", label: "Decision Ready" },
];

export default function LoanFileQueuePage() {
  const router = useRouter();
  const { orgPath } = useOrgSlug();
  const { loans, loading, error } = useLoans();
  const [stage, setStage] = useState<StageFilter>("all");

  const filtered = useMemo(() => {
    if (stage === "all") return loans;
    return loans.filter((l) => (l.pipeline_stage ?? "") === stage);
  }, [loans, stage]);

  const stats = useMemo(() => {
    const active = loans.length;
    const needAttention = loans.filter(
      (l) => l.status === "awaiting_review" || l.status === "failed"
    ).length;
    const decisionReady = loans.filter(
      (l) => l.status === "decision_ready" || l.status === "completed"
    ).length;
    const stpRate =
      active > 0 ? Math.round((decisionReady / active) * 100) : 0;
    return { active, needAttention, decisionReady, stpRate };
  }, [loans]);

  return (
    <div
      className="mx-auto max-w-7xl px-2 py-2"
      data-testid="loan-onboarding-page"
    >
      <header className="flex flex-wrap items-end justify-between gap-4 pb-5">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-brand-teal">
            LogikIntake
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight">
            Loan File Queue
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {stats.active} active file{stats.active === 1 ? "" : "s"} ·{" "}
            {stats.needAttention} need attention · Stage shown = earliest
            bottleneck requiring action
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="stage-filter">
            Stage filter
          </label>
          <select
            id="stage-filter"
            value={stage}
            onChange={(e) => setStage(e.target.value as StageFilter)}
            className="h-10 rounded-lg border bg-card px-3 text-sm focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20"
          >
            {STAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() =>
              router.push(orgPath("/apps/loan-onboarding/loans/new"))
            }
            className="btn-cta gap-2"
            data-testid="new-loan-file-button"
          >
            <Plus className="h-4 w-4" />
            New File
          </button>
        </div>
      </header>

      {/* Stat tiles — brand-token tones. Emerald is retained from the
          prototype because we don't have a dedicated "success" brand
          color and it reads as a distinct positive accent vs. the teal
          primary tile. */}
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          tone="teal"
          label="Active Files"
          value={String(stats.active)}
        />
        <StatTile
          tone="orange"
          label="Need Attention"
          value={String(stats.needAttention)}
        />
        <StatTile
          tone="purple"
          label="Decision Ready"
          value={String(stats.decisionReady)}
        />
        <StatTile
          tone="emerald"
          label="Day 1 STP Rate"
          value={`${stats.stpRate}%`}
        />
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center gap-3 py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading files…</p>
        </div>
      ) : (
        <FileQueueTable rows={filtered} orgPath={orgPath} />
      )}


      {!loading && filtered.length === 0 && (
        <p className="mt-6 text-center text-sm text-muted-foreground">
          {loans.length === 0
            ? "No loan files yet. Click \"New File\" to get started."
            : "No files match the current stage filter."}
        </p>
      )}

    </div>
  );
}

function StatTile({
  tone,
  label,
  value,
}: {
  tone: "teal" | "orange" | "purple" | "emerald";
  label: string;
  value: string;
}) {
  // Map the prototype's tonal accents to brand tokens. Orange uses a
  // darker text shade for AA contrast on the soft-orange surface.
  const accent: Record<typeof tone, string> = {
    teal: "border-t-brand-teal text-brand-teal",
    orange: "border-t-brand-orange text-brand-charcoal",
    purple: "border-t-brand-purple text-brand-purple",
    emerald: "border-t-emerald-500 text-emerald-700",
  };
  return (
    <div className={cn("card-warm border-t-4 px-4 py-3", accent[tone])}>
      <p className="font-mono text-2xl font-bold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[10px] font-bold uppercase tracking-wider opacity-80">
        {label}
      </p>
    </div>
  );
}

// ── Queue table ───────────────────────────────────────────────────────

type StatusBadge = {
  label: string;
  className: string;
};

function deriveStatus(row: LoanPackageListItem): StatusBadge {
  switch (row.status) {
    case "decision_ready":
      return {
        label: "Decision Ready",
        className: "bg-emerald-50 text-emerald-700 ring-emerald-300/60",
      };
    case "completed":
      return {
        label: "Completed",
        className:
          "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
      };
    case "awaiting_review":
      return {
        label: "Needs Review",
        className:
          "bg-brand-orange/10 text-brand-charcoal ring-brand-orange/40",
      };
    case "failed":
      return {
        label: "Failed",
        className: "bg-destructive/10 text-destructive ring-destructive/30",
      };
    case "processing":
      return {
        label: "Processing…",
        className:
          "bg-brand-teal/10 text-brand-teal ring-brand-teal/30",
      };
    case "uploading":
      return {
        label: "Uploading…",
        className: "bg-muted text-muted-foreground ring-border",
      };
    default:
      return {
        label: row.status,
        className: "bg-muted text-muted-foreground ring-border",
      };
  }
}

function deriveActionLabel(row: LoanPackageListItem): string {
  if (row.status === "awaiting_review" || row.status === "failed")
    return "Resolve";
  if (row.status === "decision_ready" || row.status === "completed")
    return "View";
  return "Open";
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffMs = Date.now() - then;
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function FileQueueTable({
  rows,
  orgPath,
}: {
  rows: LoanPackageListItem[];
  orgPath: (p: string) => string;
}) {
  const { showToast } = useToast();
  const deleteLoan = useDeleteLoan();
  // Row pending confirm — null when no modal open.
  const [confirmRow, setConfirmRow] = useState<LoanPackageListItem | null>(
    null,
  );

  if (rows.length === 0) return null;

  const closeConfirm = () => {
    if (deleteLoan.isPending) return; // don't close mid-flight
    setConfirmRow(null);
  };

  const handleConfirmDelete = () => {
    if (!confirmRow) return;
    const target = confirmRow;
    deleteLoan.mutate(target.id, {
      onSuccess: () => {
        showToast(
          "success",
          `Deleted ${target.borrower_name || target.name}`,
        );
        setConfirmRow(null);
      },
      onError: (err) => {
        showToast(
          "error",
          err instanceof Error ? err.message : "Failed to delete loan file",
        );
      },
    });
  };

  return (
    <>
      <div className="card-warm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Borrower / File</th>
              <th className="px-4 py-3">Stage</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Updated</th>
              <th className="px-4 py-3 text-right">Action</th>
              <th className="w-12 px-2 py-3" aria-label="Delete column" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => {
              const status = deriveStatus(row);
              const actionLabel = deriveActionLabel(row);
              // Phase 5.2 #2 — route to the LogikIntake pipeline overview.
              const href = orgPath(
                `/apps/loan-onboarding/loans/${row.id}`
              );
              return (
                <tr key={row.id} className="hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <p className="font-medium text-foreground">
                      {row.borrower_name || row.name}
                    </p>
                    {row.loan_reference && (
                      <p className="text-[11px] text-muted-foreground">
                        {row.loan_reference}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {row.pipeline_stage || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset",
                        status.className
                      )}
                    >
                      {status.label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {relativeTime(row.updated_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={href}
                      className="text-sm font-semibold text-brand-teal hover:underline"
                    >
                      {actionLabel} →
                    </Link>
                  </td>
                  <td className="px-2 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => setConfirmRow(row)}
                      aria-label={`Delete ${row.borrower_name || row.name}`}
                      title="Delete loan file"
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-destructive/10 hover:text-destructive focus:outline-none focus:ring-2 focus:ring-destructive/30"
                      data-testid={`delete-loan-${row.id}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {confirmRow && (
        <DeleteConfirmModal
          loan={confirmRow}
          isPending={deleteLoan.isPending}
          onCancel={closeConfirm}
          onConfirm={handleConfirmDelete}
        />
      )}
    </>
  );
}

// Inline modal — purpose-built for this destructive action so we don't
// pull in a dialog primitive just for a single confirm. Locks focus on
// the cancel button (safer default) and blocks dismissal while the
// mutation is in-flight to avoid orphaned half-deleted state on the UI.
function DeleteConfirmModal({
  loan,
  isPending,
  onCancel,
  onConfirm,
}: {
  loan: LoanPackageListItem;
  isPending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const title = loan.borrower_name || loan.name;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-loan-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        className="card-warm w-full max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="delete-loan-title"
          className="text-lg font-bold tracking-tight text-foreground"
        >
          Delete this loan file?
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{title}</span>{" "}
          and every uploaded document, classification, validation, and
          review attached to it will be permanently removed. This cannot
          be undone.
        </p>
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="inline-flex h-9 items-center rounded-md border bg-card px-3 text-sm font-semibold text-foreground hover:bg-muted/40 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            autoFocus
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-destructive px-3 text-sm font-semibold text-destructive-foreground hover:bg-destructive/90 disabled:cursor-not-allowed disabled:opacity-60"
            data-testid="delete-loan-confirm"
          >
            {isPending ? "Deleting…" : "Delete loan file"}
          </button>
        </div>
      </div>
    </div>
  );
}
