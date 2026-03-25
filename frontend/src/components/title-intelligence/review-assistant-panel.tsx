"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Sparkles, Loader2 } from "lucide-react";
import type { Recommendation } from "@/lib/ti-types";

export function ReviewAssistantPanel({
  onGetRecommendation,
}: {
  onGetRecommendation: () => Promise<Recommendation>;
}) {
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGet = async () => {
    setLoading(true);
    setError(null);
    try {
      const rec = await onGetRecommendation();
      setRecommendation(rec);
    } catch {
      setError("Failed to get recommendation.");
    } finally {
      setLoading(false);
    }
  };

  if (!recommendation && !loading) {
    return (
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium">Review Assistant</span>
          </div>
          <Button size="sm" variant="outline" onClick={handleGet}>
            Get Recommendation
          </Button>
        </div>
        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          Analyzing flag...
        </div>
      </div>
    );
  }

  const decisionLabel =
    recommendation!.decision === "approve"
      ? "Approve"
      : recommendation!.decision === "reject"
      ? "Reject"
      : "Escalate";
  const decisionColor =
    recommendation!.decision === "approve"
      ? "text-green-700 bg-green-50"
      : recommendation!.decision === "reject"
      ? "text-red-700 bg-red-50"
      : "text-purple-700 bg-purple-50";

  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">Recommendation</span>
      </div>
      <div className="flex items-center gap-3">
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${decisionColor}`}>
          {decisionLabel}
        </span>
        <span className="text-xs text-muted-foreground">
          Confidence: {Math.round(recommendation!.confidence * 100)}%
        </span>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">
        {recommendation!.reasoning}
      </p>
    </div>
  );
}
