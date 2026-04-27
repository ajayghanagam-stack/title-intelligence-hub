"use client";

import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import {
  LOAN_STATUS_COLORS,
  LOAN_STATUS_LABELS,
} from "@/lib/loan-onboarding/constants";

export function PackageStatusBadge({
  status,
  stage,
}: {
  status: string;
  stage?: string | null;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium",
        LOAN_STATUS_COLORS[status] || "bg-muted text-muted-foreground"
      )}
    >
      {status === "processing" && (
        <Loader2 className="h-3 w-3 animate-spin" />
      )}
      {LOAN_STATUS_LABELS[status] || status.replace(/_/g, " ")}
      {status === "processing" && stage ? ` · ${stage}` : ""}
    </span>
  );
}
