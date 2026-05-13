"use client";

// Phase 5.2 — LogikIntake pipeline rail.
//
// Five-stage horizontal rail mirroring the LGK-0851 prototype: numbered
// circles, connecting line, "Complete" / "Bottleneck" sub-labels, and
// (when `richLayout` is true) clickable "Open →" links to the drilldown
// pages for stages that have their own surface.
//
// **Backend → display-stage mapping.** The backend pipeline has six
// internal stages (`ingest → classify → stack → validate → extract →
// review`). The operator-facing view collapses `stack` under
// classification (it's a deterministic grouping step with no review UI)
// so the rail shows five steps:
//   ingest    → Ingestion
//   classify  → Classification
//   stack     → Classification  (subsumed)
//   validate  → Doc Validation
//   extract   → Extraction
//   review    → Data Validation
// Terminal `complete` / `decision_ready` lights all pips.

import Link from "next/link";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

type StageKey =
  | "ingestion"
  | "classification"
  | "doc_validation"
  | "extraction"
  | "data_validation";

export const LO_DISPLAY_STAGES: Array<{
  key: StageKey;
  label: string;
  /** Sub-path appended to /apps/loan-onboarding/loans/{id} for the drilldown. */
  subPath: string | null;
}> = [
  { key: "ingestion", label: "Ingestion", subPath: null },
  { key: "classification", label: "Classification", subPath: null },
  { key: "doc_validation", label: "Doc Validation", subPath: "/doc-validation" },
  { key: "extraction", label: "Extraction", subPath: null },
  { key: "data_validation", label: "Data Validation", subPath: "/validation" },
];

// Map the backend's persisted `pipeline_stage` to the display stage key.
// `complete` is treated as "everything done" — handled in stageIndex().
const BACKEND_TO_DISPLAY: Record<string, StageKey> = {
  ingest: "ingestion",
  classify: "classification",
  stack: "classification",
  validate: "doc_validation",
  extract: "extraction",
  review: "data_validation",
};

function stageIndex(stage: string | null | undefined): number {
  if (!stage) return 0;
  if (stage === "complete") return LO_DISPLAY_STAGES.length - 1;
  const displayKey = BACKEND_TO_DISPLAY[stage];
  if (!displayKey) return 0;
  return LO_DISPLAY_STAGES.findIndex((s) => s.key === displayKey);
}

/**
 * Returns `{ index, label }` for the currently-active (bottleneck) stage —
 * a 0-based index plus the display label. Returns `null` when the
 * automated pipeline has finished — that includes:
 *
 *   - `status === "completed"`        (no HITL stacks)
 *   - `status === "decision_ready"`   (operator finalised review)
 *   - `status === "awaiting_review"`  (review stage ran; HITL pending)
 *   - `currentStage === "complete"`   (orchestrator wrote the terminal stage)
 *
 * Previously this only handled `decision_ready`/`completed`, so packages
 * that finished into `awaiting_review` (the common HITL case) kept
 * showing "Bottleneck: Data Validation" forever even though the rail's
 * automated work was done — that pinned the Data Validation pip in the
 * Bottleneck state indefinitely.
 */
export function getBottleneckStage(
  currentStage: string | null,
  status: string,
): { index: number; label: string } | null {
  if (isPipelineFinished(currentStage, status)) return null;
  const idx = stageIndex(currentStage);
  const stage = LO_DISPLAY_STAGES[idx];
  if (!stage) return null;
  return { index: idx, label: stage.label };
}

// Single source of truth for "the automated pipeline has nothing left to
// do." Used by both the rail and the bottleneck pill so they agree about
// what counts as terminal.
function isPipelineFinished(
  currentStage: string | null,
  status: string,
): boolean {
  if (status === "completed") return true;
  if (status === "decision_ready") return true;
  if (status === "awaiting_review") return true;
  if (currentStage === "complete") return true;
  return false;
}

