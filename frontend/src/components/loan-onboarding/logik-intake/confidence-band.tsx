"use client";

// Phase 5.2 — confidence-band chip + helpers.
//
// The LogikIntake spec uses three confidence bands:
//   - ≥ 0.85 → auto-confirm (teal)
//   - 0.60 – 0.84 → review (orange)
//   - < 0.60 → manual (red/destructive)
// These bands drive the field-row colors on the extract page and the
// confidence dots in the classify list. Keeping the thresholds + classes
// centralized here means the next screen that needs them doesn't have
// to re-derive the mapping.

import { cn } from "@/lib/utils";

export type ConfidenceBand = "auto" | "review" | "manual";

export function bandFor(confidence: number | null | undefined): ConfidenceBand {
  if (confidence == null || Number.isNaN(confidence)) return "manual";
  if (confidence >= 0.85) return "auto";
  if (confidence >= 0.6) return "review";
  return "manual";
}

const BAND_LABEL: Record<ConfidenceBand, string> = {
  auto: "Auto-confirm",
  review: "Review",
  manual: "Manual",
};

// Text on every chip variant uses brand-charcoal so the band-state contrast
// stays comfortably above WCAG AA on light tinted backgrounds. The dot +
// ring carry the actual band signal — teal/orange/destructive — so the
// auto chip still reads as "good" without putting teal text on teal/10.
const BAND_CHIP_CLASS: Record<ConfidenceBand, string> = {
  auto: "bg-brand-teal/10 text-brand-charcoal ring-brand-teal/40",
  review: "bg-brand-orange/10 text-brand-charcoal ring-brand-orange/40",
  manual: "bg-destructive/10 text-destructive ring-destructive/40",
};

const BAND_DOT_CLASS: Record<ConfidenceBand, string> = {
  auto: "bg-brand-teal",
  review: "bg-brand-orange",
  manual: "bg-destructive",
};

export function ConfidenceChip({
  confidence,
  showPercent = true,
}: {
  confidence: number | null | undefined;
  showPercent?: boolean;
}) {
  const band = bandFor(confidence);
  const pct =
    confidence == null || Number.isNaN(confidence)
      ? "—"
      : `${Math.round(confidence * 100)}%`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset",
        BAND_CHIP_CLASS[band]
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", BAND_DOT_CLASS[band])} />
      {showPercent ? pct : BAND_LABEL[band]}
    </span>
  );
}

export function ConfidenceLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
      {(["auto", "review", "manual"] as ConfidenceBand[]).map((band) => (
        <li key={band} className="inline-flex items-center gap-1.5">
          <span className={cn("h-2 w-2 rounded-full", BAND_DOT_CLASS[band])} />
          {BAND_LABEL[band]}
        </li>
      ))}
    </ul>
  );
}
