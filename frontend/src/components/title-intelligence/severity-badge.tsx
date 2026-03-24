"use client";

import { SEVERITY_COLORS } from "@/lib/ti-constants";
import type { FlagSeverity } from "@/lib/ti-types";

export function SeverityBadge({ severity }: { severity: FlagSeverity }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize ${
        SEVERITY_COLORS[severity] || ""
      }`}
    >
      {severity}
    </span>
  );
}
