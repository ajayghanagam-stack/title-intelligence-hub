"use client";

import { useState, memo, useCallback } from "react";
import { useRouter } from "next/navigation";
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
import { FlagNoteInput } from "./flag-note-input";
import { Pagination } from "./pagination";
import { SEVERITY_DISPLAY_NAMES } from "@/lib/ti-constants";
import type { Flag, ReviewDecision } from "@/lib/ti-types";

const CATEGORY_LABELS: Record<string, string> = {
  missing_endorsement: "Missing Endorsement",
  unacceptable_exception: "Unacceptable Exception",
  unresolved_lien: "Unresolved Lien",
  unreleased_mortgage: "Unreleased Mortgage",
  cross_section_mismatch: "Cross-Section Mismatch",
  requirement_missing_proof: "Requirement Missing Proof",
  name_discrepancy: "Name Discrepancy",
  marital_status_issue: "Marital Status Issue",
  incomplete_document: "Incomplete Document",
  regulatory_compliance: "Regulatory Compliance",
  chain_of_title_gap: "Chain of Title Gap",
  document_defect: "Document Defect",
  mineral_rights: "Mineral Rights",
  trust_issue: "Trust Issue",
  estate_issue: "Estate Issue",
  vesting_issue: "Vesting Issue",
  tax_issue: "Tax Issue",
};

