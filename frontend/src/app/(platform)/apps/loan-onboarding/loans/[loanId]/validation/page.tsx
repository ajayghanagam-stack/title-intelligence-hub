"use client";

// Phase 5.2 screen #6 — Data Validation.
//
// Mirrors the LogikIntake prototype's `screenDataValidation()`:
// header (title + subline + Hard Stop pill) → 3 stat tiles
// (Hard Stops / Advisory Flag / Rules Passed) → red Hard Stops
// section with Upload Corrected / Override cards → amber Advisory
// section with inline ack input + Acknowledge button → footer with
// "Mark Decision Ready" CTA (disabled until every hard stop is
// overridden and every soft flag is acknowledged).
//
// Reads `GET /loans/{id}/validations` (alias for `validation-results`)
// and groups every rule by `(passed, severity)`. `check_id` is
// `{stack_id}__{rule_source}__{rule_id}` — the ack route parses that
// shape. Override flow opens the shared OverrideDialog with the rule's
// stack + source identifiers.

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Check,
  Edit3,
  ShieldX,
  Sparkles,
  Upload,
  X,
} from "lucide-react";

import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import {
  useAcknowledgeValidation,
  useLoanValidations,
} from "@/hooks/use-loan-operator";
import {
  OverrideDialog,
  type OverrideTarget,
} from "@/components/loan-onboarding/logik-intake/override-dialog";
import { cn } from "@/lib/utils";
import type { LoanRuleEvaluation } from "@/lib/loan-onboarding/types";

type RuleRow = LoanRuleEvaluation & { stack_id: string; doc_type: string };

function isHardStop(rule: LoanRuleEvaluation): boolean {
  return (rule.severity || rule.type || "").toLowerCase() === "hard";
}

