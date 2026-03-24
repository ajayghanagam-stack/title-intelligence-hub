"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Eye,
  FileBarChart,
  MessageCircle,
  Shield,
  AlertTriangle,
  FileText,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PackStatusBadge } from "@/components/title-intelligence/pack-status-badge";
import { PipelineProgress } from "@/components/title-intelligence/pipeline-progress";
import { ChatSlidePanel } from "@/components/title-intelligence/chat-slide-panel";
import { usePack } from "@/hooks/use-pack";
import { usePipelineStatus } from "@/hooks/use-pipeline-status";

export default function PackOverviewPage() {
  const params = useParams();
  const router = useRouter();
  const packId = params.packId as string;
  const { pack, loading, refetch } = usePack(packId);
  const isProcessing = pack?.status === "processing";
  const { pipeline } = usePipelineStatus(packId, isProcessing);
  const [showChat, setShowChat] = useState(false);
  const prevStatusRef = useRef(pack?.status);

  // Poll pack data while processing so we detect completion
  useEffect(() => {
    if (!isProcessing) return;
    const interval = setInterval(refetch, 3000);
    return () => clearInterval(interval);
  }, [isProcessing, refetch]);

  // Auto-redirect to results when pipeline completes
  useEffect(() => {
    if (prevStatusRef.current === "processing" && pack?.status === "completed") {
      router.push(`/apps/title-intelligence/packs/${packId}/results`);
    }
    prevStatusRef.current = pack?.status;
  }, [pack?.status, packId, router]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading pack...</p>
      </div>
    );
  }
  if (!pack) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-muted-foreground">Pack not found</p>
      </div>
    );
  }

  const isCompleted = pack.status === "completed";
  const totalPages = (pack.files ?? []).reduce(
    (sum, f) => sum + (f.page_count || 0),
    0
  );

  const scoreColor =
    pack.readiness_score !== null
      ? pack.readiness_score >= 90
        ? "text-emerald-700"
        : pack.readiness_score >= 60
          ? "text-amber-700"
          : "text-red-700"
      : "";

  const scoreBg =
    pack.readiness_score !== null
      ? pack.readiness_score >= 90
        ? "from-emerald-50 to-emerald-100/50 ring-emerald-200"
        : pack.readiness_score >= 60
          ? "from-amber-50 to-amber-100/50 ring-amber-200"
          : "from-red-50 to-red-100/50 ring-red-200"
      : "";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{pack.name}</h1>
        <div className="flex items-center gap-3 mt-2">
          <PackStatusBadge status={pack.status} stage={pack.current_stage} />
          <span className="text-sm text-muted-foreground">
            {(pack.files ?? []).length} file{(pack.files ?? []).length !== 1 ? "s" : ""}
            {totalPages > 0 && ` · ${totalPages} page${totalPages !== 1 ? "s" : ""}`}
          </span>
        </div>
      </div>

      {/* Readiness hero card — only show after pipeline completes */}
      {isCompleted && pack.readiness_score !== null && (
        <div className={cn("rounded-2xl bg-gradient-to-br ring-1 p-6", scoreBg)}>
          <div className="flex items-center gap-6">
            <div className="flex flex-col items-center">
              <span className={cn("text-5xl font-bold tabular-nums", scoreColor)}>
                {pack.readiness_score}
              </span>
              <span className="text-xs font-medium text-muted-foreground mt-1">of 100</span>
            </div>
            <div className="h-16 w-px bg-black/10" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <Shield className={cn("h-5 w-5", scoreColor)} />
                <span className={cn("font-semibold", scoreColor)}>
                  {pack.readiness_score >= 90 ? "Ready to Close" : pack.readiness_score >= 60 ? "At Risk" : "Not Ready"}
                </span>
              </div>
              {pack.readiness_summary && (
                <div className="flex items-start gap-2 mt-2">
                  <Sparkles className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                  <p className="text-sm text-foreground/80 leading-relaxed">
                    {pack.readiness_summary}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-3 flex-wrap">
        {(isCompleted || isProcessing) && (
          <Link
            href={`/apps/title-intelligence/packs/${packId}/documents`}
            className="btn-secondary gap-2"
          >
            <Eye className="h-4 w-4" />
            View Pages
          </Link>
        )}
        {isCompleted && (
          <>
            <Link
              href={`/apps/title-intelligence/packs/${packId}/results`}
              className="btn-cta gap-2"
            >
              <FileBarChart className="h-4 w-4" />
              View Results
              <ArrowRight className="h-4 w-4" />
            </Link>
            <button
              onClick={() => setShowChat(true)}
              className="btn-secondary gap-2"
            >
              <MessageCircle className="h-4 w-4" />
              AI Chat
            </button>
          </>
        )}
      </div>

      {/* Pipeline Progress */}
      {pipeline && <PipelineProgress stages={pipeline.stages} />}

      {/* Error message */}
      {pack.error_message && (
        <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 text-sm text-red-800 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 mt-0.5 shrink-0 text-red-600" />
          <div>
            <p className="font-medium mb-0.5">Pipeline Error</p>
            <p className="text-red-700/80">{pack.error_message}</p>
          </div>
        </div>
      )}

      {/* Files card */}
      {(pack.files ?? []).length > 0 && (
        <div className="section-card">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-4">
            Uploaded Files
          </h3>
          <div className="space-y-2">
            {(pack.files ?? []).map((f) => (
              <div
                key={f.id}
                className="flex items-center justify-between rounded-lg bg-muted/40 px-4 py-3 text-sm group hover:bg-muted/60 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-background">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <span className="font-medium">{f.filename}</span>
                </div>
                <span className="text-muted-foreground text-xs">
                  {(f.file_size / 1024 / 1024).toFixed(1)} MB
                  {f.page_count ? ` · ${f.page_count} pages` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Chat Slide Panel */}
      {isCompleted && (
        <ChatSlidePanel
          packId={packId}
          open={showChat}
          onClose={() => setShowChat(false)}
        />
      )}
    </div>
  );
}