function getCategoryLabel(flagType: string): string {
  return CATEGORY_LABELS[flagType] || flagType.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getDocumentRef(flag: Flag): string {
  if (!flag.evidence_refs || flag.evidence_refs.length === 0) return "";
  const pages = [...new Set(flag.evidence_refs.map((r) => r.page_number))].sort((a, b) => a - b);
  return "p. " + pages.join(", ");
}

interface FlagCardProps {
  flag: Flag;
  itemNumber: string;
  packId: string;
  isExpanded: boolean;
  isLoading: boolean;
  onToggle: (id: string) => void;
  onQuickAction: (flagId: string, decision: ReviewDecision) => void;
  onOpenDetail: (flag: Flag) => void;
  onNavigateToPage: (pageNumber: number, textSnippet?: string) => void;
  onSaveNote: (flagId: string, note: string | null) => Promise<void>;
}

const FlagCard = memo(function FlagCard({
  flag,
  itemNumber,
  isExpanded,
  isLoading,
  onToggle,
  onQuickAction,
  onOpenDetail,
  onNavigateToPage,
  onSaveNote,
}: FlagCardProps) {
  const docRef = getDocumentRef(flag);
  const category = getCategoryLabel(flag.flag_type);
  const sevDisplay = SEVERITY_DISPLAY_NAMES[flag.severity] || flag.severity.toUpperCase();

  return (
    <div className={cn(
      "border-b border-border/40 transition-colors",
      isExpanded ? "bg-muted/20" : "hover:bg-muted/10"
    )}>
      {/* Card header — matches PDF exception item layout */}
      <div
        className="flex items-start gap-3 px-5 py-3.5 cursor-pointer"
        onClick={() => onToggle(flag.id)}
      >
        {/* Expand chevron */}
        <div className="shrink-0 mt-0.5 text-muted-foreground/40">
          {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>

        {/* Item number */}
        <span className="shrink-0 text-sm font-bold text-brand-charcoal mt-0.5">{itemNumber}</span>

        {/* Severity badge */}
        <div className="shrink-0 mt-0.5">
          <SeverityBadge severity={flag.severity} />
        </div>

        {/* Title + description */}
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-bold text-brand-charcoal leading-snug">{flag.title}</p>
          <p className="text-[12px] text-muted-foreground mt-1 line-clamp-2 leading-relaxed">{flag.description}</p>
          {/* Mobile: show category + doc ref */}
          <div className="flex items-center gap-2 mt-1.5 lg:hidden">
            <span className="text-[11px] text-muted-foreground">{category}</span>
            {docRef && <span className="text-[11px] text-primary font-medium">{docRef}</span>}
          </div>
        </div>

        {/* Doc Ref — desktop */}
        <div className="shrink-0 w-[80px] hidden lg:block mt-0.5">
          {flag.evidence_refs.length > 0 ? (
            <button
              onClick={(e) => { e.stopPropagation(); onNavigateToPage(flag.evidence_refs[0].page_number, flag.evidence_refs[0].text_snippet); }}
              className="text-[11px] text-primary hover:text-primary/80 hover:underline font-medium transition-colors"
            >
              {docRef}
            </button>
          ) : (
            <span className="text-[11px] text-muted-foreground">&mdash;</span>
          )}
        </div>

        {/* Note — desktop */}
        <div className="shrink-0 w-[180px] hidden lg:block" onClick={(e) => e.stopPropagation()}>
          <FlagNoteInput flagId={flag.id} initialNote={flag.note} onSave={onSaveNote} />
        </div>
      </div>

      {/* Expanded detail */}
      {isExpanded && (
        <div className="pl-14 pr-5 pb-4 space-y-3">
          {/* Category label */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">{category}</span>
            {flag.status !== "open" && (
              <span className={cn(
                "text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider",
                flag.status === "approved" ? "bg-emerald-100 text-emerald-700" :
                flag.status === "rejected" ? "bg-red-100 text-red-700" :
                "bg-purple-100 text-purple-700"
              )}>
                {flag.status}
              </span>
            )}
          </div>

          {/* Full description */}
          <p className="text-[13px] text-muted-foreground leading-relaxed">{flag.description}</p>

          {/* AI Recommendation — styled like PDF warning */}
          {flag.ai_explanation && (
            <div className="rounded-lg bg-amber-50/70 border border-amber-200/50 px-4 py-3">
              <p className="flex items-center gap-1.5 text-[11px] font-bold text-amber-800 mb-1 uppercase tracking-wider">
                <Sparkles className="h-3 w-3" />Examiner&apos;s Note
              </p>
              <p className="text-[13px] leading-relaxed text-amber-900/80">{flag.ai_explanation}</p>
            </div>
          )}

          {/* Evidence */}
          {flag.evidence_refs.length > 0 && (
            <div>
              <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider mb-1.5">
                Evidence ({flag.evidence_refs.length})
              </p>
              <div className="space-y-1">
                {flag.evidence_refs.map((ref, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <button
                      onClick={(e) => { e.stopPropagation(); onNavigateToPage(ref.page_number, ref.text_snippet); }}
                      className="shrink-0 inline-flex items-center gap-1 text-[11px] text-primary font-medium bg-primary/5 hover:bg-primary/10 px-2 py-0.5 rounded cursor-pointer transition-colors"
                    >
                      <FileText className="h-3 w-3" />Page {ref.page_number}
                    </button>
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

          {/* Actions */}
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

          {/* Mobile note input */}
          <div className="lg:hidden" onClick={(e) => e.stopPropagation()}>
            <FlagNoteInput flagId={flag.id} initialNote={flag.note} onSave={onSaveNote} />
          </div>
        </div>
      )}
    </div>
  );
});

export const PAGE_SIZE = 10;

export function FlagsTable({
  flags,
  packId,
  onReview,
  onSaveNote,
  submitting,
  total,
  currentPage: serverPage,
  onPageChange: onServerPageChange,
}: {
  flags: Flag[];
  packId: string;
  onReview: (flagId: string, decision: ReviewDecision, reasonCode: string | null, notes: string) => void;
  onSaveNote: (flagId: string, note: string | null) => Promise<void>;
  submitting?: boolean;
  total?: number;
  currentPage?: number;
  onPageChange?: (page: number) => void;
}) {
  const router = useRouter();
  const [selectedFlag, setSelectedFlag] = useState<Flag | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const isServerPaginated = total !== undefined && serverPage !== undefined && onServerPageChange !== undefined;
  const currentPage = isServerPaginated ? serverPage : 1;
  const pageItems = flags;
  const effectiveTotal = isServerPaginated ? total : flags.length;
  const totalPages = Math.max(1, Math.ceil(effectiveTotal / PAGE_SIZE));

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

  const handleNavigateToPage = useCallback(
    (pageNumber: number, _textSnippet?: string) => {
      const params = new URLSearchParams({ page: String(pageNumber) });
      router.push(`/apps/title-intelligence/packs/${packId}/documents?${params.toString()}`);
    },
    [router, packId]
  );

  const handlePageChange = (page: number) => {
    if (isServerPaginated) {
      onServerPageChange(page);
    }
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
      {/* Card rows */}
      <div>
        {pageItems.map((flag, idx) => {
          const globalIdx = (currentPage - 1) * PAGE_SIZE + idx;
          const itemNumber = `EX-${String(globalIdx + 1).padStart(3, "0")}`;
          return (
            <FlagCard
              key={flag.id}
              flag={flag}
              itemNumber={itemNumber}
              packId={packId}
              isExpanded={expandedRows.has(flag.id)}
              isLoading={actionLoading === flag.id || !!submitting}
              onToggle={toggleRow}
              onQuickAction={handleQuickAction}
              onOpenDetail={handleOpenDetail}
              onNavigateToPage={handleNavigateToPage}
              onSaveNote={onSaveNote}
            />
          );
        })}
      </div>

      {/* Pagination */}
      <div className="px-4 py-3 border-t">
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          totalItems={effectiveTotal}
          pageSize={PAGE_SIZE}
          onPageChange={handlePageChange}
        />
      </div>

      {selectedFlag && (
        <FlagDetailDialog
          flag={selectedFlag}
          onReview={(decision, reasonCode, notes) => { onReview(selectedFlag.id, decision, reasonCode, notes); setSelectedFlag(null); }}
          onSaveNote={onSaveNote}
          onClose={() => setSelectedFlag(null)}
          submitting={submitting}
        />
      )}
    </>
  );
}
