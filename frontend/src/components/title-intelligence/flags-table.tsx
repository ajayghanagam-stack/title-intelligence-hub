"use client";

import { useState, memo, useCallback } from "react";
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Sparkles,
  FileText,
  ArrowUpRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SeverityBadge } from "./severity-badge";
import { FlagDetailDialog } from "./flag-detail-dialog";
import { Pagination, usePagination } from "./pagination";
import type { Flag, ReviewDecision } from "@/lib/ti-types";

const CATEGORY_LABELS: Record<string, string> = {
  missing_endorsement: "Missing Endorsement",
  unacceptable_exception: "Unacceptable Exception",
  unresolved_lien: "Unresolved Lien",
  cross_section_mismatch: "Cross-Section Mismatch",
  requirement_missing_proof: "Requirement Missing Proof",
};

const severityOrder: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

interface FlagRowProps {
  flag: Flag;
  exceptionId: string;
  packId: string;
  isExpanded: boolean;
  isLoading: boolean;
  onToggle: (id: string) => void;
  onQuickAction: (flagId: string, decision: ReviewDecision) => void;
  onOpenDetail: (flag: Flag) => void;
}

function getRequiredAction(flag: Flag): string {
  const text = flag.ai_explanation || flag.description || "";
  const match = text.match(/^[^.!?]+[.!?]/);
  return match ? match[0] : text.slice(0, 120);
}

function getDocumentRef(flag: Flag): string {
  if (!flag.evidence_refs || flag.evidence_refs.length === 0) return "\u2014";
  const first = flag.evidence_refs[0];
  let label = `Page ${first.page_number}`;
  if (flag.evidence_refs.length > 1) label += ` +${flag.evidence_refs.length - 1}`;
  return label;
}

