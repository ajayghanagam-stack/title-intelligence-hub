"use client";

import { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Circle,
  ChevronDown,
  ChevronRight,
  Sparkles,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";
import { useOrg } from "@/hooks/use-org";
import { SeverityBadge } from "./severity-badge";
import { Pagination, usePagination } from "./pagination";
import { CATEGORY_LABELS } from "@/lib/ti-constants";
import type { ChecklistItem } from "@/lib/ti-types";

interface ClosingChecklistProps {
  items: ChecklistItem[];
  packId?: string;
  onAction?: () => void;
}

const PAGE_SIZE = 10;

export function ClosingChecklist({ items, packId, onAction }: ClosingChecklistProps) {
  const { orgFetch } = useOrg();
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const { paginate, totalPages } = usePagination(items, PAGE_SIZE);

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center py-10 text-center">
        <CheckCircle2 className="h-10 w-10 text-emerald-400 mb-3" />
        <p className="text-sm font-medium text-foreground/80">No checklist items</p>
      </div>
    );
  }

  const resolved = items.filter((i) => i.status === "done").length;
  const pageItems = paginate(currentPage);

  // Calculate the global index offset for the current page
  const indexOffset = (currentPage - 1) * PAGE_SIZE;

  const toggleItem = (index: number) => {
    setExpandedItems((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index); else next.add(index);
      return next;
    });
  };

  const handleAction = async (flagId: string, decision: string, index: number) => {
    if (!packId) return;
    setActionLoading(index);
    try {
      await orgFetch(
        `/api/v1/apps/title-intelligence/packs/${packId}/flags/${flagId}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            reason_code: decision === "approve" ? "standard_exception" : decision === "reject" ? "confirmed_risk" : "requires_legal_review",
            notes: "",
          }),
        }
      );
      onAction?.();
    } catch { /* ignore */ }
    setActionLoading(null);
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    setExpandedItems(new Set());
  };

  const isResolved = (status: ChecklistItem["status"]) => status === "done";
  const isCritical = (status: ChecklistItem["status"]) => status === "blocked";

  return (
    <div className="space-y-4">
      {/* Progress */}
      <div className="flex items-center gap-3">
        <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${items.length > 0 ? (resolved / items.length) * 100 : 0}%` }}
          />
        </div>
        <span className="text-sm font-medium text-muted-foreground whitespace-nowrap">
          {resolved} of {items.length} cleared
        </span>
      </div>

      {/* Items for current page */}
      <div className="space-y-1.5">
        {pageItems.map((item, i) => {
          const globalIndex = indexOffset + i;
          const expanded = expandedItems.has(globalIndex);
          const isLoading = actionLoading === globalIndex;
          const itemResolved = isResolved(item.status);
          const itemCritical = isCritical(item.status);
          const flagId = (item as ChecklistItem & { flag_id?: string }).flag_id;
          const aiExplanation = (item as ChecklistItem & { ai_explanation?: string }).ai_explanation;
          const detail = (item as ChecklistItem & { detail?: string }).detail;
          const evidencePage = (item as ChecklistItem & { evidence_page?: number }).evidence_page;
          const hasExpandableContent = !itemResolved && (aiExplanation || detail || flagId);

          return (
            <div
              key={globalIndex}
              className={`rounded-xl border overflow-hidden ${
                itemResolved
                  ? "bg-emerald-50/50 border-emerald-200/50"
                  : itemCritical
                    ? "bg-red-50/50 border-red-200/50"
                    : "bg-card border-border"
              }`}
            >
              <div
                className={`flex items-center gap-2.5 px-4 py-3 text-sm ${hasExpandableContent ? "cursor-pointer hover:bg-muted/20" : ""}`}
                onClick={() => hasExpandableContent && toggleItem(globalIndex)}
              >
                {hasExpandableContent ? (
                  <div className="shrink-0">{expanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}</div>
                ) : (
                  <div className="w-3.5 shrink-0" />
                )}
                <div className="shrink-0">
                  {itemResolved ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : itemCritical ? <XCircle className="h-4 w-4 text-red-500" /> : <Circle className="h-4 w-4 text-muted-foreground/40" />}
                </div>
                <p className={`flex-1 min-w-0 text-sm truncate ${itemResolved ? "line-through text-muted-foreground" : "text-foreground"}`}>
                  {item.label}
                </p>
                {aiExplanation && !itemResolved && <Sparkles className="h-3.5 w-3.5 text-amber-500 shrink-0" />}
                {evidencePage && packId && (
                  <a href={`/apps/title-intelligence/packs/${packId}/documents?page=${evidencePage}`} onClick={(e) => e.stopPropagation()} className="shrink-0 text-xs text-primary hover:underline whitespace-nowrap">p.{evidencePage}</a>
                )}
                {item.severity && !itemResolved && <span className="shrink-0"><SeverityBadge severity={item.severity} /></span>}
                {flagId && !itemResolved && packId && (
                  <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => handleAction(flagId, "approve", globalIndex)} disabled={isLoading} className="rounded-lg p-1.5 text-emerald-600 hover:bg-emerald-50 transition-colors disabled:opacity-40" title="Approve"><CheckCircle className="h-3.5 w-3.5" /></button>
                    <button onClick={() => handleAction(flagId, "reject", globalIndex)} disabled={isLoading} className="rounded-lg p-1.5 text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40" title="Reject"><XCircle className="h-3.5 w-3.5" /></button>
                    <button onClick={() => handleAction(flagId, "escalate", globalIndex)} disabled={isLoading} className="rounded-lg p-1.5 text-amber-600 hover:bg-amber-50 transition-colors disabled:opacity-40" title="Escalate"><AlertTriangle className="h-3.5 w-3.5" /></button>
                  </div>
                )}
              </div>
              {expanded && hasExpandableContent && (
                <div className="border-t px-5 py-3 space-y-2 bg-muted/5">
                  {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
                  {aiExplanation && (
                    <div className="rounded-xl bg-amber-50/60 border border-amber-200/40 px-3 py-2">
                      <p className="flex items-center gap-1.5 text-xs font-medium text-amber-700 mb-0.5"><Sparkles className="h-3 w-3" />AI Recommendation</p>
                      <p className="text-xs leading-relaxed text-amber-900">{aiExplanation}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalItems={items.length}
        pageSize={PAGE_SIZE}
        onPageChange={handlePageChange}
      />
    </div>
  );
}
