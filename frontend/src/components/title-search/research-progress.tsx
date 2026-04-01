"use client";

import { Search, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface ResearchProgressProps {
  stage: string;
  isActive: boolean;
}

export function ResearchProgress({ stage, isActive }: ResearchProgressProps) {
  return (
    <div
      className="section-card flex flex-col items-center justify-center py-12 space-y-4"
      role="status"
      aria-live="polite"
      aria-label={isActive ? `Researching: ${stage}` : stage}
    >
      <div
        className={cn(
          "relative flex h-16 w-16 items-center justify-center rounded-full",
          "bg-gradient-to-br from-amber-100 to-amber-200 border-2 border-amber-300/60",
          isActive && "pulse-glow"
        )}
      >
        <Search
          className={cn(
            "h-7 w-7 text-amber-700",
            isActive && "animate-pulse"
          )}
        />
        {isActive && (
          <Loader2 className="absolute -top-1 -right-1 h-5 w-5 text-amber-500 animate-spin" />
        )}
      </div>

      <div className="text-center space-y-1">
        <p className="text-sm font-semibold text-foreground">
          {isActive ? "Researching property records" : stage}
        </p>
        {isActive && (
          <p className="text-xs text-muted-foreground">
            Searching county databases and public records
            <span className="inline-block w-8 text-left animate-pulse">...</span>
          </p>
        )}
      </div>
    </div>
  );
}
