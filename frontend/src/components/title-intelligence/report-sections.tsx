"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { SEVERITY_COLORS, PRIORITY_COLORS, SEVERITY_DISPLAY_NAMES } from "@/lib/ti-constants";
import type {
  ReportData,
  ReportException,
  ReportRequirement,
  ReportWarning,
  ReportChecklistItem,
} from "@/lib/ti-types";

const SECTION_PAGE_SIZE = 10;

/* ── Pagination controls ── */
function PaginationControls({
  total,
  page,
  onPageChange,
}: {
  total: number;
  page: number;
  onPageChange: (p: number) => void;
}) {
  const totalPages = Math.ceil(total / SECTION_PAGE_SIZE);
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-between px-5 py-2.5 border-t bg-muted/10">
      <span className="text-[12px] text-muted-foreground">
        Showing {(page - 1) * SECTION_PAGE_SIZE + 1}–{Math.min(page * SECTION_PAGE_SIZE, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="px-2.5 py-1 text-[12px] rounded border bg-background text-muted-foreground hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Prev
        </button>
        {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            className={cn(
              "px-2.5 py-1 text-[12px] rounded border",
              p === page
                ? "bg-amber-100 text-amber-800 border-amber-300"
                : "bg-background text-muted-foreground hover:bg-muted"
            )}
          >
            {p}
          </button>
        ))}
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="px-2.5 py-1 text-[12px] rounded border bg-background text-muted-foreground hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Next
        </button>
      </div>
    </div>
  );
}

/* ── Collapsible section header bar ── */
function SectionHeader({
  title,
  subtitle,
  count,
  collapsed,
  onToggle,
}: {
  title: string;
  subtitle?: string;
  count?: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full bg-amber-50 border-b border-amber-200 px-5 py-3 flex items-center justify-between cursor-pointer text-left hover:bg-amber-100/60 transition-colors"
    >
      <div>
        <h2 className="text-base font-bold tracking-tight text-amber-900">
          {title}
          {count !== undefined && (
            <span className="ml-2 text-[13px] font-normal text-amber-700/60">({count})</span>
          )}
        </h2>
        {subtitle && <p className="text-[13px] text-amber-700/70 mt-0.5">{subtitle}</p>}
      </div>
      <ChevronDown
        className={cn(
          "h-5 w-5 text-amber-600 shrink-0 transition-transform duration-200",
          collapsed && "-rotate-90"
        )}
      />
    </button>
  );
}

/* ── Collapsible subsection header ── */
function SubsectionHeader({
  title,
  subtitle,
  count,
  collapsed,
  onToggle,
}: {
  title: string;
  subtitle?: string;
  count?: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full px-5 py-2.5 bg-stone-50 border-b border-stone-200 flex items-center justify-between cursor-pointer text-left hover:bg-stone-100/60 transition-colors"
    >
      <div>
        <h3 className="text-[13px] font-semibold text-stone-700">
          {title}
          {count !== undefined && (
            <span className="ml-1.5 text-[12px] font-normal text-stone-500">({count})</span>
          )}
        </h3>
        {subtitle && (
          <p className="text-[11px] text-stone-500 mt-0.5">{subtitle}</p>
        )}
      </div>
      <ChevronDown
        className={cn(
          "h-4 w-4 text-stone-400 shrink-0 transition-transform duration-200",
          collapsed && "-rotate-90"
        )}
      />
    </button>
  );
}

