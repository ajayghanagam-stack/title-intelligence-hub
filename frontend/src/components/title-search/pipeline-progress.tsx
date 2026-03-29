"use client";

import { Check, Loader2, Circle, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { STAGE_LABELS } from "@/lib/title-search/constants";
import type { PipelineStageStatus } from "@/lib/title-search/types";

const STAGES = ["order", "retrieve", "parse", "chain", "package", "complete"];

export function PipelineProgress({
  stages,
  error,
}: {
  stages: PipelineStageStatus[];
  error?: string | null;
}) {
  const stageMap = new Map(stages.map((s) => [s.stage, s.status]));
  const completed = stages.filter((s) => s.status === "completed").length;
  const failed = stages.some((s) => s.status === "failed");
  const total = stages.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const currentIndex = stages.findIndex((s) => s.status === "running");
  const statusLabel = failed
    ? "Pipeline failed"
    : completed === total
      ? "All stages complete"
      : currentIndex >= 0
        ? `Processing stage ${currentIndex + 1} of ${total}`
        : "Starting pipeline...";

  return (
    <div
      className="section-card space-y-5"
      role="status"
      aria-live="polite"
      aria-label={statusLabel}
      data-testid="pipeline-progress"
    >
      {/* Header + progress bar */}
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
                : completed === total
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
        <p className="text-xs text-muted-foreground">{statusLabel}</p>
      </div>

      {/* Pipeline stages — circles + connecting lines */}
      <div className="flex items-start gap-0 overflow-x-auto pb-1">
        {STAGES.map((stageKey, i) => {
          const status = stageMap.get(stageKey) || "pending";
          const isCompleted = status === "completed";
          const isCurrent = status === "running";
          const isFailed = status === "failed";
          const isPending = status === "pending";

          return (
            <div key={stageKey} className="flex items-start">
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-full border-2 transition-all duration-300",
                    isCompleted &&
                      "border-emerald-500 bg-emerald-500 text-white shadow-sm",
                    isCurrent &&
                      "border-amber-500 bg-amber-500 text-white shadow-md pulse-glow",
                    isFailed &&
                      "border-red-500 bg-red-500 text-white shadow-sm",
                    isPending &&
                      "border-border bg-muted/50 text-muted-foreground/40"
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
                <span
                  className={cn(
                    "mt-2 text-[10px] font-medium whitespace-nowrap leading-tight text-center",
                    isCompleted
                      ? "text-emerald-700"
                      : isCurrent
                        ? "text-amber-700 font-semibold"
                        : isFailed
                          ? "text-red-700"
                          : "text-muted-foreground/50"
                  )}
                >
                  {STAGE_LABELS[stageKey] || stageKey}
                </span>
              </div>
              {i < STAGES.length - 1 && (
                <div
                  className={cn(
                    "mt-[18px] mx-1.5 h-0.5 w-10 flex-shrink-0 rounded-full transition-colors duration-500",
                    isCompleted ? "bg-emerald-400" : "bg-border"
                  )}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Error message */}
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