export interface PipelineStagesBarProps {
  /** Backend `pipeline_stage` value. */
  currentStage: string | null;
  /** Backend `status` — used so terminal `decision_ready` lights every pip. */
  status: string;
  /**
   * Full-prototype rail with sub-labels and Open → links. Defaults to
   * `false` so existing sub-page headers keep the slim rail; the
   * loan-overview page opts into the rich layout.
   */
  richLayout?: boolean;
  /** Loan id — required for richLayout so drilldown Links resolve. */
  loanId?: string;
  /**
   * Org-aware path resolver — passed in so this component doesn't
   * import `useOrgSlug` itself (the rail is rendered by both auth and
   * sub-page surfaces).
   */
  orgPath?: (p: string) => string;
  /**
   * Per-backend-stage elapsed seconds, sourced from `/pipeline`. When
   * supplied (and `richLayout` is on), each completed pip shows
   * "Complete · 12s" instead of just "Complete" so the operator can see
   * which stages were fast vs. slow without leaving the page. Optional —
   * older callers that don't have the timings map keep working.
   */
  stageTimings?: Array<{ stage: string; elapsed_seconds: number | null }>;
}

// Maps a display-stage key back to the backend stage names that roll up
// into it, then sums the elapsed seconds across those backend stages.
// `classification` aggregates classify + stack so the user-facing number
// matches what they see as one step.
const DISPLAY_TO_BACKEND: Record<StageKey, string[]> = {
  ingestion: ["ingest"],
  classification: ["classify", "stack"],
  doc_validation: ["validate"],
  extraction: ["extract"],
  data_validation: ["review"],
};

function rollupElapsed(
  displayKey: StageKey,
  timings: Array<{ stage: string; elapsed_seconds: number | null }> | undefined,
): number | null {
  if (!timings || timings.length === 0) return null;
  const want = new Set(DISPLAY_TO_BACKEND[displayKey] ?? []);
  let total = 0;
  let any = false;
  for (const t of timings) {
    if (!want.has(t.stage)) continue;
    if (typeof t.elapsed_seconds === "number") {
      total += t.elapsed_seconds;
      any = true;
    }
  }
  return any ? total : null;
}

