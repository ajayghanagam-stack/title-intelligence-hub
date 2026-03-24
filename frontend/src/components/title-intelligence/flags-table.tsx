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

const STATUS_STYLES: Record<string, string> = {
  open: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
  approved: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  rejected: "bg-red-50 text-red-700 ring-1 ring-red-200",
  escalated: "bg-purple-50 text-purple-700 ring-1 ring-purple-200",
};

const severityOrder: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

interface FlagRowProps {
  flag: Flag;
  packId: string;
  isExpanded: boolean;
  isLoading: boolean;
  onToggle: (id: string) => void;
  onQuickAction: (flagId: string, decision: ReviewDecision) => void;
  onOpenDetail: (flag: Flag) => void;
}

const FlagRow = memo(function FlagRow({
  flag,
  packId,
  isExpanded,
  isLoading,
  onToggle,
  onQuickAction,
  onOpenDetail,
}: FlagRowProps) {
  return (
    <div className={cn(
      "rounded-xl border transition-all",
      isExpanded ? "ring-1 ring-primary/10 shadow-sm" : "hover:border-border/80"
    )}>
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-muted/20 transition-colors rounded-xl"
        onClick={() => onToggle(flag.id)}
      >
        <div className="shrink-0 text-muted-foreground/50">
          {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>
        <div className="shrink-0">
          <SeverityBadge severity={flag.severity} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{flag.title}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {CATEGORY_LABELS[flag.flag_type] || flag.flag_type.replace(/_/g, " ")}
          </p>
        </div>
        <span className={cn(
          "shrink-0 inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium capitalize",
          STATUS_STYLES[flag.status] || ""
        )}>
          {flag.status}
        </span>
        {flag.ai_explanation && <Sparkles className="h-3.5 w-3.5 text-amber-500 shrink-0" />}
        {flag.status === "open" && (
          <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => onQuickAction(flag.id, "approve")} disabled={isLoading} className="rounded-lg p-1.5 text-emerald-600 hover:bg-emerald-50 transition-colors disabled:opacity-40" title="Approve"><CheckCircle className="h-4 w-4" /></button>
            <button onClick={() => onQuickAction(flag.id, "reject")} disabled={isLoading} className="rounded-lg p-1.5 text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40" title="Reject"><XCircle className="h-4 w-4" /></button>
            <button onClick={() => onQuickAction(flag.id, "escalate")} disabled={isLoading} className="rounded-lg p-1.5 text-amber-600 hover:bg-amber-50 transition-colors disabled:opacity-40" title="Escalate"><AlertTriangle className="h-4 w-4" /></button>
          </div>
        )}
      </div>
      {isExpanded && (
        <div className="border-t px-5 py-4 space-y-4 bg-muted/5">
          <p className="text-sm text-muted-foreground leading-relaxed">{flag.description}</p>
          {flag.ai_explanation && (
            <div className="rounded-xl bg-amber-50/60 border border-amber-200/40 px-4 py-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-700 mb-1.5"><Sparkles className="h-3.5 w-3.5" />AI Recommendation</p>
              <p className="text-sm leading-relaxed text-amber-900/80">{flag.ai_explanation}</p>
            </div>
          )}
          {flag.evidence_refs.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Evidence ({flag.evidence_refs.length})</p>
              <div className="space-y-1.5">
                {flag.evidence_refs.map((ref, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <span className="shrink-0 inline-flex items-center gap-1 text-xs text-primary font-medium bg-primary/5 px-2 py-0.5 rounded"><FileText className="h-3 w-3" />Page {ref.page_number}</span>
                    {ref.text_snippet && <p className="text-xs text-muted-foreground italic border-l-2 border-amber-300/60 pl-2 line-clamp-2">&ldquo;{ref.text_snippet}&rdquo;</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
          <button onClick={() => onOpenDetail(flag)} className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-semibold transition-colors">Open full detail<ArrowUpRight className="h-3 w-3" /></button>
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
      <div className="flex flex-col items-center py-10 text-center">
        <CheckCircle className="h-10 w-10 text-emerald-400 mb-3" />
        <p className="text-sm font-medium text-foreground/80">No risk flags identified</p>
        <p className="text-xs text-muted-foreground mt-1">This document appears to be clean</p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-2">
        {pageItems.map((flag) => (
          <FlagRow
            key={flag.id}
            flag={flag}
            packId={packId}
            isExpanded={expandedRows.has(flag.id)}
            isLoading={actionLoading === flag.id || !!submitting}
            onToggle={toggleRow}
            onQuickAction={handleQuickAction}
            onOpenDetail={handleOpenDetail}
          />
        ))}
      </div>
      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalItems={sorted.length}
        pageSize={PAGE_SIZE}
        onPageChange={handlePageChange}
      />
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
