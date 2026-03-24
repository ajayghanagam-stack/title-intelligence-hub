"use client";

import Link from "next/link";
import { FileSearch, Upload, Plus } from "lucide-react";
import { PackList } from "@/components/title-intelligence/pack-list";
import { usePacks } from "@/hooks/use-packs";

export default function TitleIntelligencePage() {
  const { packs, loading } = usePacks();

  return (
    <div className="space-y-8">
      {/* Hero header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 ring-1 ring-amber-500/10">
            <FileSearch className="h-6 w-6 text-amber-700" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Title Intelligence</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              AI-powered title commitment analysis
            </p>
          </div>
        </div>
        <Link
          href="/apps/title-intelligence/packs/new"
          className="btn-cta gap-2"
        >
          <Plus className="h-4 w-4" />
          New Pack
        </Link>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading packs...</p>
        </div>
      ) : (
        <PackList packs={packs} />
      )}
    </div>
  );
}
