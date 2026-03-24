"use client";

import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

const STATUS_STYLES: Record<string, string> = {
  uploading: "bg-stone-100 text-stone-600 ring-1 ring-stone-200",
  processing: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  completed: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-1 ring-red-200",
};

const STATUS_LABELS: Record<string, string> = {
  uploading: "Uploading",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};

export function PackStatusBadge({
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
        STATUS_STYLES[status] || "bg-muted text-muted-foreground"
      )}
    >
      {status === "processing" && (
        <Loader2 className="h-3 w-3 animate-spin" />
      )}
      {STATUS_LABELS[status] || status}
      {status === "processing" && stage ? ` · ${stage}` : ""}
    </span>
  );
}
