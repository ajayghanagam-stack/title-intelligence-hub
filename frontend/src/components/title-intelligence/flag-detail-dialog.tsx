"use client";

import { useEffect } from "react";
import { X, FileText } from "lucide-react";
import { SeverityBadge } from "./severity-badge";
import { ReviewForm } from "./review-form";
import { ReviewAssistantPanel } from "./review-assistant-panel";
import { STATUS_COLORS } from "@/lib/ti-constants";
import { useFocusTrap } from "@/hooks/use-focus-trap";
import type { Flag, ReviewDecision } from "@/lib/ti-types";

export function FlagDetailDialog({
  flag,
  onReview,
  onGetRecommendation,
  onClose,
  submitting,
}: {
  flag: Flag;
  onReview: (decision: ReviewDecision, reasonCode: string | null, notes: string) => void;
  onGetRecommendation: () => Promise<{ decision: string; reasoning: string; confidence: number }>;
  onClose: () => void;
  submitting?: boolean;
}) {
  const trapRef = useFocusTrap(true);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div role="dialog" aria-modal="true" aria-label={`Flag details: ${flag.title}`} className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div ref={trapRef} className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-background p-6 shadow-2xl mx-4">
        {/* Header */}
        <div className="flex items-start justify-between mb-5">
          <div className="flex-1 mr-4">
            <h2 className="text-lg font-semibold">{flag.title}</h2>
            <div className="flex items-center gap-2 mt-2">
              <SeverityBadge severity={flag.severity} />
              <span className="text-xs text-muted-foreground capitalize">{flag.flag_type.replace(/_/g, " ")}</span>
              <span
                className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize ${
                  STATUS_COLORS[flag.status] || ""
                }`}
              >
                {flag.status}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-full p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5">
          {/* Description */}
          <div>
            <h4 className="text-sm font-medium mb-1.5">Description</h4>
            <p className="text-sm text-muted-foreground leading-relaxed">{flag.description}</p>
          </div>

          {/* Executive Summary */}
          <div className="rounded-lg bg-primary/5 border border-primary/20 p-4">
            <h4 className="text-sm font-medium mb-1.5">Executive Summary</h4>
            <p className="text-sm text-muted-foreground leading-relaxed">{flag.ai_explanation}</p>
          </div>

          {/* Evidence */}
          {flag.evidence_refs.length > 0 && (
            <div>
              <h4 className="text-sm font-medium mb-1.5">Evidence</h4>
              <div className="space-y-1.5">
                {flag.evidence_refs.map((ref, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 rounded-lg bg-muted/50 border p-2.5 text-xs"
                  >
                    <FileText className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                    <div>
                      <span className="font-medium">Page {ref.page_number}:</span>{" "}
                      {ref.text_snippet}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* AI Recommendation */}
          <ReviewAssistantPanel onGetRecommendation={onGetRecommendation} />

          {/* Review Form */}
          {flag.status === "open" && (
            <div>
              <h4 className="text-sm font-medium mb-3">Submit Review</h4>
              <ReviewForm onSubmit={onReview} submitting={submitting} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
