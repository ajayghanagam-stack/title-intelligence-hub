"use client";

import { AlertCircle } from "lucide-react";
import type { LoanStackExtraction } from "@/lib/loan-onboarding/types";

interface Props {
  extraction: LoanStackExtraction | null | undefined;
}

/**
 * Per-stack 'Extracted fields' block rendered inside the Results screen
 * stack card. Mirrors the prototype's two-column grid:
 *   FIELD_NAME (mono uppercase, ink-60)
 *   value (truncate)            confidence%
 *   ...or "Not found" for missing fields, with no confidence on the right.
 *
 * Returns null when the stack has zero requested fields — caller decides
 * whether to render the divider/heading above us.
 */
export function ExtractedFieldsPanel({ extraction }: Props) {
  if (!extraction || extraction.fields.length === 0) return null;
  const fields = extraction.fields;
  // Recompute located from the field rows so the header tally is always
  // consistent with the rendered "found"/"Not found" rows below. The
  // backend's persisted located_count counts strict status="located" only,
  // which under-reports when the agent downgrades a high-value extraction
  // to low_confidence (confidence < 0.8) — the user sees a value on screen
  // but the header read "n-1/n located". Treat low_confidence as found
  // because it always carries a value (see _coerce in extraction_agent.py).
  const located = fields.filter(
    (f) => f.status === "located" || f.status === "low_confidence"
  ).length;
  const total = fields.length;

  return (
    <div className="mt-4 pt-4 border-t border-border" data-testid="extracted-fields-panel">
      <div className="flex items-center justify-between mb-3">
        <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
          Extracted fields
        </div>
        <div className="font-mono text-[9px] text-muted-foreground tabular-nums">
          {located}/{total} located
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2">
        {fields.map((f, i) => {
          const found = f.status === "located" || f.status === "low_confidence";
          const confidencePct = Math.round((f.confidence ?? 0) * 100);
          return (
            <div
              key={`${f.name}-${i}`}
              className="flex items-start justify-between gap-3 py-1.5 border-b border-border/60 last:border-b-0"
            >
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
                  {f.name}
                </div>
                {found ? (
                  <div className="text-[12px] text-foreground truncate" title={f.value}>
                    {f.value}
                  </div>
                ) : (
                  <div className="text-[11px] text-amber-600 flex items-center gap-1">
                    <AlertCircle className="h-2.5 w-2.5" /> Not found
                  </div>
                )}
              </div>
              {/* Always show the confidence% — even for "Not found" rows the
                  caller wants to see the (typically 0%) score on the right
                  so confidence stays visible regardless of located state. */}
              <div className="font-mono text-[10px] text-muted-foreground tabular-nums shrink-0">
                {confidencePct}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
