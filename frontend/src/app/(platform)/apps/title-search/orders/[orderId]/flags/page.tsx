"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { getFlags, reviewFlag } from "@/lib/title-search/api";
import { SEVERITY_COLORS } from "@/lib/title-search/constants";
import type { TSFlagList } from "@/lib/title-search/types";
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

export default function FlagsPage() {
  const params = useParams();
  const orderId = params.orderId as string;
  const { currentOrgId } = useOrg();
  const [data, setData] = useState<TSFlagList | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchFlags = useCallback(async () => {
    if (!currentOrgId || !orderId) return;
    try {
      const result = await getFlags(currentOrgId, orderId);
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [currentOrgId, orderId]);

  useEffect(() => {
    fetchFlags();
  }, [fetchFlags]);

  const handleReview = async (flagId: string, decision: string) => {
    if (!currentOrgId) return;
    try {
      await reviewFlag(currentOrgId, orderId, flagId, { decision });
      await fetchFlags();
    } catch {
      // ignore
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading flags...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
          <AlertTriangle className="h-7 w-7 text-muted-foreground/60" />
        </div>
        <p className="text-lg font-medium text-foreground/80 mb-1">
          No flag data available
        </p>
        <p className="text-sm text-muted-foreground">
          Flags will appear here after the pipeline analyzes your documents
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 pt-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Flags ({data.flags.length})
        </h3>
        <div className="flex gap-2">
          {Object.entries(data.counts).map(([severity, count]) => (
            <span
              key={severity}
              className={cn(
                "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize",
                SEVERITY_COLORS[severity] || ""
              )}
            >
              {count} {severity}
            </span>
          ))}
        </div>
      </div>

      {data.flags.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-50 mb-4">
            <ShieldCheck className="h-7 w-7 text-emerald-600" />
          </div>
          <p className="text-lg font-medium text-foreground/80 mb-1">
            No issues detected
          </p>
          <p className="text-sm text-muted-foreground">
            No risk flags were found in this title search
          </p>
        </div>
      ) : (
        <div className="grid gap-3">
          {data.flags.map((flag) => (
            <div key={flag.id} className="section-card">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-muted-foreground shrink-0" />
                    <span className="font-medium">{flag.title}</span>
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize",
                        SEVERITY_COLORS[flag.severity] || ""
                      )}
                    >
                      {flag.severity}
                    </span>
                    {flag.status !== "open" && (
                      <span
                        className={cn(
                          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium capitalize",
                          flag.status === "approved"
                            ? "bg-green-100 text-green-800"
                            : "bg-red-100 text-red-800"
                        )}
                      >
                        {flag.status}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground mt-1.5">
                    {flag.description}
                  </p>
                  <p className="text-xs text-muted-foreground/70 mt-1">
                    {flag.flag_type.replace(/_/g, " ")}
                  </p>
                </div>
                {flag.status === "open" && (
                  <div className="flex gap-1.5 shrink-0 ml-4">
                    <button
                      onClick={() => handleReview(flag.id, "approve")}
                      className="flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-emerald-50 hover:text-emerald-600 transition-colors"
                      title="Approve"
                    >
                      <CheckCircle2 className="h-5 w-5" />
                    </button>
                    <button
                      onClick={() => handleReview(flag.id, "reject")}
                      className="flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground hover:bg-red-50 hover:text-red-600 transition-colors"
                      title="Reject"
                    >
                      <XCircle className="h-5 w-5" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
