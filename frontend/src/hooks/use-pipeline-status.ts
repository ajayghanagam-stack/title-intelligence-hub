"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useOrg } from "./use-org";
import type { TIPipelineStatus } from "@/lib/ti-types";

export function usePipelineStatus(packId: string, polling = false) {
  const { orgFetch } = useOrg();
  const [pipeline, setPipeline] = useState<TIPipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await orgFetch<TIPipelineStatus>(
        `/api/v1/apps/title-intelligence/packs/${packId}/pipeline`
      );
      setPipeline(data);
      setLoading(false);

      // Stop polling if completed or failed
      if (
        data.status === "completed" ||
        data.status === "failed"
      ) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    } catch {
      setLoading(false);
    }
  }, [orgFetch, packId]);

  useEffect(() => {
    fetchStatus();
    if (polling) {
      intervalRef.current = setInterval(fetchStatus, 3000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchStatus, polling]);

  return { pipeline, loading, refetch: fetchStatus };
}
