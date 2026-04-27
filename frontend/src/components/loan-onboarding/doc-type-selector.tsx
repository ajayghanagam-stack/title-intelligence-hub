"use client";

import { useMemo, useState } from "react";
import {
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Plus,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import {
  SUGGESTED_DOC_TYPES,
  TOTAL_DOC_TYPE_COUNT,
} from "@/lib/loan-onboarding/constants";
import type { LoanDocTypeSpec } from "@/lib/loan-onboarding/types";

interface Props {
  value: LoanDocTypeSpec[];
  onChange: (next: LoanDocTypeSpec[]) => void;
}

const PAGE_SIZE = 5;

const isLocked = (spec: { key: string; locked?: boolean }): boolean => {
  if (spec.locked) return true;
  const suggested = SUGGESTED_DOC_TYPES.find((d) => d.key === spec.key);
  return !!suggested?.locked;
};

function slugifyKey(input: string): string {
  return input
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function matchesQuery(spec: LoanDocTypeSpec, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    spec.label.toLowerCase().includes(q) ||
    spec.key.toLowerCase().includes(q) ||
    (spec.description?.toLowerCase().includes(q) ?? false)
  );
}

export function DocTypeSelector({ value, onChange }: Props) {
  const [customLabel, setCustomLabel] = useState("");
  const [customDesc, setCustomDesc] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  // Custom-added doc types live alongside catalog items in the paginated list.
  // They are real doc type specs — added to `value` on creation and sent to
  // the backend classifier like any catalog entry.
  const [customSpecs, setCustomSpecs] = useState<LoanDocTypeSpec[]>([]);

  const selectedKeys = useMemo(
    () => new Set(value.map((d) => d.key)),
    [value]
  );
  const customKeys = useMemo(
    () => new Set(customSpecs.map((s) => s.key)),
    [customSpecs]
  );

  const selectedCount = value.filter((d) => !isLocked(d)).length;

  // Combined list: catalog first, then customs. Filtered by search.
  const allSpecs = useMemo(
    () => [...SUGGESTED_DOC_TYPES, ...customSpecs],
    [customSpecs]
  );
  const filtered = useMemo(
    () => allSpecs.filter((s) => matchesQuery(s, query)),
    [allSpecs, query]
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  // Clamp current page to valid range whenever filter shrinks the list.
  const clampedPage = Math.min(page, totalPages);
  const startIdx = (clampedPage - 1) * PAGE_SIZE;
  const pageItems = filtered.slice(startIdx, startIdx + PAGE_SIZE);

  const toggle = (spec: LoanDocTypeSpec) => {
    if (isLocked(spec)) return;
    if (selectedKeys.has(spec.key)) {
      onChange(value.filter((d) => d.key !== spec.key));
    } else {
      onChange([...value, spec]);
    }
  };

  const selectAll = () => {
    const next = [...value];
    for (const spec of allSpecs) {
      if (!next.some((d) => d.key === spec.key)) next.push(spec);
    }
    onChange(next);
  };

  const clearAll = () => {
    onChange(value.filter((d) => isLocked(d)));
  };

  const addCustom = () => {
    const label = customLabel.trim();
    if (!label) return;
    const key = slugifyKey(label);
    if (!key) {
      setCustomLabel("");
      setCustomDesc("");
      return;
    }
    const catalogKeys = new Set(SUGGESTED_DOC_TYPES.map((s) => s.key));
    if (catalogKeys.has(key) || customKeys.has(key)) {
      setCustomLabel("");
      setCustomDesc("");
      return;
    }
    const description = customDesc.trim() || undefined;
    const spec: LoanDocTypeSpec = { key, label, description, required: false };
    setCustomSpecs((prev) => [...prev, spec]);
    onChange([...value, spec]);
    setCustomLabel("");
    setCustomDesc("");
    // Jump to the last page so the newly added row is visible.
    const newTotal = filtered.length + 1;
    setPage(Math.max(1, Math.ceil(newTotal / PAGE_SIZE)));
  };

  const removeCustomSpec = (key: string) => {
    setCustomSpecs((prev) => prev.filter((s) => s.key !== key));
    onChange(value.filter((d) => d.key !== key));
  };

  return (
    <div className="space-y-5">
      {/* Search + selected counter + bulk actions */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search documents (e.g. appraisal, VOE, 1099)…"
            className="h-10 pl-9"
            data-testid="doc-type-search"
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium",
              selectedCount > 0
                ? "bg-[oklch(0.750_0.170_65)]/10 text-[oklch(0.750_0.170_65)] ring-1 ring-[oklch(0.750_0.170_65)]/30"
                : "bg-muted text-muted-foreground ring-1 ring-border"
            )}
            data-testid="doc-type-selected-count"
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            {selectedCount} / {TOTAL_DOC_TYPE_COUNT + customSpecs.length} selected
          </span>
          <button
            type="button"
            onClick={selectAll}
            className="text-xs font-medium text-[oklch(0.750_0.170_65)] hover:underline"
            data-testid="doc-type-select-all"
          >
            Select all
          </button>
          {selectedCount > 0 && (
            <button
              type="button"
              onClick={clearAll}
              className="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              data-testid="doc-type-clear-all"
            >
              Clear all
            </button>
          )}
        </div>
      </div>

      {/* Paginated flat list */}
      <div className="rounded-xl border border-border/60 bg-card/30 overflow-hidden">
        {pageItems.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            {query ? (
              <>
                No documents match{" "}
                <span className="font-medium">&ldquo;{query}&rdquo;</span>.
              </>
            ) : (
              <>No documents.</>
            )}
          </div>
        ) : (
          <div>
            {pageItems.map((spec, i) => {
              const active = selectedKeys.has(spec.key);
              const custom = customKeys.has(spec.key);
              return (
                <div
                  key={spec.key}
                  role="button"
                  tabIndex={0}
                  aria-pressed={active}
                  onClick={() => toggle(spec)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggle(spec);
                    }
                  }}
                  className={cn(
                    "flex items-center gap-4 px-5 py-3.5 cursor-pointer transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.750_0.170_65)]/40",
                    i > 0 && "border-t border-border/60",
                    active ? "bg-[oklch(0.750_0.170_65)]/5" : "hover:bg-muted/40"
                  )}
                  data-testid={`doc-type-row-${spec.key}`}
                >
                  {/* Checkbox */}
                  <div
                    className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-all",
                      active
                        ? "bg-[oklch(0.750_0.170_65)] border-[oklch(0.750_0.170_65)]"
                        : "bg-background border-input"
                    )}
                  >
                    {active && (
                      <Check
                        className="h-3 w-3 text-white"
                        strokeWidth={3}
                      />
                    )}
                  </div>

                  {/* Label + description */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {custom && (
                        <Sparkles className="h-3.5 w-3.5 shrink-0 text-violet-500" />
                      )}
                      <span className="text-sm font-medium text-foreground truncate">
                        {spec.label}
                      </span>
                      {custom && (
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-violet-600 bg-violet-50 ring-1 ring-violet-200 rounded px-1.5 py-0.5">
                          Custom
                        </span>
                      )}
                    </div>
                    {spec.description && (
                      <div className="text-xs text-muted-foreground mt-0.5 truncate">
                        {spec.description}
                      </div>
                    )}
                  </div>

                  {/* Key badge */}
                  <div className="font-mono text-[10px] text-muted-foreground shrink-0 w-48 truncate text-right">
                    {spec.key}
                  </div>

                  {/* Remove custom */}
                  {custom && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeCustomSpec(spec.key);
                      }}
                      aria-label={`Remove custom document ${spec.label}`}
                      className="shrink-0 rounded-md p-1.5 text-muted-foreground/60 hover:text-red-600 hover:bg-red-50 transition-colors"
                      data-testid={`doc-type-custom-remove-${spec.key}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Pagination */}
      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs">
          <div className="text-muted-foreground">
            Showing{" "}
            <span className="font-medium tabular-nums">
              {startIdx + 1}–{Math.min(startIdx + PAGE_SIZE, filtered.length)}
            </span>{" "}
            of{" "}
            <span className="font-medium tabular-nums">{filtered.length}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={clampedPage <= 1}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="doc-type-page-prev"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Prev
            </button>
            {/* Window of 5 page numbers — Prev/Next sit immediately on either
                side of the visible window so we don't render all 13 pages
                inline. Window slides by 5: 1–5, 6–10, 11–13, etc. */}
            {(() => {
              const WINDOW = 5;
              const windowStart =
                Math.floor((clampedPage - 1) / WINDOW) * WINDOW + 1;
              const windowEnd = Math.min(windowStart + WINDOW - 1, totalPages);
              const pages: number[] = [];
              for (let p = windowStart; p <= windowEnd; p++) pages.push(p);
              return pages.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPage(p)}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-xs font-medium tabular-nums transition-colors",
                    p === clampedPage
                      ? "bg-[oklch(0.750_0.170_65)] text-white"
                      : "hover:bg-muted text-foreground/70"
                  )}
                  data-testid={`doc-type-page-${p}`}
                >
                  {p}
                </button>
              ));
            })()}
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={clampedPage >= totalPages}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="doc-type-page-next"
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Add custom document */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-3">
        <div className="flex items-start gap-2">
          <Sparkles className="h-4 w-4 mt-0.5 shrink-0 text-[oklch(0.750_0.170_65)]" />
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              Add a new document type
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Appears in the list as a selectable row and is sent to the
              classifier for this package.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2">
          <Input
            value={customLabel}
            onChange={(e) => setCustomLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder="Name (e.g. IRS Transcript)"
            className="h-10"
            data-testid="doc-type-custom-input"
          />
          <Input
            value={customDesc}
            onChange={(e) => setCustomDesc(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder="Description (optional)"
            className="h-10"
            data-testid="doc-type-custom-desc"
          />
          <button
            type="button"
            onClick={addCustom}
            disabled={!customLabel.trim()}
            className="inline-flex items-center justify-center gap-1.5 rounded-md px-4 text-sm font-medium bg-[oklch(0.750_0.170_65)] text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed h-10"
            data-testid="doc-type-custom-add"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
