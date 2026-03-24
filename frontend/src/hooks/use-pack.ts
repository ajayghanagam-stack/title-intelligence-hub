"use client";

import { useState, useEffect, useCallback } from "react";
import { useOrg } from "./use-org";
import type { Pack } from "@/lib/ti-types";

export function usePack(packId: string) {
  const { orgFetch } = useOrg();
  const [pack, setPack] = useState<Pack | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchPack = useCallback(async () => {
    try {
      const data = await orgFetch<Pack>(
        `/api/v1/apps/title-intelligence/packs/${packId}`
      );
      setPack(data);
    } catch {
      setPack(null);
    } finally {
      setLoading(false);
    }
  }, [orgFetch, packId]);

  useEffect(() => {
    fetchPack();
  }, [fetchPack]);

  return { pack, loading, refetch: fetchPack };
}