/* ── Exception card (used in Schedule B) ── */
function ExceptionCard({ item }: { item: ReportException }) {
  const sevDisplay = SEVERITY_DISPLAY_NAMES[item.severity] || item.severity?.toUpperCase();
  const sevColor = SEVERITY_COLORS[item.severity] || "bg-gray-400 text-white";
  return (
    <div className="flex items-start gap-3 px-5 py-3 border-b last:border-b-0">
      <span className="text-[13px] font-mono text-muted-foreground min-w-[2rem] text-right pt-0.5">
        {item.number}.
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-semibold text-foreground">{item.title}</span>
          {item.severity && (
            <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${sevColor}`}>
              {sevDisplay}
            </span>
          )}
          {item.page_ref && (
            <span className="text-[11px] text-muted-foreground">{item.page_ref}</span>
          )}
        </div>
        {item.description && item.description !== item.title && (
          <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">{item.description}</p>
        )}
        {item.note && (
          <p className="text-[11px] text-muted-foreground/80 mt-1.5 italic">
            <span className="font-semibold not-italic text-muted-foreground">Note:</span> {item.note}
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Paginated exception list ── */
function PaginatedExceptions({ items, keyPrefix }: { items: ReportException[]; keyPrefix: string }) {
  const [page, setPage] = useState(1);
  const paginated = items.length > SECTION_PAGE_SIZE
    ? items.slice((page - 1) * SECTION_PAGE_SIZE, page * SECTION_PAGE_SIZE)
    : items;

  return (
    <>
      {paginated.map((item, i) => (
        <ExceptionCard key={`${keyPrefix}-${i}`} item={item} />
      ))}
      <PaginationControls total={items.length} page={page} onPageChange={setPage} />
    </>
  );
}

/* ── III. Schedule B — Exceptions from Coverage ── */
export function ScheduleBSection({ data }: { data: ReportData }) {
  const { standard_exceptions, specific_exceptions } = data;
  const totalCount = standard_exceptions.length + specific_exceptions.length;
  const [collapsed, setCollapsed] = useState(true);
  const [stdCollapsed, setStdCollapsed] = useState(false);
  const [specCollapsed, setSpecCollapsed] = useState(false);

  if (totalCount === 0) return null;

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <SectionHeader
        title="Schedule B — Exceptions from Coverage"
        subtitle="Items excluded from title insurance coverage"
        count={totalCount}
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
      />
      {!collapsed && (
        <div className="divide-y">
          {/* 3.1 Standard Exceptions */}
          {standard_exceptions.length > 0 && (
            <div>
              <SubsectionHeader
                title="3.1 Standard Exceptions"
                subtitle="Pre-printed exceptions common to all title insurance policies"
                count={standard_exceptions.length}
                collapsed={stdCollapsed}
                onToggle={() => setStdCollapsed((c) => !c)}
              />
              {!stdCollapsed && (
                <PaginatedExceptions items={standard_exceptions} keyPrefix="std" />
              )}
            </div>
          )}

          {/* 3.2 Specific Exceptions */}
          {specific_exceptions.length > 0 && (
            <div>
              <SubsectionHeader
                title="3.2 Specific Exceptions"
                subtitle="Property-specific exceptions identified from the title search"
                count={specific_exceptions.length}
                collapsed={specCollapsed}
                onToggle={() => setSpecCollapsed((c) => !c)}
              />
              {!specCollapsed && (
                <PaginatedExceptions items={specific_exceptions} keyPrefix="spec" />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── IV. Schedule C — Requirements & Conditions ── */
export function ScheduleCSection({ data }: { data: ReportData }) {
  const { requirements } = data;
  const [collapsed, setCollapsed] = useState(true);
  const [page, setPage] = useState(1);

  if (requirements.length === 0) return null;
  const paginated = requirements.length > SECTION_PAGE_SIZE
    ? requirements.slice((page - 1) * SECTION_PAGE_SIZE, page * SECTION_PAGE_SIZE)
    : requirements;

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <SectionHeader
        title="Schedule C — Requirements & Conditions"
        subtitle="Conditions that must be satisfied before policy issuance"
        count={requirements.length}
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
      />
      {!collapsed && (
        <div>
          {paginated.map((req, i) => (
            <RequirementCard key={`req-${i}`} item={req} />
          ))}
          <PaginationControls total={requirements.length} page={page} onPageChange={setPage} />
        </div>
      )}
    </div>
  );
}

function RequirementCard({ item }: { item: ReportRequirement }) {
  const prioColor = PRIORITY_COLORS[item.priority] || "bg-gray-400 text-white";
  return (
    <div className="flex items-start gap-3 px-5 py-3 border-b last:border-b-0">
      <span className="text-[13px] font-mono text-muted-foreground min-w-[2rem] text-right pt-0.5">
        {item.number}.
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-semibold text-foreground">{item.title}</span>
          <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${prioColor}`}>
            {item.priority}
          </span>
          {item.page_ref && (
            <span className="text-[11px] text-muted-foreground">{item.page_ref}</span>
          )}
        </div>
        {item.description && item.description !== item.title && (
          <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">{item.description}</p>
        )}
        {item.status && (
          <span className="text-[11px] text-muted-foreground/70 mt-1 inline-block">
            Status: {item.status}
          </span>
        )}
        {item.note && (
          <p className="text-[11px] text-muted-foreground/80 mt-1.5 italic">
            <span className="font-semibold not-italic text-muted-foreground">Note:</span> {item.note}
          </p>
        )}
      </div>
    </div>
  );
}

/* ── V. Key Warnings & Examiner's Notes ── */
export function WarningsSection({ data }: { data: ReportData }) {
  const { warnings } = data;
  const [collapsed, setCollapsed] = useState(true);
  const [page, setPage] = useState(1);

  if (warnings.length === 0) return null;
  const paginated = warnings.length > SECTION_PAGE_SIZE
    ? warnings.slice((page - 1) * SECTION_PAGE_SIZE, page * SECTION_PAGE_SIZE)
    : warnings;

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <SectionHeader
        title="Key Warnings & Examiner's Notes"
        subtitle="Risk items flagged during title examination"
        count={warnings.length}
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
      />
      {!collapsed && (
        <div className="divide-y">
          {paginated.map((w, i) => (
            <WarningCard key={`warn-${i}`} item={w} />
          ))}
          <PaginationControls total={warnings.length} page={page} onPageChange={setPage} />
        </div>
      )}
    </div>
  );
}

