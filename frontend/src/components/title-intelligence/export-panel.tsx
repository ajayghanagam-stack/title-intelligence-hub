"use client";

import { useState } from "react";
import { useOrg } from "@/hooks/use-org";
import { Download, Sparkles, FileText } from "lucide-react";
import { cn } from "@/lib/utils";

const audiences = [
  { value: "attorney", label: "Attorney Memo" },
  { value: "lender", label: "Lender Summary" },
  { value: "buyer", label: "Buyer Overview" },
  { value: "underwriter", label: "Underwriting Report" },
];

const formats = [
  { value: "markdown", label: "Markdown", icon: FileText },
  { value: "pdf", label: "PDF", icon: FileText },
  { value: "json", label: "JSON", icon: FileText },
];

export function ExportPanel({ packId }: { packId: string }) {
  const { orgFetch, orgFetchBlob } = useOrg();
  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [selectedAudience, setSelectedAudience] = useState("attorney");
  const [selectedFormat, setSelectedFormat] = useState("markdown");

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const data = await orgFetch<{ content: string }>(
        `/api/v1/apps/title-intelligence/packs/${packId}/reports`,
        {
          method: "POST",
          body: JSON.stringify({
            audience: selectedAudience,
            format: selectedFormat,
          }),
        }
      );
      setReport(data.content);
    } catch (error) {
      setReport(`Error: ${error instanceof Error ? error.message : "Failed to generate report"}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleDownload = async () => {
    setGenerating(true);
    try {
      const response = await orgFetchBlob(
        `/api/v1/apps/title-intelligence/packs/${packId}/reports/download`,
        {
          method: "POST",
          body: JSON.stringify({
            audience: selectedAudience,
            format: selectedFormat,
          }),
        }
      );

      const url = window.URL.createObjectURL(response);
      const a = document.createElement("a");
      a.href = url;
      const ext =
        selectedFormat === "pdf"
          ? "pdf"
          : selectedFormat === "json"
            ? "json"
            : "md";
      a.download = `report_${selectedAudience}.${ext}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch (error) {
      setReport(`Error: ${error instanceof Error ? error.message : "Failed to download report"}`);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="max-w-lg space-y-5">
      {/* Audience */}
      <div role="group" aria-label="Audience">
        <span className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2.5">
          Audience
        </span>
        <div className="grid grid-cols-2 gap-2">
          {audiences.map((a) => (
            <button
              key={a.value}
              type="button"
              onClick={() => setSelectedAudience(a.value)}
              className={cn(
                "rounded-xl px-4 py-2.5 text-sm font-medium ring-1 transition-all text-left",
                selectedAudience === a.value
                  ? "bg-amber-50 ring-amber-300 text-amber-700"
                  : "bg-card ring-border text-muted-foreground hover:ring-foreground/20"
              )}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      {/* Format */}
      <div role="group" aria-label="Format">
        <span className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2.5">
          Format
        </span>
        <div className="flex gap-2">
          {formats.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setSelectedFormat(f.value)}
              className={cn(
                "flex-1 rounded-xl px-4 py-2.5 text-sm font-medium ring-1 transition-all",
                selectedFormat === f.value
                  ? "bg-amber-50 ring-amber-300 text-amber-700"
                  : "bg-card ring-border text-muted-foreground hover:ring-foreground/20"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-1">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn-cta gap-2 flex-1"
        >
          <Sparkles className="h-4 w-4" />
          {generating ? "Generating..." : "Generate"}
        </button>
        <button
          onClick={handleDownload}
          disabled={generating}
          className="btn-secondary gap-2"
        >
          <Download className="h-4 w-4" />
          Download
        </button>
      </div>

      {report && (
        <div className="rounded-xl border bg-card p-5 mt-4">
          <pre className="whitespace-pre-wrap text-sm leading-relaxed font-mono text-foreground/80">
            {report}
          </pre>
        </div>
      )}
    </div>
  );
}