export default function DataValidationPage({
  params,
}: {
  params: { loanId: string };
}) {
  const { loanId } = params;
  const { orgPath } = useOrgSlug();
  const { package: loan } = useLoanPackage(loanId);
  const { data: results = [], isLoading } = useLoanValidations(loanId);
  const ack = useAcknowledgeValidation(loanId);
  const [showPassed, setShowPassed] = useState(false);
  const [overrideTarget, setOverrideTarget] = useState<OverrideTarget | null>(
    null,
  );

  const { hardStops, softFlags, passed } = useMemo(() => {
    const hardStops: RuleRow[] = [];
    const softFlags: RuleRow[] = [];
    const passed: RuleRow[] = [];
    for (const vr of results) {
      for (const rule of vr.rules_evaluated || []) {
        const row: RuleRow = {
          ...rule,
          stack_id: vr.stack_id,
          doc_type: vr.doc_type,
        };
        if (rule.passed) passed.push(row);
        else if (isHardStop(rule)) hardStops.push(row);
        else softFlags.push(row);
      }
    }
    return { hardStops, softFlags, passed };
  }, [results]);

  const unresolvedHardStops = hardStops.filter((r) => !r.override_note).length;
  const unackSoftFlags = softFlags.filter((r) => !r.acknowledged).length;
  const canAdvance = unresolvedHardStops === 0 && unackSoftFlags === 0;

  if (!loan) {
    return (
      <div className="mx-auto max-w-7xl px-2 py-8">
        <p className="text-sm text-muted-foreground">Loading loan file…</p>
      </div>
    );
  }

  const programLine = loan.loan_context?.program ?? "Loan package";

  return (
    <div className="mx-auto max-w-7xl px-6 py-6">
      <Link
        href={orgPath(`/apps/loan-onboarding/loans/${loanId}`)}
        className="mb-4 inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-[11px] font-semibold text-muted-foreground transition hover:bg-muted hover:text-foreground"
      >
        <ArrowLeft className="h-3 w-3" />
        Back to Pipeline
      </Link>

      {/* Header — title + subline + Hard Stop / All-clear pill */}
      <header className="mb-5 flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold tracking-tight">
            Data Validation
            <span className="ml-2 font-mono text-[12px] font-medium text-muted-foreground">
              {loan.borrower_name ?? loan.name} · {loan.id}
            </span>
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {programLine} · Validation run · {results.length} stack
            {results.length === 1 ? "" : "s"} evaluated
          </p>
        </div>
        {unresolvedHardStops > 0 ? (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1.5 text-[12px] font-bold text-red-800">
            <AlertCircle className="h-3.5 w-3.5" />
            {unresolvedHardStops} Hard Stop
            {unresolvedHardStops > 1 ? "s" : ""}
          </span>
        ) : (
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1.5 text-[12px] font-bold text-green-800">
            <CheckCircle2 className="h-3.5 w-3.5" />
            All hard stops resolved
          </span>
        )}
      </header>

      {/* Stat row — order + labels mirror canonical HTML:
          Hard Stops · Advisory Flag · Rules Passed */}
      <div className="mb-5 grid grid-cols-3 gap-3">
        <StatTile
          tone="red"
          label="Hard Stops"
          value={String(hardStops.length)}
          subtext="File cannot advance"
        />
        <StatTile
          tone="orange"
          label="Advisory Flag"
          value={String(softFlags.length)}
          subtext="Acknowledge to continue"
        />
        <StatTile
          tone="green"
          label="Rules Passed"
          value={String(passed.length)}
        />
      </div>

      {isLoading && (
        <p className="mb-4 text-sm text-muted-foreground">Loading checks…</p>
      )}

      {/* Hard Stops — File Cannot Advance */}
      {hardStops.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 inline-flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-red-600">
            <ShieldX className="h-4 w-4" />
            Hard Stops — File Cannot Advance
          </h2>
          <div className="space-y-3">
            {hardStops.map((rule, i) => (
              <HardStopCard
                key={`${rule.stack_id}-${rule.rule_id}-${i}`}
                rule={rule}
                onOverride={() =>
                  setOverrideTarget({
                    ruleLabel: rule.label,
                    ruleId: rule.rule_id,
                    ruleSource: rule.rule_source,
                    stackId: rule.stack_id,
                    docType: rule.doc_type,
                    detail: rule.detail,
                  })
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* Advisory Flag — Acknowledge to Continue */}
      {softFlags.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 inline-flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-amber-700">
            <AlertTriangle className="h-4 w-4" />
            Advisory Flag — Acknowledge to Continue
          </h2>
          <div className="space-y-3">
            {softFlags.map((rule, i) => (
              <SoftFlagCard
                key={`${rule.stack_id}-${rule.rule_id}-${i}`}
                rule={rule}
                ackPending={ack.isPending}
                onAcknowledge={(note) =>
                  ack.mutate({
                    checkId: `${rule.stack_id}__${rule.rule_source}__${rule.rule_id}`,
                    override_note: note,
                  })
                }
              />
            ))}
          </div>
        </section>
      )}

      {ack.error && (
        <p className="mt-3 text-xs text-destructive">{ack.error.message}</p>
      )}

      <OverrideDialog
        open={overrideTarget !== null}
        onClose={() => setOverrideTarget(null)}
        target={overrideTarget}
        pending={ack.isPending}
        onSubmit={(payload) => {
          ack.mutate(payload, {
            onSuccess: () => setOverrideTarget(null),
          });
        }}
      />

      {/* Footer — Mark Decision Ready action */}
      <footer className="mt-6 flex items-center gap-3 border-t-2 border-border pt-4">
        <p className="text-xs leading-relaxed text-muted-foreground">
          {canAdvance
            ? "All issues resolved. You can mark this file Decision Ready."
            : `Resolve ${unresolvedHardStops > 0 ? (unresolvedHardStops === 1 ? "the Hard Stop" : "all Hard Stops") : "all issues"} to advance this file to Decision Ready.`}
        </p>
        <button
          type="button"
          disabled={!canAdvance}
          className={cn(
            "ml-auto inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-bold uppercase tracking-wider transition",
            canAdvance
              ? "bg-brand-teal text-brand-white shadow-sm hover:shadow-md hover:brightness-105"
              : "cursor-not-allowed bg-brand-teal/40 text-brand-white/70",
          )}
        >
          <Sparkles className="h-3.5 w-3.5" />
          Mark Decision Ready
        </button>
      </footer>

      {/* Collapsed passed-checks audit list */}
      {passed.length > 0 && (
        <section className="mt-6">
          <button
            type="button"
            className="text-sm font-semibold text-brand-teal hover:underline"
            onClick={() => setShowPassed((v) => !v)}
          >
            {showPassed ? "Hide" : "Show"} {passed.length} passed check
            {passed.length === 1 ? "" : "s"}
          </button>
          {showPassed && (
            <ul className="mt-3 space-y-2">
              {passed.map((rule, i) => (
                <li
                  key={`${rule.stack_id}-${rule.rule_id}-${i}`}
                  className="rounded-lg border border-l-4 border-l-green-600 bg-card p-3 text-sm"
                >
                  <p className="font-medium text-foreground">{rule.label}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {rule.doc_type} · {rule.rule_id}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

// Stat tile — colored top border + large number + tiny label/subtext.
// Mirrors the canonical HTML `.stat.stat-t` block.
function StatTile({
  tone,
  label,
  value,
  subtext,
}: {
  tone: "green" | "red" | "orange";
  label: string;
  value: string;
  subtext?: string;
}) {
  const palette: Record<typeof tone, string> = {
    green: "border-t-green-600 text-green-700",
    red: "border-t-red-600 text-red-700",
    orange: "border-t-brand-orange text-amber-800",
  };
  return (
    <div
      className={cn("rounded-xl border border-t-4 bg-card p-3", palette[tone])}
    >
      <p className="font-mono text-2xl font-bold tabular-nums">{value}</p>
      <p className="mt-0.5 text-[10px] font-bold uppercase tracking-wider opacity-80">
        {label}
      </p>
      {subtext && (
        <p className="mt-0.5 text-[10px] text-muted-foreground">{subtext}</p>
      )}
    </div>
  );
}

// Hard-stop card — red icon circle + bold title + description + action
// row (Upload Corrected Document, Override with Supervisor Note).
// Override fires the parent OverrideDialog; Upload is a stub for now.
function HardStopCard({
  rule,
  onOverride,
}: {
  rule: RuleRow;
  onOverride: () => void;
}) {
  const overridden = !!rule.override_note;
  return (
    <div
      className={cn(
        "rounded-lg border-[1.5px] border-red-300 bg-red-50 px-3.5 py-3",
        overridden && "opacity-70",
      )}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-red-600 text-brand-white">
          <X className="h-3.5 w-3.5" strokeWidth={3} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[13px] font-extrabold tracking-tight">
            {rule.label}
          </p>
          {rule.detail && (
            <p className="mb-2 text-[12px] leading-relaxed text-slate-600">
              {rule.detail}
            </p>
          )}
          <p className="mb-2 text-[11px] text-muted-foreground">
            {rule.doc_type} · {rule.rule_source} · {rule.rule_id}
          </p>
          {!overridden ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-md bg-brand-teal px-2.5 py-1.5 text-[11px] font-bold text-brand-white shadow-sm transition hover:shadow-md hover:brightness-105"
              >
                <Upload className="h-3 w-3" />
                Upload Corrected Document
              </button>
              <button
                type="button"
                onClick={onOverride}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-[11px] font-bold text-muted-foreground transition hover:bg-muted hover:text-foreground"
              >
                <Edit3 className="h-3 w-3" />
                Override with Supervisor Note
              </button>
            </div>
          ) : (
            <span className="inline-flex max-w-md items-center gap-1 truncate rounded-md border border-brand-teal/40 bg-brand-teal/10 px-2 py-1 text-[11px] text-brand-teal">
              Note: {rule.override_note}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// Soft-flag card — amber icon circle + title + description + inline
// ack input + Acknowledge button. Once acknowledged the action row
// collapses to a green-tinted "Acknowledged" pill matching the HTML
// prototype's `.btn.btn-g` post-state.
function SoftFlagCard({
  rule,
  onAcknowledge,
  ackPending,
}: {
  rule: RuleRow;
  onAcknowledge: (note: string) => void;
  ackPending?: boolean;
}) {
  const [note, setNote] = useState(rule.override_note ?? "");
  const acked = rule.acknowledged === true;
  return (
    <div
      className={cn(
        "rounded-lg border-[1.5px] border-amber-200 bg-amber-50 px-3.5 py-3",
        acked && "opacity-70",
      )}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-orange text-brand-charcoal">
          <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2.5} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[13px] font-extrabold tracking-tight">
            {rule.label}
          </p>
          {rule.detail && (
            <p className="mb-2 text-[12px] leading-relaxed text-slate-600">
              {rule.detail}
            </p>
          )}
          <p className="mb-2 text-[11px] text-muted-foreground">
            {rule.doc_type} · {rule.rule_source} · {rule.rule_id}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add acknowledgment note..."
              disabled={acked}
              className="h-8 min-w-[200px] flex-1 rounded-md border border-border bg-card px-2.5 text-xs focus:border-brand-teal focus:outline-none focus:ring-2 focus:ring-brand-teal/20 disabled:bg-muted/40"
            />
            <button
              type="button"
              disabled={acked || ackPending}
              onClick={() => onAcknowledge(note.trim())}
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[11px] font-bold transition",
                acked
                  ? "cursor-default bg-green-50 text-green-800 ring-1 ring-green-200"
                  : "bg-brand-teal text-brand-white shadow-sm hover:shadow-md hover:brightness-105",
              )}
            >
              <Check className="h-3 w-3" />
              {acked ? "Acknowledged" : ackPending ? "Saving…" : "Acknowledge"}
            </button>
          </div>
          {acked && rule.override_note && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Note: {rule.override_note}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
