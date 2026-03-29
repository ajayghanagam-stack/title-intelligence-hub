"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { getChain } from "@/lib/title-search/api";
import type { ChainResponse } from "@/lib/title-search/types";
import {
  ArrowRight,
  AlertTriangle,
  CheckCircle2,
  Link2,
  GitBranch,
} from "lucide-react";

export default function ChainPage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [chain, setChain] = useState<ChainResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!currentOrgId || !orderId) return;
    getChain(currentOrgId, orderId)
      .then(setChain)
      .catch(() => setChain(null))
      .finally(() => setLoading(false));
  }, [currentOrgId, orderId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading chain...</p>
      </div>
    );
  }

  if (!chain) {
    return (
      <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
          <GitBranch className="h-7 w-7 text-muted-foreground/60" />
        </div>
        <p className="text-lg font-medium text-foreground/80 mb-1">
          No chain data available
        </p>
        <p className="text-sm text-muted-foreground">
          Chain of title will appear here once the pipeline completes
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 pt-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Chain of Title
        </h3>
        <div className="flex items-center gap-3">
          {chain.chain_complete ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
              <CheckCircle2 className="h-3.5 w-3.5" /> Complete
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
              <AlertTriangle className="h-3.5 w-3.5" /> {chain.gap_count}{" "}
              gap(s)
            </span>
          )}
          <span className="text-xs text-muted-foreground">
            {chain.total_links} links
          </span>
        </div>
      </div>

      {chain.chain_links.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
            <Link2 className="h-7 w-7 text-muted-foreground/60" />
          </div>
          <p className="text-lg font-medium text-foreground/80 mb-1">
            No chain links found
          </p>
          <p className="text-sm text-muted-foreground">
            Links will be generated from parsed documents
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {chain.chain_links.map((link, i) => (
            <div key={link.id}>
              <div
                className={`section-card ${link.is_gap ? "border-amber-300 bg-amber-50/50" : ""}`}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold tabular-nums ${
                      link.is_gap
                        ? "bg-amber-100 text-amber-700 ring-1 ring-amber-300"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {link.position}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">
                        {link.from_party?.names?.join(", ") || "See Official Records"}
                      </span>
                      <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">
                        {link.to_party?.names?.join(", ") || "See Official Records"}
                      </span>
                    </div>
                    <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                      <span>{link.effective_date || "No date"}</span>
                      <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 capitalize">
                        {link.link_type}
                      </span>
                      {link.is_gap && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-amber-700 font-medium">
                          <AlertTriangle className="h-3 w-3" />
                          {link.gap_description}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              {i < chain.chain_links.length - 1 && (
                <div className="flex justify-center py-1">
                  <Link2 className="h-4 w-4 text-muted-foreground/30" />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
