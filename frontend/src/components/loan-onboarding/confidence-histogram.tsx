"use client";

import type { LoanStack } from "@/lib/loan-onboarding/types";

interface Bucket {
  range: string;
  min: number;
  max: number;
  count: number;
}

/**
 * 5-bucket vertical histogram showing how stack overall_confidence is
 * distributed (50–60, 60–70, 70–80, 80–90, 90–100). Stacks with null
 * confidence are dropped — the chart describes scored stacks only.
 *
 * Bars below 90% render in amber (the "needs attention" band); the 90–100
 * bucket renders in emerald. This mirrors the dashboard's stack-level
 * scoring tiles and keeps the colour vocabulary consistent.
 */
export function ConfidenceHistogram({ stacks }: { stacks: LoanStack[] }) {
  const scored = stacks
    .map((s) => s.overall_confidence)
    .filter((v): v is number => v != null)
    .map((v) => Math.round(v * 100));

  const buckets: Bucket[] = [
    { range: "50–60", min: 50, max: 60, count: 0 },
    { range: "60–70", min: 60, max: 70, count: 0 },
    { range: "70–80", min: 70, max: 80, count: 0 },
    { range: "80–90", min: 80, max: 90, count: 0 },
    { range: "90–100", min: 90, max: 101, count: 0 },
  ];

  for (const v of scored) {
    const b = buckets.find((bk) => v >= bk.min && v < bk.max);
    if (b) b.count += 1;
  }

  const max = Math.max(...buckets.map((b) => b.count), 1);

  return (
    <div data-testid="confidence-histogram">
      <div className="flex items-end gap-3 h-32">
        {buckets.map((b) => {
          const isGreen = b.min >= 90;
          const heightPct = (b.count / max) * 100;
          return (
            <div
              key={b.range}
              className="flex-1 flex flex-col items-center gap-1.5 min-w-0"
              data-testid={`hist-bucket-${b.range}`}
            >
              <span className="font-mono text-[11px] tabular-nums text-foreground">
                {b.count}
              </span>
              <div className="w-full flex-1 flex items-end">
                <div
                  className={`w-full rounded-t-sm ${
                    isGreen ? "bg-emerald-500/80" : "bg-amber-500/80"
                  }`}
                  style={{
                    height: `${Math.max(heightPct, b.count > 0 ? 6 : 2)}%`,
                    minHeight: b.count > 0 ? "6px" : "2px",
                    opacity: b.count === 0 ? 0.25 : undefined,
                  }}
                />
              </div>
              <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
                {b.range}%
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex items-center gap-4 text-[10px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-emerald-500/80" />
          Confident (≥ 90%)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-amber-500/80" />
          Below 90%
        </span>
        <span className="ml-auto tabular-nums">
          {scored.length} scored stack{scored.length === 1 ? "" : "s"}
        </span>
      </div>
    </div>
  );
}