function getCategoryLabel(flagType: string): string {
  return CATEGORY_LABELS[flagType] || flagType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const FlagRow = memo(function FlagRow({
  flag,
  exceptionId,
  isExpanded,
  isLoading,
  onToggle,
  onQuickAction,
  onOpenDetail,
}: FlagRowProps) {
  const docRef = getDocumentRef(flag);
  const requiredAction = getRequiredAction(flag);
  const category = getCategoryLabel(flag.flag_type);

  return (
    <div className={cn(
      "transition-colors",
      isExpanded ? "bg-muted/30" : "hover:bg-muted/15"
    )}>
      {/* Row */}
      <div
        className="flex items-start gap-0 cursor-pointer"
        onClick={() => onToggle(flag.id)}
      >
        {/* Chevron */}
        <div className="shrink-0 w-9 flex items-center justify-center pt-3.5 text-muted-foreground/40">
          {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </div>
        {/* ID */}
        <div className="shrink-0 w-[60px] pt-3 pb-3 pr-2">
          <span className="text-[12px] font-mono font-semibold text-muted-foreground">{exceptionId}</span>
        </div>
        {/* Severity */}
        <div className="shrink-0 w-[80px] pt-2.5 pb-3">
          <SeverityBadge severity={flag.severity} />
        </div>
        {/* Category — desktop only */}
        <div className="shrink-0 w-[110px] pt-3 pb-3 pr-2 hidden lg:block">
          <span className="text-[12px] font-medium text-muted-foreground">{category}</span>
        </div>
        {/* Description */}
        <div className="flex-1 min-w-0 pt-3 pb-3 pr-3">
          <p className="text-[13px] text-foreground leading-snug line-clamp-2">{flag.description || flag.title}</p>
          {/* Mobile: show category below description */}
          <p className="text-[11px] text-muted-foreground mt-0.5 lg:hidden">{category}</p>
        </div>
        {/* Doc Ref — desktop only */}
        <div className="shrink-0 w-[120px] pt-3 pb-3 pr-2 hidden lg:block">
          <span className="text-[12px] text-muted-foreground">{docRef}</span>
        </div>
        {/* Required Action — desktop only */}
        <div className="shrink-0 w-[180px] pt-3 pb-3 pr-4 hidden lg:block">
          <p className="text-[12px] text-muted-foreground leading-snug line-clamp-3">{requiredAction}</p>
        </div>
      </div>

      {/* Divider between rows */}
      <div className="border-b border-border/50" />

      {/* Expanded detail */}
      {isExpanded && (
        <div className="pl-9 pr-5 py-4 space-y-3 border-b border-border/50 bg-muted/10">
          <p className="text-[13px] text-muted-foreground leading-relaxed">{flag.description}</p>

          {flag.ai_explanation && (
            <div className="rounded-lg bg-amber-50/70 border border-amber-200/50 px-4 py-3">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-700 mb-1">
                <Sparkles className="h-3 w-3" />Recommendation
              </p>
              <p className="text-[13px] leading-relaxed text-amber-900/80">{flag.ai_explanation}</p>
            </div>
          )}

          {flag.evidence_refs.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                Evidence ({flag.evidence_refs.length})
              </p>
              <div className="space-y-1">
                {flag.evidence_refs.map((ref, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="shrink-0 inline-flex items-center gap-1 text-[11px] text-primary font-medium bg-primary/5 px-2 py-0.5 rounded">
                      <FileText className="h-3 w-3" />Page {ref.page_number}
                    </span>
                    {ref.text_snippet && (
                      <p className="text-[11px] text-muted-foreground italic border-l-2 border-amber-300/60 pl-2 line-clamp-2">
                        &ldquo;{ref.text_snippet}&rdquo;
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-2 pt-2">
            {flag.status === "open" && (
              <div className="flex items-center gap-1.5 mr-3" onClick={(e) => e.stopPropagation()}>
                <button onClick={() => onQuickAction(flag.id, "approve")} disabled={isLoading} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 ring-1 ring-emerald-200/60 transition-colors disabled:opacity-40"><CheckCircle className="h-3 w-3" />Approve</button>
                <button onClick={() => onQuickAction(flag.id, "reject")} disabled={isLoading} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium text-red-700 bg-red-50 hover:bg-red-100 ring-1 ring-red-200/60 transition-colors disabled:opacity-40"><XCircle className="h-3 w-3" />Reject</button>
                <button onClick={() => onQuickAction(flag.id, "escalate")} disabled={isLoading} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 ring-1 ring-amber-200/60 transition-colors disabled:opacity-40"><AlertTriangle className="h-3 w-3" />Escalate</button>
              </div>
            )}
            <button onClick={() => onOpenDetail(flag)} className="inline-flex items-center gap-1 text-[11px] text-primary hover:text-primary/80 font-semibold transition-colors">
              View full detail <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
});

const PAGE_SIZE = 10;

export function FlagsTable({
  flags,
  packId,
  onReview,
  onGetRecommendation,
  submitting,
}: {
  flags: Flag[];
  packId: string;
  onReview: (flagId: string, decision: ReviewDecision, reasonCode: string | null, notes: string) => void;
  onGetRecommendation: (flagId: string) => Promise<{ decision: string; reasoning: string; confidence: number }>;
  submitting?: boolean;
}) {
  const [selectedFlag, setSelectedFlag] = useState<Flag | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const sorted = [...flags].sort(
    (a, b) => (severityOrder[a.severity] ?? 4) - (severityOrder[b.severity] ?? 4)
  );

  const { paginate, totalPages } = usePagination(sorted, PAGE_SIZE);
  const pageItems = paginate(currentPage);

  const toggleRow = useCallback((id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleQuickAction = useCallback(
    async (flagId: string, decision: ReviewDecision) => {
      setActionLoading(flagId);
      const reasonCode = decision === "approve" ? "standard_exception" : decision === "reject" ? "confirmed_risk" : "requires_legal_review";
      onReview(flagId, decision, reasonCode, "");
      setActionLoading(null);
    },
    [onReview]
  );

  const handleOpenDetail = useCallback((flag: Flag) => setSelectedFlag(flag), []);

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    setExpandedRows(new Set());
  };

  if (flags.length === 0) {
    return (
      <div className="flex flex-col items-center py-14 text-center">
        <CheckCircle className="h-8 w-8 text-emerald-400 mb-2" />
        <p className="text-sm font-medium text-foreground/80">No flags identified for this filter</p>
        <p className="text-xs text-muted-foreground mt-0.5">Try a different filter or this document appears clean</p>
      </div>
    );
  }

  return (
    <>
      {/* Table header */}
      <div className="hidden lg:flex items-center gap-0 bg-muted/40 border-b text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        <div className="w-9" />
        <span className="w-[60px] py-2.5 pr-2">ID</span>
        <span className="w-[80px] py-2.5">Severity</span>
        <span className="w-[110px] py-2.5 pr-2">Category</span>
        <span className="flex-1 py-2.5 pr-3">Description</span>
        <span className="w-[120px] py-2.5 pr-2">Doc Ref</span>
        <span className="w-[180px] py-2.5 pr-4">Required Action</span>
      </div>

      {/* Rows */}
      <div>
        {pageItems.map((flag, idx) => {
          const globalIdx = (currentPage - 1) * PAGE_SIZE + idx;
          const exceptionId = `EX-${String(globalIdx + 1).padStart(3, "0")}`;
          return (
            <FlagRow
              key={flag.id}
              flag={flag}
              exceptionId={exceptionId}
              packId={packId}
              isExpanded={expandedRows.has(flag.id)}
              isLoading={actionLoading === flag.id || !!submitting}
              onToggle={toggleRow}
              onQuickAction={handleQuickAction}
              onOpenDetail={handleOpenDetail}
            />
          );
        })}
      </div>

      {/* Pagination */}
      <div className="px-4 py-3 border-t">
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          totalItems={sorted.length}
          pageSize={PAGE_SIZE}
          onPageChange={handlePageChange}
        />
      </div>

      {selectedFlag && (
        <FlagDetailDialog
          flag={selectedFlag}
          onReview={(decision, reasonCode, notes) => { onReview(selectedFlag.id, decision, reasonCode, notes); setSelectedFlag(null); }}
          onGetRecommendation={() => onGetRecommendation(selectedFlag.id)}
          onClose={() => setSelectedFlag(null)}
          submitting={submitting}
        />
      )}
    </>
  );
}
