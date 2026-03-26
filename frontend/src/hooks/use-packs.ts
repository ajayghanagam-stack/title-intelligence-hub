"use client";

import { useState, useEffect, useCallback } from "react";
import { useOrg } from "./use-org";
import type { Pack } from "@/lib/ti-types";

export function usePacks() {
  const { orgFetch } = useOrg();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPacks = useCallback(async () => {
    try {
      setLoading(true);
      const data = await orgFetch<Pack[]>("/api/v1/apps/title-intelligence/packs");
      setPacks(data);
    } catch {
      setPacks([]);
    } finally {
      setLoading(false);
    }
  }, [orgFetch]);

  useEffect(() => {
    fetchPacks();
  }, [fetchPacks]);

  useEffect(() => {
    const handler = () => fetchPacks();
    window.addEventListener("pack-deleted", handler);
    return () => window.removeEventListener("pack-deleted", handler);
  }, [fetchPacks]);

  const deletePack = useCallback(async (packId: string) => {
    await orgFetch(`/api/v1/apps/title-intelligence/packs/${packId}`, {
      method: "DELETE",
    });
    await fetchPacks();
    window.dispatchEvent(new CustomEvent("pack-deleted"));
  }, [orgFetch, fetchPacks]);

  return { packs, loading, refetch: fetchPacks, deletePack };
}