function formatElapsed(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function PipelineStagesBar({
  currentStage,
  status,
  richLayout = false,
  loanId,
  orgPath,
  stageTimings,
}: PipelineStagesBarProps) {
  const current = stageIndex(currentStage);
  // When the automated pipeline has finished — completed, decision_ready,
  // awaiting_review, or pipeline_stage="complete" — every pip is done.
  // Otherwise the currently-running step is `current` and every prior step
  // is done. `awaiting_review` is included because review (Data Validation)
  // having flagged HITL stacks does not mean the *pipeline* is still
  // running; the pipeline is done, only human review remains.
  const allDone = isPipelineFinished(currentStage, status);
  const activeIdx = allDone ? LO_DISPLAY_STAGES.length - 1 : current;
  const isFailed = status === "failed";

  if (!richLayout) {
    return <SlimRail currentIdx={current} allDone={allDone} isFailed={isFailed} />;
  }
  return (
    <RichRail
      activeIdx={activeIdx}
      allDone={allDone}
      isFailed={isFailed}
      loanId={loanId ?? ""}
      orgPath={orgPath ?? ((p) => p)}
      stageTimings={stageTimings}
    />
  );
}

// Compact horizontal pip-and-label rail used by the sub-page headers
// (classify, doc-validation, extract, validation). Kept as-is from
// Phase 5.2 so those screens don't reflow.
function SlimRail({
  currentIdx,
  allDone,
  isFailed,
}: {
  currentIdx: number;
  allDone: boolean;
  isFailed: boolean;
}) {
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs">
      {LO_DISPLAY_STAGES.map((stage, idx) => {
        const done = allDone ? true : idx < currentIdx;
        const active = !allDone && idx === currentIdx;
        const failed = isFailed && idx === currentIdx;
        return (
          <li key={stage.key} className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold ring-1 ring-inset",
                done && "bg-brand-teal text-brand-white ring-brand-teal",
                active &&
                  "bg-brand-purple/10 text-brand-purple ring-brand-purple/40 pulse-glow",
                failed && "bg-destructive/10 text-destructive ring-destructive/40",
                !done &&
                  !active &&
                  !failed &&
                  "bg-muted text-muted-foreground ring-border",
              )}
            >
              {idx + 1}
            </span>
            <span
              className={cn(
                "font-medium",
                done && "text-foreground",
                active && "text-brand-purple",
                failed && "text-destructive",
                !done && !active && !failed && "text-muted-foreground",
              )}
            >
              {stage.label}
            </span>
            {idx < LO_DISPLAY_STAGES.length - 1 && (
              <span
                aria-hidden
                className={cn("h-px w-8", done ? "bg-brand-teal/40" : "bg-border")}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// Prototype-aligned rail card with numbered circles, connecting lines,
// "Complete" / "Bottleneck" sub-labels, and per-stage drilldown links.
function RichRail({
  activeIdx,
  allDone,
  isFailed,
  loanId,
  orgPath,
  stageTimings,
}: {
  activeIdx: number;
  allDone: boolean;
  isFailed: boolean;
  loanId: string;
  orgPath: (p: string) => string;
  stageTimings?: Array<{ stage: string; elapsed_seconds: number | null }>;
}) {
  return (
    <ol className="flex items-start">
      {LO_DISPLAY_STAGES.map((step, i) => {
        const isDone = allDone || i < activeIdx;
        const isActive = !allDone && i === activeIdx;
        const failed = isFailed && i === activeIdx;
        const elapsed = isDone
          ? rollupElapsed(step.key, stageTimings)
          : null;
        // Stages with a dedicated drilldown surface get a hover-able
        // wrapper link. Done steps remain clickable so operators can
        // revisit (e.g. review a recorded validation override).
        const targetHref =
          step.subPath && loanId
            ? orgPath(`/apps/loan-onboarding/loans/${loanId}${step.subPath}`)
            : null;
        const inner = (
          <>
            {i < LO_DISPLAY_STAGES.length - 1 && (
              <span
                className={cn(
                  "absolute left-1/2 top-[14px] -z-0 h-0.5 w-full",
                  isDone ? "bg-brand-teal" : "bg-border",
                )}
                aria-hidden
              />
            )}
            <span
              className={cn(
                "relative z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 bg-card text-[11px] font-bold",
                isDone && "border-brand-teal bg-brand-teal text-brand-white",
                isActive &&
                  !failed &&
                  "border-brand-purple bg-brand-purple/10 text-brand-purple ring-4 ring-brand-purple/10",
                failed &&
                  "border-destructive bg-destructive/10 text-destructive ring-4 ring-destructive/10",
                !isDone &&
                  !isActive &&
                  "border-border text-muted-foreground",
              )}
            >
              {isDone ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </span>
            <span
              className={cn(
                "mt-2 max-w-[88px] text-center text-[10px] leading-tight",
                isActive
                  ? "font-bold text-foreground"
                  : isDone
                    ? "font-semibold text-emerald-700"
                    : "font-medium text-muted-foreground",
              )}
            >
              {step.label}
              {isDone && (
                <>
                  <br />
                  Complete
                  {elapsed !== null && (
                    <>
                      {" · "}
                      <span className="font-mono text-[9px] text-muted-foreground">
                        {formatElapsed(elapsed)}
                      </span>
                    </>
                  )}
                </>
              )}
              {isActive && !failed && (
                <>
                  <br />
                  <span className="text-brand-purple">Bottleneck</span>
                </>
              )}
              {failed && (
                <>
                  <br />
                  <span className="text-destructive">Failed</span>
                </>
              )}
              {targetHref && (
                <>
                  <br />
                  <span className="text-brand-teal underline-offset-2 group-hover:underline">
                    Open →
                  </span>
                </>
              )}
            </span>
          </>
        );
        return (
          <li
            key={step.key}
            className="relative flex flex-1 flex-col items-center"
          >
            {targetHref ? (
              <Link
                href={targetHref}
                className="group flex flex-col items-center rounded-md px-1 py-1 transition hover:bg-muted/40"
              >
                {inner}
              </Link>
            ) : (
              <div className="flex flex-col items-center px-1 py-1">{inner}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
