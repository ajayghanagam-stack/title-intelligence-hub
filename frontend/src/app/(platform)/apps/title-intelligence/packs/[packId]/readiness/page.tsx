"use client";

import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { ReadinessDashboard } from "@/components/title-intelligence/readiness-dashboard";
import { ClosingChecklist } from "@/components/title-intelligence/closing-checklist";
import { useOrg } from "@/hooks/use-org";
import { Gauge } from "lucide-react";
import type { ReadinessData } from "@/lib/ti-types";

export default function ReadinessPage() {
  const params = useParams();
  const packId = params.packId as string;
  const { orgFetch } = useOrg();
  const [readiness, setReadiness] = useState<ReadinessData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    orgFetch<ReadinessData>(`/api/v1/apps/title-intelligence/packs/${packId}/readiness`)
      .then(setReadiness)
      .catch(() => setReadiness(null))
      .finally(() => setLoading(false));
  }, [orgFetch, packId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }
  if (!readiness) return <p className="text-muted-foreground">No data available</p>;

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div className="flex items-center gap-2.5">
        <Gauge className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Closing Readiness</h2>
      </div>

      <ReadinessDashboard data={readiness} />

      {readiness.checklist && readiness.checklist.length > 0 && (
        <div>
          <h3 className="text-base font-semibold mb-3">Closing Checklist</h3>
          <ClosingChecklist items={readiness.checklist} />
        </div>
      )}
    </div>
  );
}
