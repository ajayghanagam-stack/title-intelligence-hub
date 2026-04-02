"use client";

import { SEVERITY_COLORS, SEVERITY_DISPLAY_NAMES } from "@/lib/ti-constants";
import type { FlagSeverity } from "@/lib/ti-types";

export function SeverityBadge({ severity, size = "sm" }: { severity: FlagSeverity; size?: "sm" | "xs" }) {
  const displayName = SEVERITY_DISPLAY_NAMES[severity] || severity.toUpperCase();
  return (
    <span
      className={`inline-flex items-center rounded px-2 py-0.5 font-bold tracking-wide ${
        size === "xs" ? "text-[10px]" : "text-[11px]"
      } ${SEVERITY_COLORS[severity] || ""}`}
    >
      {displayName}
    </span>
  );
}
