"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Download,
  Loader2,
  FileText,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { usePack } from "@/hooks/use-pack";
import { cn } from "@/lib/utils";
import type { Flag } from "@/lib/ti-types";

export default function ExportPage() {
  const params = useParams();
  const packId = params.packId as string;
  const { orgFetch, orgFetchBlob } = useOrg();
  const { pack } = usePack(packId);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);

  const fetchData = useCallback(async () => {
    try {
      const flagsData = await orgFetch<{ flags: Flag[] }>(`/api/v1/apps/title-intelligence/packs/${packId}/flags`);
      setFlags(flagsData.flags);
    } catch { /* non-critical preview data */ }
  }, [orgFetch, packId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleDownload = async () => {
    setDownloading(true);
    setError(null);
    try {
      const blob = await orgFetchBlob(
        `/api/v1/apps/title-intelligence/packs/${packId}/reports/download`,
        { method: "POST" }
      );
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const nameSlug = (pack?.name || "report").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 60);
      a.download = `${nameSlug}_title_intelligence_report.pdf`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download report");
    } finally {
      setDownloading(false);
    }
  };

  const criticalCount = flags.filter((f) => f.severity === "critical").length;
  const warningCount = flags.filter((f) => f.severity === "high" || f.severity === "medium").length;
  const resolvedCount = flags.filter((f) => f.status === "approved" || f.status === "rejected").length;

  return (
    <div className="space-y-6 max-w-3xl">
      {/* Back link */}
      <Link
        href={`/apps/title-intelligence/packs/${packId}/results`}
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Results
      </Link>

      {/* Hero card */}
      <div className="card-warm overflow-hidden">
        <div className="relative bg-gradient-to-br from-amber-500/10 via-orange-500/5 to-transparent p-6 sm:p-8">
          {/* Decorative circles */}
          <div className="absolute top-0 right-0 w-48 h-48 bg-gradient-to-bl from-amber-400/10 to-transparent rounded-full -translate-y-1/2 translate-x-1/4 pointer-events-none" />
          <div className="absolute bottom-0 left-0 w-32 h-32 bg-gradient-to-tr from-orange-400/8 to-transparent rounded-full translate-y-1/3 -translate-x-1/4 pointer-events-none" />

          <div className="relative flex flex-col sm:flex-row items-start sm:items-center gap-5">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 ring-1 ring-amber-500/20">
              <FileText className="h-7 w-7 text-amber-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h1 className="text-xl font-bold tracking-tight text-foreground">
                Title Intelligence Report
              </h1>
              {pack && (
                <p className="text-sm text-muted-foreground mt-0.5 truncate">{pack.name}</p>
              )}
              <p className="text-[13px] text-muted-foreground/80 mt-1.5 leading-relaxed max-w-lg">
                A comprehensive PDF with property details, executive summary, and all exceptions with recommended actions.
              </p>
            </div>
          </div>
        </div>

        {/* Report preview stats */}
        {flags.length > 0 && (
          <div className="border-t px-6 sm:px-8 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
              Report Preview
            </p>
            <div className="grid grid-cols-3 gap-3">
              {[
                { value: criticalCount, label: "Critical", icon: AlertTriangle, color: "text-red-500", bg: "bg-red-50" },
                { value: warningCount, label: "Warnings", icon: ShieldCheck, color: "text-amber-500", bg: "bg-amber-50" },
                { value: resolvedCount, label: "Resolved", icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-50" },
              ].map((stat) => {
                const Icon = stat.icon;
                return (
                  <div key={stat.label} className="flex items-center gap-2.5 rounded-lg border bg-card/50 px-3 py-2.5">
                    <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", stat.bg)}>
                      <Icon className={cn("h-4 w-4", stat.color)} />
                    </div>
                    <div>
                      <p className={cn("text-lg font-bold leading-none", stat.color)}>{stat.value}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">{stat.label}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Download action */}
        <div className="border-t px-6 sm:px-8 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 bg-muted/20">
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <FileText className="h-4 w-4 shrink-0" />
            <span>PDF format &middot; Includes all {flags.length} exception{flags.length !== 1 ? "s" : ""}</span>
          </div>
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading}
            className={cn(
              "btn-cta gap-2 py-2.5 px-6 text-sm",
              downloading && "opacity-80"
            )}
          >
            {downloading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {downloading ? "Generating..." : "Download PDF"}
          </button>
        </div>
      </div>

      {/* What's included */}
      <div className="section-card">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-3">
          What&apos;s Included
        </h2>
        <ul className="space-y-2.5">
          {[
            "Transaction summary with all parties and policy details",
            "Risk summary with severity breakdown and flag table",
            "Schedule B exceptions (standard and specific)",
            "Schedule C requirements with satisfaction status",
            "Key warnings and observations for critical issues",
            "Pre-closing checklist",
            "Legal disclaimer",
          ].map((item) => (
            <li key={item} className="flex items-start gap-2.5 text-sm text-muted-foreground">
              <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0 mt-0.5" />
              {item}
            </li>
          ))}
        </ul>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 text-sm text-red-700 flex items-start gap-2.5">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}
    </div>
  );
}
