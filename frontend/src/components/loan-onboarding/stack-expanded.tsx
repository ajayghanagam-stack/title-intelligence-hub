"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  ArrowRight,
  ChevronDown,
  Eye,
  FileSearch,
  FileText,
  Undo2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiFetchBlob } from "@/lib/api";
import {
  applyPageOverride,
  removePageOverride,
} from "@/lib/loan-onboarding/api";
import { LOAN_DOC_TYPE_LABELS } from "@/lib/loan-onboarding/constants";
import { blendOverallNoSplit } from "@/components/loan-onboarding/confidence-breakdown";
import type {
  LoanStack,
  LoanStackPage,
  LoanStackExtraction,
  LoanValidationResult,
  LoanPageOverride,
} from "@/lib/loan-onboarding/types";
import { ExtractedFieldsPanel } from "@/components/loan-onboarding/extracted-fields-panel";

interface Props {
  orgId: string;
  packageId: string;
  stack: LoanStack;
  validation: LoanValidationResult | undefined;
  /** All stacks in the package — used to populate the "Move to…" dropdown. */
  allStacks: LoanStack[];
  /** Doc types configured at upload (keys). Combined with allStacks doc types
   *  so the Move dropdown can target a configured type even if no stack of
   *  that type currently exists in the result. */
  packageDocTypes: string[];
  /** Page overrides keyed by page_id so we can render Undo for moved pages. */
  overrides: Map<string, LoanPageOverride>;
  /** Per-stack field extraction (Section D). Optional — null when extraction
   *  is disabled for the package or this stack's doc type has no fields. */
  extraction?: LoanStackExtraction | null;
  /** Called after any successful move/undo so the parent can refetch. */
  onMutated: () => void;
}

/**
 * Expanded details rendered beneath a stack row on the Results tab.
 *
 * Three diagnostic panels (Split Points · Validation · Score Breakdown).
 * Score Breakdown shows classification + validation only (split accuracy is
 * a deterministic heuristic that doesn't help users triage stacks, so it's
 * intentionally hidden here and on the dashboard).
 * describe *what happened*. The View pages → Move action lets the user
 * correct misclassified pages via applyPageOverride.
 *
 * A stack-level Reclassify action is intentionally omitted until the
 * backend exposes an endpoint for it — the page-override path covers
 * most correction cases today.
 */
