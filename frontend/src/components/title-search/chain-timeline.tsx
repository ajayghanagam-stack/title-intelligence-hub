"use client";

import { ArrowRight, AlertTriangle, CheckCircle, Link2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChainLink } from "@/lib/title-search/types";

interface ChainTimelineProps {
  links: ChainLink[];
  chainComplete: boolean;
}

function formatParty(party: { names: string[] } | null): string {
  if (!party || party.names.length === 0) return "Unknown";
  return party.names.join(", ");
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "No date";
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function linkTypeLabel(linkType: string): string {
  const labels: Record<string, string> = {
    conveyance: "Conveyance",
    encumbrance: "Encumbrance",
    release: "Release",
    gap: "Gap",
  };
  return labels[linkType] || linkType;
}

/** SVG progress ring for chain completeness */
function CompletenessRing({ complete }: { complete: boolean }) {
  const pct = complete ? 100 : 0;
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div className="relative flex items-center justify-center">
      <svg width="48" height="48" className="-rotate-90">
        <circle
          cx="24"
          cy="24"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          className="text-muted/30"
        />
        <circle
          cx="24"
          cy="24"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={cn(
            "transition-all duration-700",
            complete ? "text-emerald-500" : "text-amber-500"
          )}
        />
      </svg>
      <span className="absolute text-[10px] font-bold">
        {complete ? (
          <CheckCircle className="h-4 w-4 text-emerald-600" />
        ) : (
          <AlertTriangle className="h-4 w-4 text-amber-600" />
        )}
      </span>
    </div>
  );
}

export function ChainTimeline({ links, chainComplete }: ChainTimelineProps) {
  if (links.length === 0) {
    return (
      <div className="section-card flex flex-col items-center py-10 text-center">
        <Link2 className="h-8 w-8 text-muted-foreground/40 mb-2" />
        <p className="text-sm text-muted-foreground">No chain links found</p>
      </div>
    );
  }

  return (
    <div className="section-card space-y-5">
      {/* Header with completeness ring */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Chain of Title
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {links.length} link{links.length !== 1 ? "s" : ""} &middot;{" "}
            {chainComplete ? "Complete" : "Incomplete"}
          </p>
        </div>
        <CompletenessRing complete={chainComplete} />
      </div>

      <div className="divider-brand" />

      {/* Timeline */}
      <div className="relative space-y-0">
        {links.map((link, idx) => {
          const isGap = link.is_gap;
          const isLast = idx === links.length - 1;

          return (
            <div key={link.id} className="flex gap-4">
              {/* Left: node + connector */}
              <div className="flex flex-col items-center">
                {/* Node */}
                <div
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 z-10",
                    isGap
                      ? "border-red-400 bg-red-50 animate-pulse"
                      : "border-amber-400 bg-amber-50"
                  )}
                >
                  {isGap ? (
                    <AlertTriangle className="h-3.5 w-3.5 text-red-600" />
                  ) : (
                    <span className="text-[10px] font-bold text-amber-700">
                      {link.position}
                    </span>
                  )}
                </div>
                {/* Connector line */}
                {!isLast && (
                  <div
                    className={cn(
                      "w-0.5 flex-1 min-h-[24px]",
                      isGap ? "bg-red-200" : "bg-amber-200"
                    )}
                  />
                )}
              </div>

              {/* Right: content card */}
              <div
                className={cn(
                  "flex-1 mb-3 rounded-lg border px-4 py-3",
                  isGap
                    ? "border-red-200 bg-red-50/50"
                    : "border-amber-100 bg-amber-50/30"
                )}
              >
                {isGap ? (
                  <div>
                    <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700 uppercase tracking-wider mb-1">
                      Gap
                    </span>
                    <p className="text-sm text-red-800">
                      {link.gap_description || "Gap in chain of title"}
                    </p>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800 uppercase tracking-wider">
                        {linkTypeLabel(link.link_type)}
                      </span>
                      <span className="text-[11px] text-muted-foreground">
                        {formatDate(link.effective_date)}
                      </span>
                    </div>
                    {/* From -> To flow */}
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-medium text-foreground">
                        {formatParty(link.from_party)}
                      </span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                      <span className="font-medium text-foreground">
                        {formatParty(link.to_party)}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
