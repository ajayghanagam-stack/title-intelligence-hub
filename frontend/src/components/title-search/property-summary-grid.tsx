"use client";

import { cn } from "@/lib/utils";

interface PropertySummaryItem {
  label: string;
  value: string | number | null | boolean;
}

interface PropertySummaryGridProps {
  items: PropertySummaryItem[];
}

function formatValue(value: string | number | null | boolean): string {
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString();
  return value;
}

export function PropertySummaryGrid({ items }: PropertySummaryGridProps) {
  return (
    <div className="card-warm overflow-hidden rounded-xl">
      <div className="grid grid-cols-1 sm:grid-cols-2">
        {items.map((item, idx) => (
          <div
            key={item.label}
            className={cn(
              "flex flex-col gap-0.5 px-4 py-3",
              "border-b border-amber-100/60 last:border-b-0 sm:[&:nth-last-child(2)]:border-b-0",
              idx % 2 === 0
                ? "bg-amber-50/30"
                : "bg-white/60"
            )}
          >
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {item.label}
            </span>
            <span className="text-sm font-medium text-foreground">
              {formatValue(item.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
