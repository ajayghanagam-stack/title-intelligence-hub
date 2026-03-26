"use client";

import { useState } from "react";
import Link from "next/link";
import { PackStatusBadge } from "./pack-status-badge";
import { Upload, ChevronRight, Shield, Calendar, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Pack } from "@/lib/ti-types";

function ScorePill({ score }: { score: number }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums",
        score >= 90
          ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
          : score >= 60
            ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
            : "bg-red-50 text-red-700 ring-1 ring-red-200"
      )}
    >
      <Shield className="h-3 w-3" />
      {score}
    </span>
  );
}

export function PackList({ packs, onDelete }: { packs: Pack[]; onDelete?: (id: string) => Promise<void> }) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(packId: string) {
    if (!onDelete) return;
    setDeleting(true);
    try {
      await onDelete(packId);
    } finally {
      setDeleting(false);
      setConfirmDeleteId(null);
    }
  }

  if (packs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
          <Upload className="h-7 w-7 text-muted-foreground/60" />
        </div>
        <p className="text-lg font-medium text-foreground/80 mb-1">No packs yet</p>
        <p className="text-sm text-muted-foreground mb-6">Upload your first title document to get started</p>
        <Link
          href="/apps/title-intelligence/packs/new"
          className="btn-cta gap-2"
        >
          <Upload className="h-4 w-4" />
          Upload New Pack
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {packs.map((pack) => (
        <Link
          key={pack.id}
          href={`/apps/title-intelligence/packs/${pack.id}`}
          className="group flex items-center gap-4 card-warm px-5 py-4 hover:border-primary/20"
        >
          {/* Score indicator */}
          <div className="shrink-0">
            {pack.readiness_score !== null ? (
              <div
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded-xl text-sm font-bold tabular-nums",
                  pack.readiness_score >= 90
                    ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                    : pack.readiness_score >= 60
                      ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
                      : "bg-red-50 text-red-700 ring-1 ring-red-200"
                )}
              >
                {pack.readiness_score}
              </div>
            ) : (
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-muted/60 text-muted-foreground/40">
                <Shield className="h-5 w-5" />
              </div>
            )}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-foreground group-hover:text-primary transition-colors truncate">
              {pack.name}
            </p>
            <div className="flex items-center gap-3 mt-1">
              <PackStatusBadge status={pack.status} stage={pack.current_stage} />
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Calendar className="h-3 w-3" />
                {new Date(pack.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>

          {/* Delete */}
          {onDelete && (
            <div className="shrink-0" onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
              {confirmDeleteId === pack.id ? (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleDelete(pack.id); }}
                    disabled={deleting}
                    className="h-7 px-2 text-xs font-medium rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                  >
                    {deleting ? "Deleting..." : "Confirm"}
                  </button>
                  <button
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirmDeleteId(null); }}
                    className="h-7 px-2 text-xs font-medium rounded-md text-muted-foreground hover:bg-muted transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); setConfirmDeleteId(pack.id); }}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground/50 hover:text-red-600 hover:bg-red-50 transition-colors"
                  title="Delete pack"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          )}

          {/* Arrow */}
          <ChevronRight className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/60 transition-colors shrink-0" />
        </Link>
      ))}
    </div>
  );
}
