"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, FileText, Braces, Sparkles } from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { usePack } from "@/hooks/use-pack";
import { cn } from "@/lib/utils";

const audiences = [
  { value: "attorney", label: "Attorney Memo", description: "Legal analysis with citations" },
  { value: "lender", label: "Lender Summary", description: "Concise risk overview for lenders" },
  { value: "buyer", label: "Buyer Overview", description: "Plain-language summary for buyers" },
  { value: "underwriter", label: "Underwriting Report", description: "Detailed underwriting analysis" },
];

const formats = [
  { value: "pdf", label: "PDF", icon: FileText, ext: "pdf" },
  { value: "json", label: "JSON", icon: Braces, ext: "json" },
];

export default function ExportPage() {
  const params = useParams();
  const packId = params.packId as string;
  const { orgFetchBlob } = useOrg();
  const { pack } = usePack(packId);
  const [selectedAudience, setSelectedAudience] = useState("attorney");
  const [generating, setGenerating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDownload = async (format: string) => {
    setGenerating(format);
    setError(null);
    try {
      const response = await orgFetchBlob(
        `/api/v1/apps/title-intelligence/packs/${packId}/reports/download`,
        {
          method: "POST",
          body: JSON.stringify({
            audience: selectedAudience,
            format,
          }),
        }
      );

      const url = window.URL.createObjectURL(response);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report_${selectedAudience}.${format === "pdf" ? "pdf" : "json"}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download report");
    } finally {
      setGenerating(null);
    }
  };

  return (
    <div className="space-y-8 max-w-2xl">
      {/* Header */}
      <div>
        <Link
          href={`/apps/title-intelligence/packs/${packId}/results`}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Results
        </Link>
        <h1 className="text-2xl font-bold tracking-tight">Export Report</h1>
        {pack && (
          <p className="text-sm text-muted-foreground mt-1">{pack.name}</p>
        )}
      </div>

      {/* Audience selection */}
      <div className="section-card">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Select Audience
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {audiences.map((a) => (
            <button
              key={a.value}
              type="button"
              onClick={() => setSelectedAudience(a.value)}
              className={cn(
                "rounded-xl px-5 py-4 text-left ring-1 transition-all",
                selectedAudience === a.value
                  ? "bg-amber-50 ring-amber-300 text-amber-800 shadow-sm"
                  : "bg-card ring-border text-foreground hover:ring-foreground/20"
              )}
            >
              <p className="text-sm font-semibold">{a.label}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{a.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Format + Download */}
      <div className="section-card">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Download Format
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {formats.map((f) => {
            const Icon = f.icon;
            const isGenerating = generating === f.value;
            return (
              <button
                key={f.value}
                type="button"
                onClick={() => handleDownload(f.value)}
                disabled={generating !== null}
                className={cn(
                  "flex items-center gap-4 rounded-xl px-5 py-4 ring-1 transition-all text-left",
                  "bg-card ring-border hover:ring-primary/40 hover:bg-primary/5",
                  generating !== null && !isGenerating && "opacity-50 cursor-not-allowed"
                )}
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 shrink-0">
                  {isGenerating ? (
                    <Sparkles className="h-5 w-5 text-primary animate-pulse" />
                  ) : (
                    <Icon className="h-5 w-5 text-primary" />
                  )}
                </div>
                <div>
                  <p className="text-sm font-semibold">
                    {isGenerating ? "Generating..." : `Download ${f.label}`}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {f.value === "pdf" ? "Formatted report document" : "Structured data export"}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
