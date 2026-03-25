"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { usePipelineStatus } from "@/hooks/use-pipeline-status";
import { FlagsTable } from "@/components/title-intelligence/flags-table";
import { ChatSlidePanel } from "@/components/title-intelligence/chat-slide-panel";
import { PipelineProgress } from "@/components/title-intelligence/pipeline-progress";
import {
  Download,
  RefreshCw,
  Send,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import type { Flag, Extraction, ReadinessData, ReviewDecision, Pack, Recommendation } from "@/lib/ti-types";

type FilterKey = "all" | "critical" | "warning" | "review";

function extractValue(ext: Extraction): string {
  const v = ext.value;
  if (typeof v === "string") return v;
  if (v && typeof v === "object") {
    for (const key of ["value", "address", "full_address", "name", "amount", "number", "date", "text"]) {
      if (typeof (v as Record<string, unknown>)[key] === "string") return (v as Record<string, unknown>)[key] as string;
    }
    for (const val of Object.values(v)) {
      if (typeof val === "string" && val.length > 0) return val;
    }
  }
  return "";
}

function findExtraction(extractions: Extraction[], type: string, ...labelPatterns: string[]): string {
  for (const pat of labelPatterns) {
    const lowerPat = pat.toLowerCase();
    const match = extractions.find(
      (e) => e.extraction_type === type && e.label.toLowerCase().includes(lowerPat)
    );
    if (match) {
      const val = extractValue(match);
      if (val) return val;
    }
  }
  return "";
}

export default function ResultsPage() {
  const params = useParams();
  const packId = params.packId as string;
  const { orgFetch, orgFetchBlob } = useOrg();

  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");
  const [flags, setFlags] = useState<Flag[]>([]);
  const [extractions, setExtractions] = useState<Extraction[]>([]);
  const [readiness, setReadiness] = useState<ReadinessData | null>(null);
  const [pack, setPack] = useState<Pack | null>(null);
  const [packName, setPackName] = useState<string>("");
  const [flagsLoading, setFlagsLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [chatInitialQuestion, setChatInitialQuestion] = useState<string>("");
  const [inlineQuestion, setInlineQuestion] = useState("");
  const [reanalyzing, setReanalyzing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const { showToast } = useToast();

  const isProcessing = pack?.status === "processing";
  const { pipeline } = usePipelineStatus(packId, isProcessing);
  const prevStatusRef = useRef(pack?.status);

  const fetchFlags = useCallback(async () => {
    try {
      const data = await orgFetch<{ flags: Flag[] }>(`/api/v1/apps/title-intelligence/packs/${packId}/flags`);
      setFlags(data.flags);
    } catch { setFlags([]); showToast("error", "Failed to load flags"); }
    finally { setFlagsLoading(false); }
  }, [orgFetch, packId, showToast]);

  const fetchExtractions = useCallback(async () => {
    try {
      const data = await orgFetch<Extraction[]>(`/api/v1/apps/title-intelligence/packs/${packId}/extractions`);
      setExtractions(data);
    } catch { setExtractions([]); }
  }, [orgFetch, packId]);

  const fetchReadiness = useCallback(async () => {
    try {
      const data = await orgFetch<ReadinessData>(`/api/v1/apps/title-intelligence/packs/${packId}/readiness`);
      setReadiness(data);
    } catch { setReadiness(null); }
  }, [orgFetch, packId]);

  const fetchPack = useCallback(async () => {
    try {
      const data = await orgFetch<Pack>(`/api/v1/apps/title-intelligence/packs/${packId}`);
      setPack(data);
      setPackName(data.name);
    } catch { /* non-critical */ }
  }, [orgFetch, packId]);

  const handleReanalyze = async () => {
    if (!confirm("This will reprocess the entire package through the AI pipeline. All existing analysis results will be replaced.")) return;
    setReanalyzing(true);
    try {
      await orgFetch<unknown>(`/api/v1/apps/title-intelligence/packs/${packId}/process`, { method: "POST" });
      showToast("success", "Re-analysis started");
      // Set pack status locally so pipeline progress UI appears immediately
      setPack((prev) => prev ? { ...prev, status: "processing" as Pack["status"] } : prev);
      fetchPack();
    } catch {
      showToast("error", "Failed to start re-analysis");
    } finally {
      setReanalyzing(false);
    }
  };

  const handleDownloadReport = async () => {
    setDownloading(true);
    try {
      const blob = await orgFetchBlob(
        `/api/v1/apps/title-intelligence/packs/${packId}/reports/download`,
        { method: "POST" }
      );
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "title_intelligence_report.pdf";
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch {
      showToast("error", "Failed to download report");
    } finally {
      setDownloading(false);
    }
  };

  const handleInlineAsk = () => {
    if (!inlineQuestion.trim()) return;
    setChatInitialQuestion(inlineQuestion.trim());
    setInlineQuestion("");
    setShowChat(true);
  };

  useEffect(() => {
    fetchFlags();
    fetchExtractions();
    fetchReadiness();
    fetchPack();
  }, [fetchFlags, fetchExtractions, fetchReadiness, fetchPack]);

  // Poll pack data while processing to detect completion
  useEffect(() => {
    if (!isProcessing) return;
    const interval = setInterval(fetchPack, 3000);
    return () => clearInterval(interval);
  }, [isProcessing, fetchPack]);

  // Refresh all data when pipeline completes
  useEffect(() => {
    if (prevStatusRef.current === "processing" && pack?.status === "completed") {
      setFlagsLoading(true);
      fetchFlags();
      fetchExtractions();
      fetchReadiness();
    }
    prevStatusRef.current = pack?.status;
  }, [pack?.status, fetchFlags, fetchExtractions, fetchReadiness]);

  const handleReview = async (flagId: string, decision: ReviewDecision, reasonCode: string | null, notes: string) => {
    setSubmitting(true);
    try {
      await orgFetch<unknown>(`/api/v1/apps/title-intelligence/packs/${packId}/flags/${flagId}/review`, {
        method: "POST",
        body: JSON.stringify({ decision, reason_code: reasonCode, notes }),
      });
      fetchFlags();
      fetchReadiness();
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "Failed to submit review");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGetRecommendation = async (flagId: string) => {
    return await orgFetch<Recommendation>(`/api/v1/apps/title-intelligence/packs/${packId}/flags/${flagId}/recommend`, { method: "POST" });
  };

  const propertyAddress = findExtraction(extractions, "property_info", "address", "property address", "full_address");
  const displayTitle = propertyAddress || packName || "Analysis Results";
  const orderNumber = findExtraction(extractions, "property_info", "commitment number", "order number", "order no", "commitment_number");
  const commitmentDate = findExtraction(extractions, "property_info", "effective date", "commitment date", "effective_date");
  const issuedBy = findExtraction(extractions, "party", "title company", "underwriter", "issuer", "issued by");

  const criticalCount = flags.filter((f) => f.severity === "critical").length;
  const warningCount = flags.filter((f) => f.severity === "high" || f.severity === "medium").length;
  const underReviewCount = flags.filter((f) => f.status === "open" || f.status === "escalated").length;
  const validationScore = readiness ? Math.round(readiness.score / 10) : 0;

  const analyzedAt = pack?.status === "completed" && pack?.updated_at
    ? new Date(pack.updated_at).toLocaleString("en-US", { month: "numeric", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true })
    : null;

  const filteredFlags = flags.filter((f) => {
    if (activeFilter === "critical") return f.severity === "critical";
    if (activeFilter === "warning") return f.severity === "high" || f.severity === "medium";
    if (activeFilter === "review") return f.status === "open" || f.status === "escalated";
    return true;
  });

  const uniqueDocs = new Set(flags.flatMap((f) => (f.evidence_refs || []).map((r) => r.page_number))).size;
  const actionableCount = flags.filter((f) => f.status === "open").length;

  const filterTabs: { key: FilterKey; label: string; count: number }[] = [
    { key: "all", label: "All", count: flags.length },
    { key: "critical", label: "Critical", count: criticalCount },
    { key: "warning", label: "Warning", count: warningCount },
    { key: "review", label: "Review", count: underReviewCount },
  ];

  return (
    <div className="space-y-5 max-w-[1400px]">
      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-foreground">{displayTitle}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-[13px] text-muted-foreground">
            {orderNumber && <span>Order No: {orderNumber}</span>}
            {commitmentDate && <span>Commitment Date: {commitmentDate}</span>}
            {issuedBy && <span>Issued by: {issuedBy}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {analyzedAt && (
            <span className="text-[11px] text-muted-foreground/70 mr-1 hidden xl:block">Analyzed on {analyzedAt}</span>
          )}
          <button
            onClick={handleReanalyze}
            disabled={reanalyzing || pack?.status === "processing"}
            className="btn-secondary gap-1.5 text-xs py-2 px-3"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", reanalyzing && "animate-spin")} />
            Re-analyze
          </button>
          <button
            onClick={handleDownloadReport}
            disabled={downloading}
            className="btn-cta gap-1.5 text-xs py-2 px-4"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {downloading ? "Generating..." : "Export Full Report"}
          </button>
        </div>
      </div>

      {/* ── Pipeline Progress ── */}
      {isProcessing && pipeline && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
            <p className="text-sm font-medium text-amber-800">Re-analyzing package...</p>
          </div>
          <PipelineProgress stages={pipeline.stages} />
        </div>
      )}

      {/* ── Summary Cards ── */}
      {!flagsLoading && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { value: criticalCount, label: "Critical Issues", sub: "Require immediate resolution", color: "border-l-red-500", text: "text-red-600" },
            { value: warningCount, label: "Warnings", sub: "Require attention before closing", color: "border-l-amber-500", text: "text-amber-600" },
            { value: underReviewCount, label: "Under Review", sub: "Examiner judgment required", color: "border-l-blue-500", text: "text-blue-600" },
          ].map((card) => (
            <div key={card.label} className={cn("rounded-lg border bg-card p-4 border-l-4", card.color)}>
              <p className={cn("text-2xl font-bold", card.text)}>{card.value}</p>
              <p className="text-xs font-medium text-foreground/80 mt-0.5">{card.label}</p>
              <p className="text-[10px] text-muted-foreground">{card.sub}</p>
            </div>
          ))}
          <div className="rounded-lg border bg-card p-4 border-l-4 border-l-emerald-500">
            <p className="text-2xl font-bold text-emerald-600">
              {validationScore}<span className="text-sm font-normal text-muted-foreground"> / 10</span>
            </p>
            <p className="text-xs font-medium text-foreground/80 mt-0.5">Validation Score</p>
            <p className="text-[10px] text-muted-foreground">Requirements met</p>
          </div>
        </div>
      )}

      {/* ── Summary sentence ── */}
      {!flagsLoading && (
        <p className="text-[13px] text-muted-foreground leading-relaxed">
          This package contains {criticalCount} critical issue{criticalCount !== 1 ? "s" : ""} requiring resolution before closing, {warningCount} warning{warningCount !== 1 ? "s" : ""}, and passed {validationScore} of 10 standard validation requirements.
        </p>
      )}

      {/* ── Ask a Question ── */}
      <div className="rounded-lg border bg-card px-4 py-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">Ask a Question</p>
        <div className="flex gap-2">
          <input
            type="text"
            value={inlineQuestion}
            onChange={(e) => setInlineQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleInlineAsk()}
            placeholder="Ask a question about this package..."
            className="flex-1 h-9 rounded-md border bg-background px-3 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-brand-amber/30 transition-shadow"
          />
          <button
            onClick={handleInlineAsk}
            disabled={!inlineQuestion.trim()}
            className="btn-cta h-9 px-4 text-xs gap-1.5"
          >
            <Send className="h-3.5 w-3.5" />
            Ask
          </button>
        </div>
      </div>

      {/* ── Exceptions & Required Actions — contained section ── */}
      <div className="rounded-xl border bg-card overflow-hidden">
        {/* Section header */}
        <div className="px-5 pt-5 pb-3">
          <h2 className="text-base font-bold tracking-tight text-foreground">Exceptions & Required Actions</h2>
          <p className="text-[13px] text-muted-foreground mt-0.5">Issues identified requiring resolution prior to closing</p>
        </div>

        {/* Filter tabs */}
        {!flagsLoading && (
          <div className="flex items-center gap-0.5 px-5 border-b">
            {filterTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveFilter(tab.key)}
                className={cn(
                  "relative px-3 py-2 text-[13px] font-medium transition-colors rounded-t-md",
                  activeFilter === tab.key
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground/80"
                )}
              >
                {tab.label} ({tab.count})
                {activeFilter === tab.key && (
                  <span className="absolute bottom-0 inset-x-1 h-[2px] bg-brand-amber rounded-t" />
                )}
              </button>
            ))}
          </div>
        )}

        {/* Stats line */}
        {!flagsLoading && flags.length > 0 && (
          <div className="px-5 py-2.5 bg-muted/20 border-b">
            <p className="text-[12px] text-muted-foreground">
              {flags.length} issue{flags.length !== 1 ? "s" : ""} found across {uniqueDocs} document{uniqueDocs !== 1 ? "s" : ""} &mdash; {actionableCount} require action before closing
            </p>
          </div>
        )}

        {/* Table */}
        <div className="px-0">
          {flagsLoading ? (
            <div className="flex items-center gap-2 py-16 justify-center">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-sm text-muted-foreground">Loading...</p>
            </div>
          ) : (
            <FlagsTable
              flags={filteredFlags}
              packId={packId}
              onReview={handleReview}
              onGetRecommendation={handleGetRecommendation}
              submitting={submitting}
            />
          )}
        </div>
      </div>

      {/* Chat Slide Panel */}
      <ChatSlidePanel
        packId={packId}
        open={showChat}
        onClose={() => { setShowChat(false); setChatInitialQuestion(""); }}
        initialQuestion={chatInitialQuestion}
      />
    </div>
  );
}
