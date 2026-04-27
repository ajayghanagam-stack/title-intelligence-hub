"use client";

import { AlertCircle, Check, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { LOAN_STAGE_LABELS } from "@/lib/loan-onboarding/constants";
import type {
  LoanPipelineStageStatus,
  LoanPipelineStageTiming,
} from "@/lib/loan-onboarding/types";

const STAGES = ["ingest", "classify", "stack", "validate", "review"];

/**
 * Per-stage one-line description shown under the stage name. Adds
 * transparency about what the pipeline is actually doing. Kept short so
 * the vertical stepper stays compact.
 */
const STAGE_DESCRIPTIONS: Record<string, string> = {
  ingest: "Splitting uploaded PDFs and indexing each page",
  classify: "Predicting document type per page with the classifier",
  stack: "Grouping consecutive same-type pages into stacks",
  validate: "Running preset and custom rules against each stack",
  review: "Cross-document reasoning and final stack decisions",
};

/**
 * Stages whose progress can sensibly be reported in pages. Ingest reports
 * pages it has split; classify/stack/validate report pages they have
 * processed. Review is per-stack so we don't show a page count there.
 */
const PAGE_PROGRESS_STAGES = new Set(["ingest", "classify", "stack", "validate"]);

interface Props {
  stages?: LoanPipelineStageStatus[];
  timings?: LoanPipelineStageTiming[];
  processed?: number;
  total?: number;
  error?: string | null;
}

export function PipelineProgress({
  stages,
  timings,
  processed = 0,
  total = 0,
  error,
}: Props) {
  // Guard: older backend responses / in-flight fetches may not include `stages`
  // or `timings`. Default to empty arrays so the first render doesn't crash.
  const safeStages = stages ?? [];
  const safeTimings = timings ?? [];

  const stageMap = new Map(safeStages.map((s) => [s.stage, s.status]));
  const timingMap = new Map(
    safeTimings.map((t) => [t.stage, t.elapsed_seconds])
  );

  const completedCount = safeStages.filter((s) => s.status === "completed").length;
  const failed = safeStages.some((s) => s.status === "failed");
  const totalStages = STAGES.length;
  const stagePct = Math.round((completedCount / totalStages) * 100);

  // Prefer page-processed ratio when active in classify/stack/validate
  const runningStage = safeStages.find((s) => s.status === "running")?.stage;
  const useDocProgress =
    total > 0 &&
    runningStage &&
    ["classify", "stack", "validate"].includes(runningStage);
  const pct = useDocProgress
    ? Math.round((processed / total) * 100)
    : stagePct;

  const statusLabel = failed
    ? "Pipeline failed"
    : completedCount === totalStages
      ? "All stages complete"
      : runningStage
        ? `Processing: ${LOAN_STAGE_LABELS[runningStage] || runningStage}`
        : "Starting pipeline...";

  return (
    <div
      className="section-card space-y-5"
      role="status"
      aria-live="polite"
      aria-label={statusLabel}
      data-testid="loan-pipeline-progress"
    >
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Processing Pipeline
          </h3>
          <span
            className={cn(
              "text-xs font-semibold tabular-nums px-2.5 py-0.5 rounded-full",
              failed
                ? "bg-red-50 text-red-700"
                : completedCount === totalStages
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-amber-50 text-amber-700"
            )}
          >
            {pct}%
          </span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-700 ease-out",
              failed
                ? "bg-red-500"
                : "bg-gradient-to-r from-amber-500 to-orange-500"
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{statusLabel}</span>
          {useDocProgress ? (
            <span className="tabular-nums">
              {processed} / {total} pages
            </span>
          ) : null}
        </div>
      </div>

      <ol className="relative space-y-0" data-testid="loan-pipeline-stages">
        {STAGES.map((stageKey, i) => {
          const status = stageMap.get(stageKey) || "pending";
          const elapsed = timingMap.get(stageKey);
          const isCompleted = status === "completed";
          const isCurrent = status === "running";
          const isFailed = status === "failed";
          const isPending = status === "pending";
          const isLast = i === STAGES.length - 1;

          const statusText = isCompleted
            ? "Completed"
            : isCurrent
              ? "In progress"
              : isFailed
                ? "Failed"
                : "Pending";

          return (
            <li
              key={stageKey}
              className="relative flex items-start gap-4 pb-5 last:pb-0"
              data-testid={`loan-pipeline-stage-${stageKey}`}
            >
              {/* Vertical connector line behind the icon column */}
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute left-[17px] top-9 bottom-0 w-0.5 rounded-full transition-colors duration-500",
                    isCompleted ? "bg-emerald-400" : "bg-border"
                  )}
                />
              )}

              <div
                className={cn(
                  "relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 transition-all duration-300",
                  isCompleted &&
                    "border-emerald-500 bg-emerald-500 text-white shadow-sm",
                  isCurrent &&
                    "border-amber-500 bg-amber-500 text-white shadow-md pulse-glow",
                  isFailed &&
                    "border-red-500 bg-red-500 text-white shadow-sm",
                  isPending &&
                    "border-border bg-background text-muted-foreground/40"
                )}
              >
                {isCompleted ? (
                  <Check className="h-4 w-4" strokeWidth={3} />
                ) : isCurrent ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : isFailed ? (
                  <AlertCircle className="h-4 w-4" />
                ) : (
                  <Circle className="h-3 w-3 fill-current" />
                )}
              </div>

              <div className="flex-1 min-w-0 pt-1">
                <div className="flex items-baseline justify-between gap-3">
                  <span
                    className={cn(
                      "text-sm font-medium",
                      isCompleted
                        ? "text-emerald-700"
                        : isCurrent
                          ? "text-amber-700 font-semibold"
                          : isFailed
                            ? "text-red-700"
                            : "text-muted-foreground/70"
                    )}
                  >
                    {LOAN_STAGE_LABELS[stageKey] || stageKey}
                  </span>
                  {elapsed !== undefined && elapsed !== null && (
                    <span className="text-[10px] tabular-nums text-muted-foreground/70 shrink-0">
                      {elapsed < 1
                        ? `${Math.round(elapsed * 1000)}ms`
                        : `${elapsed.toFixed(1)}s`}
                    </span>
                  )}
                </div>
                {/* Description of what this stage is doing. */}
                <div
                  className={cn(
                    "text-xs mt-0.5 leading-snug",
                    isCurrent
                      ? "text-amber-700"
                      : isFailed
                        ? "text-red-600"
                        : "text-muted-foreground/70"
                  )}
                >
                  {STAGE_DESCRIPTIONS[stageKey] ?? statusText}
                </div>
                {/* Status + page count line. Only show "X of Y pages" while
                    running and when the stage has page-level progress. */}
                <div className="text-[11px] mt-0.5 flex items-center gap-2 text-muted-foreground/70">
                  <span>{statusText}</span>
                  {isCurrent &&
                    total > 0 &&
                    PAGE_PROGRESS_STAGES.has(stageKey) && (
                      <>
                        <span aria-hidden>·</span>
                        <span className="tabular-nums">
                          {processed} of {total} pages
                        </span>
                      </>
                    )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-800">Pipeline Error</p>
            <p className="text-sm text-red-700 mt-0.5">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
