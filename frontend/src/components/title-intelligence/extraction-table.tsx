"use client";

import { useState, memo, useCallback } from "react";
import { ChevronDown, ChevronRight, FileText, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { Pagination, usePagination } from "./pagination";
import type { Extraction } from "@/lib/ti-types";

const TYPE_LABELS: Record<string, string> = {
  party: "Parties",
  property_info: "Property Info",
  requirement: "Requirements",
  exception: "Exceptions",
  endorsement: "Endorsements",
  legal_description: "Legal Description",
};

const TYPE_ORDER = [
  "party", "property_info", "requirement", "exception", "endorsement", "legal_description",
];

const TYPE_COLORS: Record<string, { pill: string; pillActive: string; border: string; bg: string }> = {
  party: { pill: "bg-purple-50 text-purple-700 ring-purple-200", pillActive: "bg-purple-600 text-white ring-purple-600", border: "border-l-purple-400", bg: "bg-purple-50/30" },
  property_info: { pill: "bg-sky-50 text-sky-700 ring-sky-200", pillActive: "bg-sky-600 text-white ring-sky-600", border: "border-l-sky-400", bg: "bg-sky-50/30" },
  requirement: { pill: "bg-amber-50 text-amber-700 ring-amber-200", pillActive: "bg-amber-600 text-white ring-amber-600", border: "border-l-amber-400", bg: "bg-amber-50/30" },
  exception: { pill: "bg-red-50 text-red-700 ring-red-200", pillActive: "bg-red-600 text-white ring-red-600", border: "border-l-red-400", bg: "bg-red-50/30" },
  endorsement: { pill: "bg-emerald-50 text-emerald-700 ring-emerald-200", pillActive: "bg-emerald-600 text-white ring-emerald-600", border: "border-l-emerald-400", bg: "bg-emerald-50/30" },
  legal_description: { pill: "bg-stone-50 text-stone-700 ring-stone-200", pillActive: "bg-stone-600 text-white ring-stone-600", border: "border-l-stone-400", bg: "bg-stone-50/30" },
};

function summarizeValue(value: Record<string, unknown>): string {
  const entries = Object.entries(value);
  const parts: string[] = [];
  for (const [k, v] of entries) {
    if (v === null || v === undefined || v === "") continue;
    const str = String(v);
    parts.push(str.length > 60 ? `${k}: ${str.slice(0, 57)}...` : `${k}: ${str}`);
    if (parts.join(" | ").length > 120) break;
  }
  return parts.join(" | ");
}

const ExtractionRow = memo(function ExtractionRow({
  ext,
  isExpanded,
  borderColor,
  onToggle,
}: {
  ext: Extraction;
  isExpanded: boolean;
  borderColor: string;
  onToggle: (id: string) => void;
}) {
  const value = ext.value as Record<string, unknown>;
  return (
    <div
      className={cn("border-l-2 cursor-pointer transition-all", borderColor, isExpanded ? "bg-muted/20" : "hover:bg-muted/10")}
      onClick={() => onToggle(ext.id)}
    >
      <div className="flex items-start gap-3 px-4 py-2.5">
        <div className="shrink-0 mt-0.5 text-muted-foreground/40">
          {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-foreground">{ext.label}</p>
          {isExpanded ? (
            <div className="mt-2 space-y-1">
              {Object.entries(value).map(([k, v]) => {
                if (v === null || v === undefined || v === "") return null;
                return (
                  <div key={k} className="text-xs">
                    <span className="font-medium text-foreground/80">{k}:</span>{" "}
                    <span className="text-muted-foreground">{String(v)}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">{summarizeValue(value)}</p>
          )}
        </div>
        {ext.evidence_refs.length > 0 && (
          <span className="shrink-0 inline-flex items-center gap-1 text-[10px] text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
            <FileText className="h-2.5 w-2.5" />p.{ext.evidence_refs.map((e) => e.page_number).join(",")}
          </span>
        )}
      </div>
    </div>
  );
});

const PAGE_SIZE = 10;

export function ExtractionTable({ extractions }: { extractions: Extraction[] }) {
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = useState(1);

  const toggleRow = useCallback((id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Group by type (needed for both empty check and rendering)
  const grouped: Record<string, Extraction[]> = {};
  for (const ext of extractions) {
    const key = ext.extraction_type;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(ext);
  }

  const sortedTypes = TYPE_ORDER.filter((t) => grouped[t]);
  for (const key of Object.keys(grouped)) {
    if (!sortedTypes.includes(key)) sortedTypes.push(key);
  }

  const filteredItems = activeFilter
    ? grouped[activeFilter] || []
    : extractions;

  const { paginate, totalPages } = usePagination(filteredItems, PAGE_SIZE);

  if (extractions.length === 0) {
    return (
      <div className="flex flex-col items-center py-10 text-center">
        <Layers className="h-10 w-10 text-muted-foreground/30 mb-3" />
        <p className="text-sm font-medium text-foreground/80">No extractions yet</p>
        <p className="text-xs text-muted-foreground mt-1">Process the pack to extract document data</p>
      </div>
    );
  }

  const pageItems = paginate(currentPage);

  // Group page items by type for display
  const pageGrouped: Record<string, Extraction[]> = {};
  for (const ext of pageItems) {
    const key = ext.extraction_type;
    if (!pageGrouped[key]) pageGrouped[key] = [];
    pageGrouped[key].push(ext);
  }

  const displayTypes = TYPE_ORDER.filter((t) => pageGrouped[t]);
  for (const key of Object.keys(pageGrouped)) {
    if (!displayTypes.includes(key)) displayTypes.push(key);
  }

  const handleFilterChange = (type: string | null) => {
    setActiveFilter(type);
    setCurrentPage(1);
    setExpandedRows(new Set());
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
    setExpandedRows(new Set());
  };

  return (
    <div className="space-y-4">
      {/* Filter pills */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => handleFilterChange(null)}
          className={cn(
            "px-3 py-1.5 rounded-full text-xs font-medium ring-1 transition-all",
            activeFilter === null
              ? "bg-foreground text-background ring-foreground"
              : "bg-transparent text-muted-foreground ring-border hover:ring-foreground/30"
          )}
        >
          All ({extractions.length})
        </button>
        {sortedTypes.map((type) => {
          const colors = TYPE_COLORS[type] || { pill: "bg-stone-50 text-stone-700 ring-stone-200", pillActive: "bg-stone-600 text-white ring-stone-600" };
          const isActive = activeFilter === type;
          return (
            <button
              key={type}
              onClick={() => handleFilterChange(isActive ? null : type)}
              className={cn("px-3 py-1.5 rounded-full text-xs font-medium ring-1 transition-all", isActive ? colors.pillActive : colors.pill)}
            >
              {TYPE_LABELS[type] || type.replace(/_/g, " ")} ({grouped[type].length})
            </button>
          );
        })}
      </div>

      {/* Grouped items for current page */}
      <div className="space-y-3">
        {displayTypes.map((type) => {
          const items = pageGrouped[type];
          const colors = TYPE_COLORS[type] || { pill: "bg-stone-50 text-stone-700 ring-stone-200", border: "border-l-stone-400", bg: "bg-stone-50/30" };

          return (
            <div key={type} className="rounded-xl border overflow-hidden">
              <div className={cn("flex items-center gap-3 px-4 py-2.5", colors.bg)}>
                <span className={cn("inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ring-1", colors.pill)}>
                  {TYPE_LABELS[type] || type.replace(/_/g, " ")}
                </span>
                <span className="text-xs text-muted-foreground">
                  {items.length} item{items.length !== 1 ? "s" : ""} on this page
                </span>
              </div>
              <div className="border-t divide-y divide-border/50">
                {items.map((ext) => (
                  <ExtractionRow
                    key={ext.id}
                    ext={ext}
                    isExpanded={expandedRows.has(ext.id)}
                    borderColor={colors.border}
                    onToggle={toggleRow}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <Pagination
        currentPage={currentPage}
        totalPages={totalPages}
        totalItems={filteredItems.length}
        pageSize={PAGE_SIZE}
        onPageChange={handlePageChange}
      />
    </div>
  );
}