export function StackExpanded({
  orgId,
  packageId,
  stack,
  validation,
  allStacks,
  packageDocTypes,
  overrides,
  extraction,
  onMutated,
}: Props) {
  const [showPages, setShowPages] = useState(false);
  const [busyPageId, setBusyPageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const rules = validation?.rules_evaluated ?? [];
  const rulesPassed = rules.filter((r) => r.passed).length;
  const rulesTotal = rules.length;
  const failedRules = rules.filter((r) => !r.passed);

  // Split points: count pages inside this stack whose page_role indicates
  // the start of a sub-document. In the deterministic stacker today this is
  // typically 1, but we surface whatever's in the data so it stays honest.
  const subDocCount =
    stack.pages.filter((p) => p.page_role === "first_page").length || 1;

  const breakdown = validation?.confidence_breakdown ?? {
    classification: null,
    split_accuracy: null,
    validation: null,
  };

  // Move destination options — union of every doc_type present in any stack
  // and every doc_type configured for the package, minus this stack's own
  // doc_type. This lets the user move pages to a configured type even if no
  // stack of that type exists yet (e.g. moving a misclassified page out of
  // the catch-all "Others" bucket).
  const moveOptions = useMemo(
    () =>
      Array.from(
        new Set([
          ...allStacks.map((s) => s.doc_type),
          ...packageDocTypes,
        ])
      ).filter((dt) => dt !== stack.doc_type),
    [allStacks, packageDocTypes, stack.doc_type]
  );

  const handleMove = async (page: LoanStackPage, targetDocType: string) => {
    setBusyPageId(page.page_id);
    setError(null);
    try {
      await applyPageOverride(orgId, packageId, page.page_id, {
        assigned_doc_type: targetDocType,
      });
      onMutated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to move page");
    } finally {
      setBusyPageId(null);
    }
  };

  const handleUndo = async (page: LoanStackPage) => {
    setBusyPageId(page.page_id);
    setError(null);
    try {
      await removePageOverride(orgId, packageId, page.page_id);
      onMutated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to undo move");
    } finally {
      setBusyPageId(null);
    }
  };

  return (
    <div
      className="mt-3 rounded-lg border border-border/60 bg-muted/20 p-4 space-y-4"
      data-testid={`stack-expanded-${stack.stack_index}`}
    >
      {/* Three diagnostic panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Split Points */}
        <div>
          <h4 className="text-[10px] font-mono tracking-[0.2em] text-muted-foreground uppercase mb-2">
            Split Points
          </h4>
          <div className="rounded-md bg-background border border-border/60 p-3 space-y-1">
            <div className="text-sm font-medium">
              Page {stack.first_page} → {stack.last_page}
            </div>
            <div className="text-xs text-muted-foreground">
              {stack.page_count} page{stack.page_count === 1 ? "" : "s"}
            </div>
            <div className="text-xs text-muted-foreground">
              {subDocCount} sub-document{subDocCount === 1 ? "" : "s"} detected
            </div>
          </div>
        </div>

        {/* Validation */}
        <div>
          <h4 className="text-[10px] font-mono tracking-[0.2em] text-muted-foreground uppercase mb-2">
            Validation
          </h4>
          <div
            className={cn(
              "rounded-md border p-3 space-y-2",
              rulesTotal === 0
                ? "bg-background border-border/60"
                : failedRules.length === 0
                  ? "bg-emerald-50/60 border-emerald-200"
                  : "bg-amber-50/60 border-amber-200"
            )}
          >
            {rulesTotal === 0 ? (
              <div className="text-xs text-muted-foreground">
                No rules evaluated for this stack.
              </div>
            ) : failedRules.length === 0 ? (
              <div className="flex items-center gap-2 text-sm text-emerald-700">
                <CheckCircle2 className="h-4 w-4" />
                All checks passed ({rulesPassed}/{rulesTotal})
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 text-sm text-amber-800 font-medium">
                  <AlertTriangle className="h-4 w-4" />
                  {failedRules.length} issue
                  {failedRules.length === 1 ? "" : "s"} ({rulesPassed}/
                  {rulesTotal} passed)
                </div>
                <ul className="space-y-1 text-xs text-amber-900">
                  {failedRules.slice(0, 4).map((r) => (
                    <li key={r.rule_id} className="flex gap-1.5">
                      <span className="shrink-0 text-amber-700">•</span>
                      <span>
                        <span className="font-medium">{r.label}</span>
                        {r.detail ? (
                          <span className="text-amber-800/80">
                            {" "}
                            — {r.detail}
                          </span>
                        ) : null}
                      </span>
                    </li>
                  ))}
                  {failedRules.length > 4 && (
                    <li className="text-[11px] text-amber-800/80 italic">
                      +{failedRules.length - 4} more
                    </li>
                  )}
                </ul>
              </>
            )}
          </div>
        </div>

        {/* Score Breakdown */}
        <div>
          <h4 className="text-[10px] font-mono tracking-[0.2em] text-muted-foreground uppercase mb-2">
            Score Breakdown
          </h4>
          <div className="rounded-md bg-background border border-border/60 p-3 space-y-2">
            <ScoreRow
              label="Classification"
              value={breakdown.classification}
            />
            <ScoreRow
              label="Validation"
              value={breakdown.validation}
            />
            {(() => {
              // Recompute Overall from classification + validation only so
              // the number stays consistent with the rows above, even on
              // stacks whose stored overall_confidence still folds in
              // split-accuracy from a pre-v5 run.
              const effective = blendOverallNoSplit(breakdown);
              return (
                <div className="border-t border-border/60 pt-2 mt-2 flex items-center justify-between text-xs">
                  <span className="font-medium">Overall</span>
                  <span className="font-mono tabular-nums font-semibold">
                    {effective === null
                      ? "—"
                      : `${Math.round(effective * 100)}%`}
                  </span>
                </div>
              );
            })()}
          </div>
        </div>
      </div>

      {/* Extracted fields (Section D output) — shown only when the package
          has extraction enabled and the agent emitted fields for this stack. */}
      <ExtractedFieldsPanel extraction={extraction} />

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setShowPages((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-background hover:bg-muted/60 px-3 py-1.5 text-xs font-medium"
          data-testid={`view-pages-${stack.stack_index}`}
        >
          <Eye className="h-3.5 w-3.5" />
          {showPages ? "Hide pages" : "View pages"}
        </button>

        {error && (
          <span className="text-xs text-red-600">{error}</span>
        )}
      </div>

      {/* View pages drawer — 2-column thumbnail strip + preview viewer */}
      {showPages && (
        <PageViewer
          orgId={orgId}
          packageId={packageId}
          stack={stack}
          overrides={overrides}
          moveOptions={moveOptions}
          busyPageId={busyPageId}
          onMove={handleMove}
          onUndo={handleUndo}
        />
      )}
    </div>
  );
}

function ScoreRow({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  const pct =
    value === null || value === undefined ? null : Math.round(value * 100);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono tabular-nums">
          {pct === null ? "—" : `${pct}%`}
        </span>
      </div>
      <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full",
            pct === null
              ? "bg-muted-foreground/20"
              : pct >= 85
                ? "bg-emerald-500"
                : pct >= 70
                  ? "bg-amber-500"
                  : "bg-red-500"
          )}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>
    </div>
  );
}

/**
 * Authenticated <img> loader. Mirrors the TI documents-page pattern:
 * fetches the JPEG via apiFetchBlob (which injects auth + org headers),
 * renders the result via URL.createObjectURL, and revokes on unmount or
 * path change to avoid leaking blob URLs.
 */
function AuthImage({
  path,
  orgId,
  alt,
  className,
}: {
  path: string;
  orgId: string;
  alt: string;
  className?: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<boolean>(false);
  const srcRef = useRef<string | null>(null);

  useEffect(() => {
    let revoked = false;
    setError(false);
    setSrc(null);

    apiFetchBlob(path, { orgId })
      .then((blob) => {
        if (revoked) return;
        const url = URL.createObjectURL(blob);
        srcRef.current = url;
        setSrc(url);
      })
      .catch((err) => {
        console.error(`Failed to load image ${path}:`, err);
        if (!revoked) setError(true);
      });
    return () => {
      revoked = true;
      if (srcRef.current) URL.revokeObjectURL(srcRef.current);
    };
  }, [path, orgId]);

  if (error) {
    return (
      <div
        className={cn(
          "bg-red-50 flex items-center justify-center text-red-400",
          className
        )}
      >
        <FileSearch className="h-6 w-6" />
      </div>
    );
  }

  if (!src) {
    return (
      <div
        className={cn("bg-muted/40 animate-pulse rounded", className)}
      />
    );
  }

  return <img src={src} alt={alt} className={className} />;
}

interface PageViewerProps {
  orgId: string;
  packageId: string;
  stack: LoanStack;
  overrides: Map<string, LoanPageOverride>;
  moveOptions: string[];
  busyPageId: string | null;
  onMove: (page: LoanStackPage, target: string) => void;
  onUndo: (page: LoanStackPage) => void;
}

/**
 * Two-column page viewer rendered inline beneath a stack row. Mirrors the
 * Loan Onboarding prototype:
 *   - Left: scrollable thumbnail strip listing every page in the stack with
 *     page number, role, and an arrow to the move target if overridden.
 *   - Right: a metadata "preview" surface (no real page images yet) plus a
 *     Move-to dropdown + Move/Undo action bar for the active page.
 *
 * The preview surface is intentionally a styled metadata mock — the loan
 * onboarding backend does not currently expose a per-page image endpoint.
 */
function PageViewer({
  orgId,
  packageId,
  stack,
  overrides,
  moveOptions,
  busyPageId,
  onMove,
  onUndo,
}: PageViewerProps) {
  const pages = stack.pages;
  const [activePageId, setActivePageId] = useState<string | null>(
    pages[0]?.page_id ?? null
  );
  const [search, setSearch] = useState("");
  const [draftByPage, setDraftByPage] = useState<Record<string, string>>({});

  // Combobox popover state — mirrors the prototype's pickerOpen/pickerQuery
  // pair. Closes on thumbnail switch, on outside click, or after a selection.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const closePicker = () => {
    setPickerOpen(false);
    setPickerQuery("");
  };

  // Close on Escape while the picker is open.
  useEffect(() => {
    if (!pickerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closePicker();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pickerOpen]);

  const visiblePages = useMemo(() => {
    const q = search.trim();
    if (!q) return pages;
    return pages.filter((p) => String(p.page_number).startsWith(q));
  }, [pages, search]);

  const activePage =
    pages.find((p) => p.page_id === activePageId) ??
    visiblePages[0] ??
    pages[0] ??
    null;

  const activeOverride = activePage ? overrides.get(activePage.page_id) : undefined;
  const activeDraft = activePage
    ? (draftByPage[activePage.page_id] ?? "")
    : "";
  const movedCount = pages.filter((p) => overrides.has(p.page_id)).length;
  const currentDocType = stack.doc_type;
  const currentLabel = LOAN_DOC_TYPE_LABELS[currentDocType] ?? currentDocType;

  if (pages.length === 0) {
    return (
      <div
        className="rounded-md border border-border/60 bg-background py-6 text-center text-xs text-muted-foreground"
        data-testid={`pages-drawer-${stack.stack_index}`}
      >
        No pages in this stack.
      </div>
    );
  }

  return (
    <div data-testid={`pages-drawer-${stack.stack_index}`}>
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[10px] font-mono tracking-[0.2em] text-muted-foreground uppercase">
            Page viewer · {currentLabel}
          </div>
          <div className="text-[10px] font-mono text-muted-foreground mt-0.5 tabular-nums">
            {pages.length} page{pages.length === 1 ? "" : "s"} · {movedCount}{" "}
            moved
          </div>
        </div>
        <input
          type="text"
          inputMode="numeric"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Jump to page #"
          className="w-32 rounded-md border border-input bg-background px-2 py-1 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          aria-label="Filter pages by number"
        />
      </div>

      <div className="grid grid-cols-[180px_1fr] bg-background border border-border/60 rounded-md overflow-hidden">
        {/* Left: thumbnail strip */}
        <div className="border-r border-border/60 flex flex-col">
          <div className="px-3 py-2 bg-muted/40 border-b border-border/60 flex items-center justify-between">
            <span className="text-[9px] font-mono tracking-[0.2em] text-muted-foreground uppercase">
              Pages
            </span>
            <span className="text-[9px] font-mono tabular-nums text-muted-foreground">
              {visiblePages.length}/{pages.length}
            </span>
          </div>
          <div className="overflow-y-auto max-h-[460px]">
            {visiblePages.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-muted-foreground italic">
                No pages match.
              </div>
            ) : (
              visiblePages.map((pg) => {
                const o = overrides.get(pg.page_id);
                const isActive = activePage?.page_id === pg.page_id;
                return (
                  <button
                    key={pg.page_id}
                    type="button"
                    onClick={() => {
                      setActivePageId(pg.page_id);
                      closePicker();
                    }}
                    className={cn(
                      "w-full flex items-center gap-2 px-2 py-2 text-left border-b border-border/60 transition-colors border-l-2",
                      isActive
                        ? "bg-amber-50/70 border-l-amber-500"
                        : "hover:bg-muted/40 border-l-transparent"
                    )}
                    data-testid={`thumb-${pg.page_number}`}
                  >
                    <div
                      className={cn(
                        "w-9 h-12 shrink-0 border rounded flex items-center justify-center",
                        o
                          ? "bg-amber-50 border-amber-300"
                          : "bg-muted/40 border-border/60"
                      )}
                    >
                      <FileText
                        className="h-3.5 w-3.5 text-muted-foreground"
                        strokeWidth={1.5}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-[11px] tabular-nums">
                        p. {pg.page_number}
                      </div>
                      {pg.page_role && (
                        <div className="font-mono text-[9px] text-muted-foreground uppercase tracking-[0.1em] truncate">
                          {pg.page_role.replace(/_/g, " ")}
                        </div>
                      )}
                      {o && (
                        <div className="font-mono text-[9px] text-amber-700 truncate mt-0.5">
                          →{" "}
                          {LOAN_DOC_TYPE_LABELS[o.assigned_doc_type] ??
                            o.assigned_doc_type}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right: preview surface + move action bar */}
        <div className="flex flex-col">
          <div className="px-4 py-2 bg-muted/40 border-b border-border/60 flex items-center justify-between gap-3">
            <div className="flex items-baseline gap-3 min-w-0">
              <div className="text-sm font-medium truncate">
                {activePage ? `Page ${activePage.page_number}` : "No page"}
              </div>
              {activePage && (
                <div className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase truncate">
                  {(activePage.page_role ?? "page").replace(/_/g, " ")}
                  {activePage.confidence != null &&
                    ` · ${Math.round(activePage.confidence * 100)}% conf.`}
                </div>
              )}
            </div>
            <div className="font-mono text-[10px] text-muted-foreground shrink-0">
              Current:{" "}
              <span className="text-foreground font-medium">{currentLabel}</span>
              {activeOverride && (
                <span className="inline-flex items-center gap-1 ml-2 text-amber-700">
                  <ArrowRight className="h-3 w-3" />
                  <span className="font-medium">
                    {LOAN_DOC_TYPE_LABELS[activeOverride.assigned_doc_type] ??
                      activeOverride.assigned_doc_type}
                  </span>
                </span>
              )}
            </div>
          </div>

          {/* Real PDF page preview — rendered on demand via PyMuPDF. */}
          <div className="flex-1 px-6 py-6 flex items-center justify-center bg-amber-50/30 min-h-[400px]">
            {activePage ? (
              <div className="bg-card border border-border shadow-sm rounded overflow-hidden">
                <AuthImage
                  key={activePage.page_id}
                  path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${activePage.page_id}/image`}
                  orgId={orgId}
                  alt={`Page ${activePage.page_number}`}
                  className="block max-h-[520px] max-w-full w-auto h-auto"
                />
              </div>
            ) : (
              <div className="text-xs text-muted-foreground italic">
                Select a page from the left.
              </div>
            )}
          </div>

          {/* Move action bar */}
          {activePage && (() => {
            const q = pickerQuery.trim().toLowerCase();
            const filtered = q
              ? moveOptions.filter((dt) =>
                  (LOAN_DOC_TYPE_LABELS[dt] ?? dt)
                    .toLowerCase()
                    .includes(q)
                )
              : moveOptions;
            const activeDraftLabel = activeDraft
              ? (LOAN_DOC_TYPE_LABELS[activeDraft] ?? activeDraft)
              : "";
            const triggerDisabled =
              !!activeOverride ||
              busyPageId === activePage.page_id ||
              moveOptions.length === 0;
            return (
            <div className="px-4 py-3 border-t border-border/60 bg-card flex items-center gap-3">
              <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase shrink-0">
                Move to
              </span>
              <div className="flex-1 relative">
                <button
                  type="button"
                  onClick={() => {
                    if (triggerDisabled) return;
                    setPickerOpen((o) => !o);
                  }}
                  disabled={triggerDisabled}
                  aria-haspopup="listbox"
                  aria-expanded={pickerOpen}
                  aria-label="Move target doc type"
                  className={cn(
                    "w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs flex items-center justify-between gap-2",
                    "hover:border-border focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                  data-testid={`move-trigger-${activePage.page_number}`}
                >
                  <span
                    className={cn(
                      "truncate",
                      activeDraft ? "text-foreground" : "text-muted-foreground"
                    )}
                  >
                    {moveOptions.length === 0
                      ? "No other doc types configured"
                      : activeDraftLabel || "Choose document type…"}
                  </span>
                  <ChevronDown
                    className={cn(
                      "h-3 w-3 text-muted-foreground shrink-0 transition-transform",
                      pickerOpen && "rotate-180"
                    )}
                  />
                </button>
                {pickerOpen && !activeOverride && (
                  <>
                    {/* Click-outside backdrop closes the popover. */}
                    <div
                      className="fixed inset-0 z-10"
                      onClick={closePicker}
                      aria-hidden
                    />
                    {/* Popover above the trigger so it stays inside the viewer. */}
                    <div
                      className="absolute bottom-full left-0 right-0 mb-2 bg-popover border border-border rounded-md shadow-lg z-20 flex flex-col"
                      role="listbox"
                    >
                      <div className="p-2 border-b border-border/60">
                        <input
                          autoFocus
                          value={pickerQuery}
                          onChange={(e) => setPickerQuery(e.target.value)}
                          placeholder="Search doc types…"
                          className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                          aria-label="Search doc types"
                        />
                      </div>
                      <div className="overflow-y-auto max-h-[220px]">
                        {filtered.length === 0 ? (
                          <div className="px-3 py-4 text-[11px] text-muted-foreground italic">
                            No doc types match.
                          </div>
                        ) : (
                          filtered.map((dt) => {
                            const label =
                              LOAN_DOC_TYPE_LABELS[dt] ?? dt;
                            const selected = activeDraft === dt;
                            return (
                              <button
                                key={dt}
                                type="button"
                                role="option"
                                aria-selected={selected}
                                onClick={() => {
                                  setDraftByPage((prev) => ({
                                    ...prev,
                                    [activePage.page_id]: dt,
                                  }));
                                  closePicker();
                                }}
                                className={cn(
                                  "w-full text-left px-3 py-1.5 text-xs hover:bg-muted/60 transition-colors",
                                  selected
                                    ? "bg-amber-50/70 text-foreground font-medium"
                                    : "text-foreground"
                                )}
                                data-testid={`move-option-${dt}`}
                              >
                                {label}
                              </button>
                            );
                          })
                        )}
                      </div>
                      <div className="px-3 py-1.5 border-t border-border/60 bg-muted/40 font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase tabular-nums flex items-center justify-between">
                        <span>
                          {filtered.length} of {moveOptions.length}
                        </span>
                        <span>Esc / click outside to close</span>
                      </div>
                    </div>
                  </>
                )}
              </div>
              {activeOverride ? (
                <button
                  type="button"
                  onClick={() => onUndo(activePage)}
                  disabled={busyPageId === activePage.page_id}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-background hover:bg-muted/60 px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                  data-testid={`undo-${activePage.page_number}`}
                >
                  <Undo2 className="h-3 w-3" /> Undo move
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => activeDraft && onMove(activePage, activeDraft)}
                  disabled={
                    !activeDraft ||
                    busyPageId === activePage.page_id ||
                    moveOptions.length === 0
                  }
                  className="inline-flex items-center gap-1.5 rounded-md bg-foreground text-background hover:opacity-90 px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                  data-testid={`move-${activePage.page_number}`}
                >
                  <ArrowRight className="h-3 w-3" /> Move page
                </button>
              )}
            </div>
            );
          })()}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <AlertCircle className="h-3 w-3" />
        Move targets include every doc type configured for this package.
      </div>
    </div>
  );
}
