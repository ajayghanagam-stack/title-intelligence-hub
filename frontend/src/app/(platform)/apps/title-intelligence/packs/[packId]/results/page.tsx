"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useOrg } from "@/hooks/use-org";
import { FlagsTable } from "@/components/title-intelligence/flags-table";
import { ExtractionTable } from "@/components/title-intelligence/extraction-table";
import { ReadinessDashboard } from "@/components/title-intelligence/readiness-dashboard";
import { ClosingChecklist } from "@/components/title-intelligence/closing-checklist";
import { ChatSlidePanel } from "@/components/title-intelligence/chat-slide-panel";
import {
  MessageCircle,
  Download,
  AlertTriangle,
  FileCheck,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import type { Flag, Extraction, ReadinessData, ReviewDecision, Pack, Recommendation } from "@/lib/ti-types";

type TabKey = "flags" | "checklist" | "extractions";

const TABS: { key: TabKey; label: string; icon: React.ElementType }[] = [
  { key: "flags", label: "Risk Flags", icon: AlertTriangle },
  { key: "checklist", label: "Checklist", icon: FileCheck },
  { key: "extractions", label: "Extractions", icon: Layers },
];

export default function ResultsPage() {
  const params = useParams();
  const packId = params.packId as string;
  const { orgFetch } = useOrg();

  const [activeTab, setActiveTab] = useState<TabKey>("flags");
  const [flags, setFlags] = useState<Flag[]>([]);
  const [extractions, setExtractions] = useState<Extraction[]>([]);
  const [readiness, setReadiness] = useState<ReadinessData | null>(null);
  const [packName, setPackName] = useState<string>("");
  const [flagsLoading, setFlagsLoading] = useState(true);
  const [extractionsLoading, setExtractionsLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [showChat, setShowChat] = useState(false);
  const { showToast } = useToast();

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
    } catch { setExtractions([]); showToast("error", "Failed to load extractions"); }
    finally { setExtractionsLoading(false); }
  }, [orgFetch, packId, showToast]);

  const fetchReadiness = useCallback(async () => {
    try {
      const data = await orgFetch<ReadinessData>(`/api/v1/apps/title-intelligence/packs/${packId}/readiness`);
      setReadiness(data);
    } catch { setReadiness(null); showToast("error", "Failed to load readiness data"); }
  }, [orgFetch, packId, showToast]);

  const fetchPack = useCallback(async () => {
    try {
      const data = await orgFetch<Pack>(`/api/v1/apps/title-intelligence/packs/${packId}`);
      setPackName(data.name);
    } catch { /* Pack name is non-critical UI label */ }
  }, [orgFetch, packId]);

  useEffect(() => {
    fetchFlags();
    fetchExtractions();
    fetchReadiness();
    fetchPack();
  }, [fetchFlags, fetchExtractions, fetchReadiness, fetchPack]);

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
      setReviewError(error instanceof Error ? error.message : "Failed to submit review");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGetRecommendation = async (flagId: string) => {
    return await orgFetch<Recommendation>(`/api/v1/apps/title-intelligence/packs/${packId}/flags/${flagId}/recommend`, { method: "POST" });
  };

  const tabCounts: Record<TabKey, number | undefined> = {
    flags: flagsLoading ? undefined : flags.length,
    checklist: readiness?.checklist?.length,
    extractions: extractionsLoading ? undefined : extractions.length,
  };

  // Hide checklist tab if no items
  const visibleTabs = TABS.filter(
    (t) => t.key !== "checklist" || (readiness?.checklist && readiness.checklist.length > 0)
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analysis Results</h1>
          <p className="text-sm text-muted-foreground mt-1">{packName}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowChat(!showChat)}
            className={cn("btn-secondary gap-2", showChat && "ring-2 ring-primary/30")}
          >
            <MessageCircle className="h-4 w-4" />
            AI Chat
          </button>
          <Link
            href={`/apps/title-intelligence/packs/${packId}/export`}
            className="btn-secondary gap-2"
          >
            <Download className="h-4 w-4" />
            Export
          </Link>
        </div>
      </div>

      {/* Readiness Dashboard */}
      {readiness && <ReadinessDashboard data={readiness} />}

      {/* Tabs + content */}
      <div className="section-card p-0 overflow-hidden">
        {/* Tab bar */}
        <div className="flex border-b bg-muted/20">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.key;
            const count = tabCounts[tab.key];
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "flex items-center gap-2 px-5 py-3.5 text-sm font-medium transition-all relative",
                  isActive
                    ? "text-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
                {count !== undefined && (
                  <span className={cn(
                    "inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full text-[11px] font-semibold tabular-nums",
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground"
                  )}>
                    {count}
                  </span>
                )}
                {/* Active indicator */}
                {isActive && (
                  <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-t-full" />
                )}
              </button>
            );
          })}
        </div>

        {/* Tab content */}
        <div className="p-5">
          {activeTab === "flags" && (
            flagsLoading ? (
              <div className="flex items-center gap-2 py-10 justify-center">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <p className="text-sm text-muted-foreground">Loading flags...</p>
              </div>
            ) : (
              <FlagsTable
                flags={flags}
                packId={packId}
                onReview={handleReview}
                onGetRecommendation={handleGetRecommendation}
                submitting={submitting}
              />
            )
          )}

          {activeTab === "checklist" && readiness?.checklist && (
            <ClosingChecklist
              items={readiness.checklist}
              packId={packId}
              onAction={() => { fetchFlags(); fetchReadiness(); }}
            />
          )}

          {activeTab === "extractions" && (
            extractionsLoading ? (
              <div className="flex items-center gap-2 py-10 justify-center">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <p className="text-sm text-muted-foreground">Loading extractions...</p>
              </div>
            ) : (
              <ExtractionTable extractions={extractions} />
            )
          )}
        </div>
      </div>

      {/* Chat Slide Panel */}
      <ChatSlidePanel
        packId={packId}
        open={showChat}
        onClose={() => setShowChat(false)}
      />
    </div>
  );
}
