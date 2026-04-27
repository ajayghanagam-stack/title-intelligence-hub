"use client";

import { cn } from "@/lib/utils";
import type { LoanConfidenceBreakdown } from "@/lib/loan-onboarding/types";

type SegmentKey = "classification" | "split_accuracy" | "validation";

interface Props {
  breakdown: LoanConfidenceBreakdown;
  overall: number | null;
  /**
   * Hide one or more sub-scores from both the donut and the legend. Used on
   * the package dashboard where the split-accuracy score isn't meaningful at
   * a glance — operators only need classification + validation there.
   */
  omit?: SegmentKey[];
  /**
   * Compact variant — smaller donut + tighter legend. Tuned to fit inside a
   * stack tile on the dashboard.
   */
  compact?: boolean;
}

interface Segment {
  key: SegmentKey;
  label: string;
  value: number;
  color: string;
  bg: string;
}

function pct(v: number | null | undefined): number {
  if (v === null || v === undefined || Number.isNaN(v)) return 0;
  const clamped = Math.max(0, Math.min(1, v));
  return Math.round(clamped * 100);
}

/**
 * Frontend-side overall confidence — equal-weight average of classification
 * and validation. A failed validation (e.g. 60%) pulls the overall down by
 * the same amount a strong classification (e.g. 96%) pulls it up, which
 * matches how operators read the two numbers side-by-side on the dashboard.
 *
 * Returns null only when both inputs are missing. If only one is present,
 * the other is treated as 0 so missing-validation stacks don't appear
 * artificially confident.
 */
export function blendOverallNoSplit(
  breakdown: LoanConfidenceBreakdown
): number | null {
  const c = breakdown.classification;
  const v = breakdown.validation;
  if (c == null && v == null) return null;
  const cls = c ?? 0;
  const val = v ?? 0;
  const blended = (cls + val) / 2;
  return Math.max(0, Math.min(1, blended));
}

/**
 * Simple SVG donut showing the three confidence sub-scores
 * (classification, split, validation) with the overall confidence in the
 * center. The three equal-width arc segments are tinted by the respective
 * sub-score so weak areas are visually obvious.
 */
export function ConfidenceBreakdown({
  breakdown,
  overall,
  omit,
  compact,
}: Props) {
  const omitSet = new Set<SegmentKey>(omit ?? []);
  const allSegments: Segment[] = [
    {
      key: "classification",
      label: "Classification",
      value: pct(breakdown.classification),
      color: "oklch(0.670 0.170 145)",
      bg: "oklch(0.920 0.040 145)",
    },
    {
      key: "split_accuracy",
      label: "Split",
      value: pct(breakdown.split_accuracy),
      color: "oklch(0.680 0.160 245)",
      bg: "oklch(0.930 0.040 245)",
    },
    {
      key: "validation",
      label: "Validation",
      value: pct(breakdown.validation),
      color: "oklch(0.720 0.170 65)",
      bg: "oklch(0.940 0.045 65)",
    },
  ];
  const segments = allSegments.filter((s) => !omitSet.has(s.key));

  // When split-accuracy is omitted, the caller's stored `overall` was likely
  // computed against the older weights. Recompute on the fly so the number
  // in the donut center matches the segments we're actually drawing.
  const effectiveOverall = omitSet.has("split_accuracy")
    ? blendOverallNoSplit(breakdown)
    : overall;

  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const segmentLen = circumference / Math.max(1, segments.length);
  const gap = 2;

  const donutSize = compact ? "h-24 w-24" : "h-32 w-32";
  const overallText = compact ? "text-base" : "text-xl";
  const legendText = compact ? "text-xs" : "text-sm";
  const legendLabelWidth = compact ? "w-20" : "w-24";
  const containerGap = compact ? "gap-4" : "gap-6";

  return (
    <div
      className={cn("flex items-center", containerGap)}
      data-testid="confidence-breakdown"
    >
      <div className={cn("relative shrink-0", donutSize)}>
        <svg viewBox="0 0 100 100" className="-rotate-90 h-full w-full">
          {segments.map((seg, idx) => {
            const offset = -(segmentLen * idx);
            const filled = (segmentLen - gap) * (seg.value / 100);
            return (
              <g key={seg.label}>
                <circle
                  cx="50"
                  cy="50"
                  r={radius}
                  fill="none"
                  stroke={seg.bg}
                  strokeWidth="10"
                  strokeDasharray={`${segmentLen - gap} ${circumference}`}
                  strokeDashoffset={offset}
                />
                <circle
                  cx="50"
                  cy="50"
                  r={radius}
                  fill="none"
                  stroke={seg.color}
                  strokeWidth="10"
                  strokeDasharray={`${filled} ${circumference}`}
                  strokeDashoffset={offset}
                  strokeLinecap="butt"
                />
              </g>
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("font-bold tabular-nums", overallText)}>
            {pct(effectiveOverall)}%
          </span>
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Overall
          </span>
        </div>
      </div>

      <ul className={cn("space-y-1.5", legendText)}>
        {segments.map((seg) => (
          <li key={seg.label} className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: seg.color }}
            />
            <span className={cn("text-muted-foreground", legendLabelWidth)}>
              {seg.label}
            </span>
            <span className="font-semibold tabular-nums">{seg.value}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
