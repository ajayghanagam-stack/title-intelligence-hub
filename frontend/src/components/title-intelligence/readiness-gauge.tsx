"use client";

import type { CategoryScore } from "@/lib/ti-types";

const categoryLabels: Record<string, string> = {
  extraction_completeness: "Extraction Completeness",
  risk_assessment: "Risk Assessment",
  flag_resolution: "Flag Resolution",
  extraction_confidence: "Extraction Confidence",
  requirements: "Requirements",
  endorsements: "Endorsements",
  liens: "Liens",
  exceptions: "Exceptions",
  consistency: "Consistency",
};

export function ReadinessGauge({
  score,
  summary,
  categories,
}: {
  score: number;
  summary: string | null;
  categories: CategoryScore[];
}) {
  const color =
    score >= 80 ? "text-green-600" : score >= 50 ? "text-yellow-600" : "text-red-600";
  const bgColor =
    score >= 80 ? "bg-green-500" : score >= 50 ? "bg-yellow-500" : "bg-red-500";
  const status =
    score >= 90 ? "Ready" : score >= 60 ? "At Risk" : "Not Ready";
  const statusColor =
    score >= 90 ? "bg-green-100 text-green-800" : score >= 60 ? "bg-yellow-100 text-yellow-800" : "bg-red-100 text-red-800";

  return (
    <div className="space-y-6">
      <div className="rounded-xl border bg-card p-6 shadow-sm text-center">
        <div className={`text-5xl font-bold ${color}`}>{score}</div>
        <p className="text-sm text-muted-foreground mt-1">out of 100</p>
        <div className="mt-3 h-3 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${bgColor}`}
            style={{ width: `${score}%` }}
          />
        </div>
        <span className={`mt-3 inline-block rounded-full px-3 py-1 text-xs font-semibold ${statusColor}`}>
          {status}
        </span>
      </div>

      {summary && (
        <div className="rounded-xl bg-muted/50 border p-4">
          <p className="text-sm leading-relaxed">{summary}</p>
        </div>
      )}

      <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
        <h3 className="text-sm font-semibold">Category Breakdown</h3>
        {categories.map((cat) => {
          const pct = cat.max_score > 0 ? (cat.score / cat.max_score) * 100 : 0;
          const barColor =
            pct >= 80 ? "bg-green-500" : pct >= 50 ? "bg-yellow-500" : "bg-red-500";

          return (
            <div key={cat.category}>
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">
                  {categoryLabels[cat.category] || cat.category}
                </span>
                <span className="text-muted-foreground">
                  {cat.score}/{cat.max_score}
                </span>
              </div>
              <div className="mt-1.5 h-2 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{cat.details}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