function WarningCard({ item }: { item: ReportWarning }) {
  const sevDisplay = SEVERITY_DISPLAY_NAMES[item.severity] || item.severity?.toUpperCase();
  const sevColor = SEVERITY_COLORS[item.severity] || "bg-gray-400 text-white";
  return (
    <div className="px-5 py-3 border-b last:border-b-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${sevColor}`}>
          {sevDisplay}
        </span>
        <span className="text-[13px] font-semibold text-foreground">{item.title}</span>
      </div>
      {item.explanation && (
        <p className="text-[12px] text-muted-foreground mt-1.5 leading-relaxed">{item.explanation}</p>
      )}
    </div>
  );
}

/* ── VI. Pre-Closing Action Checklist ── */
export function ChecklistSection({ data }: { data: ReportData }) {
  const { checklist_items } = data;
  const [collapsed, setCollapsed] = useState(true);
  const [page, setPage] = useState(1);

  if (checklist_items.length === 0) return null;
  const hasNotes = checklist_items.some((item) => item.note);
  const paginated = checklist_items.length > SECTION_PAGE_SIZE
    ? checklist_items.slice((page - 1) * SECTION_PAGE_SIZE, page * SECTION_PAGE_SIZE)
    : checklist_items;

  return (
    <div className="rounded-xl border bg-card overflow-hidden">
      <SectionHeader
        title="Pre-Closing Action Checklist"
        subtitle="Items requiring resolution before closing"
        count={checklist_items.length}
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
      />
      {!collapsed && (
        <>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="text-left px-5 py-2 font-semibold text-muted-foreground w-12">#</th>
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Action Required</th>
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground w-28">Priority</th>
                <th className="text-center px-3 py-2 font-semibold text-muted-foreground w-20">Status</th>
                {hasNotes && (
                  <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Notes</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y">
              {paginated.map((item) => (
                <ChecklistRow key={`cl-${item.number}`} item={item} hasNotes={hasNotes} />
              ))}
            </tbody>
          </table>
          <PaginationControls total={checklist_items.length} page={page} onPageChange={setPage} />
        </>
      )}
    </div>
  );
}

function ChecklistRow({ item, hasNotes }: { item: ReportChecklistItem; hasNotes: boolean }) {
  return (
    <tr className="hover:bg-muted/10">
      <td className="px-5 py-2.5 font-mono text-muted-foreground">{item.number}</td>
      <td className="px-3 py-2.5 text-foreground">{item.action}</td>
      <td className="px-3 py-2.5">
        <span className="text-[11px] font-semibold text-muted-foreground">{item.priority}</span>
      </td>
      <td className="px-3 py-2.5 text-center">
        <span className="text-[11px] text-muted-foreground">{item.checked ? "Done" : "Pending"}</span>
      </td>
      {hasNotes && (
        <td className="px-3 py-2.5 text-[12px] text-muted-foreground italic">{item.note || ""}</td>
      )}
    </tr>
  );
}
