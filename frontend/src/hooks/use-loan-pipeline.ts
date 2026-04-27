"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useOrg } from "@/hooks/use-org";
import { getToken } from "@/lib/auth";
import { getPipelineStatus } from "@/lib/loan-onboarding/api";
import type { LoanPipelineStatus } from "@/lib/loan-onboarding/types";

const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "awaiting_review",
]);

/**
 * SSE-first with 3s polling fallback for loan onboarding package pipeline.
 * Mirrors the pattern used by `use-pipeline-status` for TI.
 */
export function useLoanPipeline(packageId: string, polling = true) {
  const { currentOrgId } = useOrg();
  const [pipeline, setPipeline] = useState<LoanPipelineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!currentOrgId || !packageId) return;
    try {
      const data = await getPipelineStatus(currentOrgId, packageId);
      setPipeline(data);
      setLoading(false);

      if (TERMINAL_STATUSES.has(data.status)) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    } catch {
      setLoading(false);
    }
  }, [currentOrgId, packageId]);

  useEffect(() => {
    if (!polling || !currentOrgId) {
      if (!polling) fetchStatus();
      return;
    }

    const token = getToken();
    if (!token) {
      fetchStatus();
      intervalRef.current = setInterval(fetchStatus, 3000);
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current);
      };
    }

    const abortController = new AbortController();
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
    const url = `${apiUrl}/api/v1/apps/loan-onboarding/packages/${packageId}/pipeline/stream`;
    let active = true;

    async function connectSSE() {
      try {
        const response = await fetch(url, {
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Org-Id": currentOrgId!,
          },
          signal: abortController.signal,
        });

        if (!response.ok || !response.body) {
          if (active && !intervalRef.current) {
            intervalRef.current = setInterval(fetchStatus, 3000);
          }
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done || !active) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6)) as LoanPipelineStatus;
                setPipeline(data);
                setLoading(false);
                if (TERMINAL_STATUSES.has(data.status)) {
                  active = false;
                  abortController.abort();
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (active && !intervalRef.current) {
          intervalRef.current = setInterval(fetchStatus, 3000);
        }
      }
    }

    fetchStatus();
    connectSSE();

    return () => {
      active = false;
      abortController.abort();
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [polling, packageId, currentOrgId, fetchStatus]);

  return { pipeline, loading, refetch: fetchStatus };
}
