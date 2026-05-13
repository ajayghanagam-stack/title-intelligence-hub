"use client";

// Phase 5.5 — 3-state Bbox overlay for extracted-field grounding.
//
// The extraction agent emits a `page` + `bbox` ([x0, y0, x1, y1] in
// 0..1 normalized coordinates) per field. Operators need to know at
// a glance which fields are AI-grounded (good), which they've edited
// (operator override), and which the agent couldn't locate (missing).
// The overlay renders one absolutely-positioned <div> per field on
// top of a page image, color-coded by the three states:
//
//   1. grounded:   bbox + page present, no operator edit → brand-teal
//   2. edited:     operator override applied → brand-purple (accent)
//   3. missing:    no bbox / different page / no value → dashed gray
//
// Hovering or clicking a field elsewhere on the screen sets `activeName`
// so the overlay can pulse the matching box. The component is page-aware:
// it filters fields to the visible page index before rendering.
//
// Coordinates assumption: the parent constrains size via inline width/
// height (or just an aspect ratio); the SVG overlay then positions
// each rect relative to that box. We do NOT enforce a particular page
// image source — the overlay is composited on top via absolute
// positioning, so the parent supplies the image (or a placeholder).

import { cn } from "@/lib/utils";
import type { LoanDocExtractionField } from "@/lib/loan-onboarding/api";

export type BboxState = "grounded" | "edited" | "missing";

export function bboxStateFor(field: LoanDocExtractionField): BboxState {
  if (field.edited) return "edited";
  if (field.grounded) return "grounded";
  return "missing";
}

const STATE_RING: Record<BboxState, string> = {
  grounded: "ring-brand-teal/70 bg-brand-teal/10",
  edited: "ring-brand-purple/70 bg-brand-purple/10",
  // Missing fields don't have a real bbox so they don't render — kept
  // here for completeness if a caller decides to draw a "missing"
  // marker at field origin (0,0) anyway.
  missing: "ring-destructive/40 bg-destructive/5",
};

const STATE_LABEL: Record<BboxState, string> = {
  grounded: "AI-grounded",
  edited: "Operator-edited",
  missing: "No grounding",
};

export function bboxStateLabel(state: BboxState): string {
  return STATE_LABEL[state];
}

export function BboxPageOverlay({
  fields,
  page,
  activeFieldName,
  onFieldHover,
  className,
}: {
  fields: LoanDocExtractionField[];
  /** 1-based page number to filter to. */
  page: number;
  /** Optional active field — pulses the matching rect. */
  activeFieldName?: string | null;
  onFieldHover?: (fieldName: string | null) => void;
  className?: string;
}) {
  // Only fields with a bbox + matching page get rendered. Missing fields
  // (no bbox / different page) are surfaced in the field list, not on
  // the page — drawing a phantom box at (0,0) would mislead operators.
  const visible = fields.filter(
    (f) => f.page === page && Array.isArray(f.bbox) && f.bbox.length === 4
  );

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0",
        className
      )}
      data-testid="bbox-page-overlay"
    >
      {visible.map((field) => {
        const [x0, y0, x1, y1] = field.bbox as [
          number,
          number,
          number,
          number,
        ];
        const state = bboxStateFor(field);
        const isActive = activeFieldName === field.name;
        const left = `${Math.max(0, x0) * 100}%`;
        const top = `${Math.max(0, y0) * 100}%`;
        const width = `${Math.max(0, x1 - x0) * 100}%`;
        const height = `${Math.max(0, y1 - y0) * 100}%`;
        return (
          <div
            key={field.name}
            role="presentation"
            data-field-name={field.name}
            data-state={state}
            onMouseEnter={
              onFieldHover ? () => onFieldHover(field.name) : undefined
            }
            onMouseLeave={
              onFieldHover ? () => onFieldHover(null) : undefined
            }
            className={cn(
              "pointer-events-auto absolute rounded-sm ring-2 ring-inset transition-all",
              STATE_RING[state],
              isActive && "shadow-lg scale-[1.02]"
            )}
            style={{ left, top, width, height }}
            title={`${field.name} · ${STATE_LABEL[state]}`}
          />
        );
      })}
    </div>
  );
}
