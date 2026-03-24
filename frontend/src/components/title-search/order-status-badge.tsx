"use client";

import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import {
  ORDER_STATUS_COLORS,
  ORDER_STATUS_LABELS,
} from "@/lib/title-search/constants";

export function OrderStatusBadge({
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
        ORDER_STATUS_COLORS[status] || "bg-muted text-muted-foreground"
      )}
    >
      {status === "processing" && (
        <Loader2 className="h-3 w-3 animate-spin" />
      )}
      {ORDER_STATUS_LABELS[status] || status.replace(/_/g, " ")}
      {status === "processing" && stage ? ` · ${stage}` : ""}
    </span>
  );
}
