"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Expand,
  Eye,
  FileSearch,
  GalleryHorizontal,
  LayoutList,
  Maximize2,
  Undo2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { cn } from "@/lib/utils";
import { apiFetchBlob } from "@/lib/api";
import {
  applyPageOverride,
  removePageOverride,
} from "@/lib/loan-onboarding/api";
import {
  LOAN_DOC_TYPE_LABELS,
  OTHERS_DOC_TYPE_KEY,
  SUGGESTED_DOC_TYPES,
} from "@/lib/loan-onboarding/constants";
import { blendOverallNoSplit } from "@/components/loan-onboarding/confidence-breakdown";
import type {
  LoanStack,
  LoanStackPage,
  LoanStackExtraction,
  LoanValidationResult,
  LoanPageOverride,
  LoanPageRole,
  LoanDocTypeSpec,
} from "@/lib/loan-onboarding/types";
import { ExtractedFieldsPanel } from "@/components/loan-onboarding/extracted-fields-panel";

/** Move-target option for the "Move to…" picker. Hoisted to module scope so
 *  the inner PageViewer can type its `moveOptions` prop against it. */
type MoveOption = {
  key: string;
  label: string;
  description?: string;
  required: boolean;
  group: "configured" | "detected" | "suggested" | "catch-all";
};

interface Props {
  orgId: string;
  packageId: string;
  stack: LoanStack;
  validation: LoanValidationResult | undefined;
  /** All stacks in the package — used to populate the "Move to…" dropdown. */
  allStacks: LoanStack[];
  /** Doc types configured at upload (full specs — key/label/description/required).
   *  Drives the primary "Expected for this package" section in the Move dropdown. */
  packageDocTypeSpecs: LoanDocTypeSpec[];
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
  packageDocTypeSpecs,
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

  // Move destination options — built as rich entries (label + description +
  // required + group) so the picker can render a grouped, hierarchical list:
  //   1. Expected for this package      ← the configured doc types
  //   2. Other detected types           ← runtime stacks not in config
  //   3. Other common types             ← canonical catalog fallback
  //   4. Catch-all                      ← Others (always last)
  // The grouping is what makes the picker feel intuitive: the user sees
  // their configured list FIRST, with required pills, before falling back
  // to the broader catalog. The current stack's own type is excluded.
  const moveOptions = useMemo<MoveOption[]>(() => {
    const seen = new Set<string>();
    const out: MoveOption[] = [];
    const push = (opt: MoveOption) => {
      if (opt.key === stack.doc_type) return;
      if (seen.has(opt.key)) return;
      seen.add(opt.key);
      out.push(opt);
    };

    // 1. Configured types (preserve config order — required-ness matters here)
    for (const spec of packageDocTypeSpecs) {
      push({
        key: spec.key,
        label: spec.label,
        description: spec.description,
        required: spec.required,
        group: "configured",
      });
    }

    // 2. Doc types that exist at runtime as stacks but weren't configured
    //    (e.g. AI created an "Others" bucket, or a custom type added later)
    for (const s of allStacks) {
      if (s.doc_type === OTHERS_DOC_TYPE_KEY) continue;
      const fromCatalog = SUGGESTED_DOC_TYPES.find((d) => d.key === s.doc_type);
      push({
        key: s.doc_type,
        label:
          fromCatalog?.label ??
          LOAN_DOC_TYPE_LABELS[s.doc_type] ??
          s.doc_type,
        description: fromCatalog?.description,
        required: false,
        group: "detected",
      });
    }

    // 3. Canonical catalog fallback — always include so the LO can route a
    //    page to a common doc type even when it wasn't pre-configured. This
    //    is the fix for the "dropdown only shows 1 type" symptom that
    //    happens when the package config is sparse.
    for (const spec of SUGGESTED_DOC_TYPES) {
      push({
        key: spec.key,
        label: spec.label,
        description: spec.description,
        required: spec.required,
        group: "suggested",
      });
    }

    // 4. Others — always present as the demote-anywhere target
    push({
      key: OTHERS_DOC_TYPE_KEY,
      label: "Others (catch-all)",
      description: "Pages that don't fit any expected document type",
      required: false,
      group: "catch-all",
    });

    return out;
  }, [allStacks, packageDocTypeSpecs, stack.doc_type]);

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

  /**
   * Re-role a page WITHIN the current stack's doc type. Promoting a
   * continuation to `first_page` splits the stack here; flipping a page to
   * `signature_page` regroups it accordingly. The override keeps the
   * page's effective doc_type unchanged — only `page_role_override` moves.
   */
  const handleChangeRole = async (
    page: LoanStackPage,
    role: LoanPageRole,
  ) => {
    setBusyPageId(page.page_id);
    setError(null);
    try {
      await applyPageOverride(orgId, packageId, page.page_id, {
        assigned_doc_type: stack.doc_type,
        page_role_override: role,
      });
      onMutated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change page role");
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
          onChangeRole={handleChangeRole}
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
 *
 * Two reliability features sit on top of the basic fetch:
 *
 * 1. **Lazy loading via IntersectionObserver.** A 100-page packet has 100
 *    thumbs; without lazy loading every revisit fires 100 parallel auth-
 *    fetches and the browser's per-host concurrency cap (~6) means the
 *    last thumbs queue for seconds. We only fetch when the placeholder
 *    enters the viewport (root margin 200px = pre-fetch a viewport ahead).
 *
 * 2. **One automatic retry on failure.** `/thumb` re-renders from the
 *    source PDF on cache miss, and a single PyMuPDF/PIL hiccup used to
 *    leave the thumb permanently red (the user reported pages 6 and 9
 *    missing). One retry after a 600ms backoff catches the transient case;
 *    permanent failures still surface as the red error tile.
 */
function AuthImage({
  path,
  orgId,
  alt,
  className,
  style,
}: {
  path: string;
  orgId: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<boolean>(false);
  const [visible, setVisible] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const srcRef = useRef<string | null>(null);

  // IntersectionObserver gate — flip `visible=true` once and stay there.
  // Re-fetching on every viewport re-entry would defeat the browser's HTTP
  // cache (immutable response) and our blob URL is already mounted.
  useEffect(() => {
    if (visible) return;
    const node = containerRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") {
      // SSR / older browsers — fall back to immediate load.
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.disconnect();
            break;
          }
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    setError(false);
    setSrc(null);

    const load = async (attempt: number) => {
      try {
        const blob = await apiFetchBlob(path, { orgId });
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        // Revoke any prior URL on this consumer before swapping in the new one.
        if (srcRef.current) URL.revokeObjectURL(srcRef.current);
        srcRef.current = url;
        setSrc(url);
      } catch (err) {
        if (cancelled) return;
        if (attempt === 0) {
          // Single retry — covers the transient "PDF render hiccup" case
          // without hammering the backend on permanent failures.
          setTimeout(() => {
            if (!cancelled) load(attempt + 1);
          }, 600);
          return;
        }
        console.error(`Failed to load image ${path}:`, err);
        setError(true);
      }
    };

    load(0);

    return () => {
      cancelled = true;
      if (srcRef.current) {
        URL.revokeObjectURL(srcRef.current);
        srcRef.current = null;
      }
    };
  }, [path, orgId, visible]);

  if (error) {
    return (
      <div
        ref={containerRef}
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
        ref={containerRef}
        className={cn("bg-muted/40 animate-pulse rounded", className)}
      />
    );
  }

  return (
    <div ref={containerRef} className={cn("contents")}>
      <img src={src} alt={alt} className={className} style={style} />
    </div>
  );
}

interface PageViewerProps {
  orgId: string;
  packageId: string;
  stack: LoanStack;
  overrides: Map<string, LoanPageOverride>;
  moveOptions: MoveOption[];
  busyPageId: string | null;
  onMove: (page: LoanStackPage, target: string) => void;
  onUndo: (page: LoanStackPage) => void;
  /** Re-role a page within the current stack's doc type (drag onto a role
   *  pill). Promoting `continuation → first_page` splits the stack here. */
  onChangeRole: (page: LoanStackPage, role: LoanPageRole) => void;
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
  onChangeRole,
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
  // Per-section "show all" toggle. The picker shows the top N options per
  // section by default — clicking "Show all" expands that section. Cleared
  // when the picker closes so it always opens with the compact view.
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    () => new Set()
  );
  const SECTION_PAGE_SIZE = 5;
  const closePicker = () => {
    setPickerOpen(false);
    setPickerQuery("");
    setExpandedSections(new Set());
  };

  // The popover is rendered via a React portal into document.body so it
  // can't be clipped by any `overflow-hidden` ancestor (the previous inline
  // `absolute bottom-full` placement was getting hidden by the View pages
  // drawer's overflow box, which is what made the dropdown look "frozen" —
  // the backdrop covered the page but the popover itself was invisible).
  // We anchor the popover to the trigger's bounding rect on every open.
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [pickerRect, setPickerRect] = useState<{
    top: number;
    bottom: number;
    left: number;
    width: number;
  } | null>(null);

  const recomputePickerRect = () => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPickerRect({
      top: r.top,
      bottom: r.bottom,
      left: r.left,
      width: r.width,
    });
  };

  // Recompute on open + on viewport resize/scroll while open. useLayoutEffect
  // so the popover paints in the right place on its first frame.
  useLayoutEffect(() => {
    if (!pickerOpen) return;
    recomputePickerRect();
    const onScrollOrResize = () => recomputePickerRect();
    window.addEventListener("resize", onScrollOrResize);
    window.addEventListener("scroll", onScrollOrResize, true);
    return () => {
      window.removeEventListener("resize", onScrollOrResize);
      window.removeEventListener("scroll", onScrollOrResize, true);
    };
  }, [pickerOpen]);

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

  // Track which page is currently being dragged so we can reveal the
  // doc-type drop strip + dim non-draggable UI. Cleared on drop or cancel.
  const [draggingPageId, setDraggingPageId] = useState<string | null>(null);

  // Page-preview zoom. "fit" = scale-to-container (default — works on any
  // resolution), numeric values are explicit zoom factors. Reset to "fit"
  // whenever the active page changes so a fresh page always lands at a
  // sensible default instead of inheriting the previous page's zoom.
  const [zoom, setZoom] = useState<number | "fit">("fit");
  // Lightbox (full-page view) — separate zoom state from the inline preview
  // because the lightbox uses a much larger pixel anchor; sharing zoom would
  // make 100% in the inline view feel tiny in the lightbox and vice versa.
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxZoom, setLightboxZoom] = useState<number | "fit">("fit");
  useEffect(() => {
    setZoom("fit");
    setLightboxZoom("fit");
  }, [activePageId]);

  // Lightbox keyboard handling: ←/→ navigate within the stack, Esc closes,
  // 0 resets to fit. Body scroll is locked while open so the underlying
  // results page can't scroll behind the overlay.
  useEffect(() => {
    if (!lightboxOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLightboxOpen(false);
        return;
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const idx = visiblePages.findIndex((p) => p.page_id === activePageId);
        if (idx < 0) return;
        const next = e.key === "ArrowLeft" ? idx - 1 : idx + 1;
        if (next >= 0 && next < visiblePages.length) {
          setActivePageId(visiblePages[next].page_id);
        }
        e.preventDefault();
        return;
      }
      if (e.key === "0") setLightboxZoom("fit");
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [lightboxOpen, activePageId, visiblePages]);

  // Per-user layout preference. List = vertical thumbnail rail (metadata-
  // rich, easier triage). Filmstrip = horizontal scrolling thumbs above the
  // preview (denser, much shorter drag distance to drop targets — the
  // intended fast-move mode). Persisted in localStorage so the choice
  // survives navigation / reload. SSR-safe via the lazy initializer.
  const [viewMode, setViewMode] = useState<"list" | "strip">(() => {
    if (typeof window === "undefined") return "list";
    try {
      return window.localStorage.getItem("lo-pageviewer-mode") === "strip"
        ? "strip"
        : "list";
    } catch {
      return "list";
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem("lo-pageviewer-mode", viewMode);
    } catch {
      // localStorage unavailable (private mode, quota, etc.) — silently
      // ignore; the in-memory state still works for this session.
    }
  }, [viewMode]);

  // Auto-scroll the active thumb into view in filmstrip mode. Without this
  // the user can click a thumb on the far edge and lose track of selection
  // when navigating with arrow keys / programmatic moves.
  const activeThumbRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (viewMode !== "strip") return;
    activeThumbRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [activePageId, viewMode]);

  // PointerSensor with a small activation distance so simple clicks on a
  // thumb (to switch the active page) still fire normally — drag only
  // engages once the cursor moves a few pixels.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const handleDragStart = (event: DragStartEvent) => {
    const pageId = event.active.data.current?.pageId as string | undefined;
    if (pageId) setDraggingPageId(pageId);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const pageId = event.active.data.current?.pageId as string | undefined;
    const overData = event.over?.data.current as
      | { kind: "doctype"; docType: string }
      | { kind: "role"; role: LoanPageRole }
      | undefined;
    setDraggingPageId(null);
    if (!pageId || !overData) return;
    const page = pages.find((p) => p.page_id === pageId);
    if (!page) return;

    if (overData.kind === "doctype") {
      // No-op: dropping a page onto its current effective doc type. The
      // backend would reject this with 400; short-circuit here so the user
      // doesn't see an error toast for "I dropped it where it already was."
      const effectiveDocType =
        overrides.get(pageId)?.assigned_doc_type ?? stack.doc_type;
      if (overData.docType === effectiveDocType) return;
      onMove(page, overData.docType);
      return;
    }

    // Role drop: keep the page in the same stack's doc_type but flip its
    // role. No-op if the effective role already matches.
    const effectiveRole =
      overrides.get(pageId)?.page_role_override ??
      (page.page_role as LoanPageRole | null);
    if (overData.role === effectiveRole) return;
    onChangeRole(page, overData.role);
  };

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
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDraggingPageId(null)}
    >
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
        <div className="flex items-center gap-2">
          {/* View-mode toggle. List is the existing layout; Filmstrip is
              the horizontal-row layout for fast scanning + short drag
              paths. Persisted in localStorage. */}
          <div
            className="inline-flex items-center rounded-md border border-border/60 bg-background overflow-hidden"
            role="group"
            aria-label="Page viewer layout"
          >
            <button
              type="button"
              onClick={() => setViewMode("list")}
              aria-pressed={viewMode === "list"}
              aria-label="List view"
              title="List view — vertical thumbnails with metadata"
              className={cn(
                "px-2 py-1 transition-colors",
                viewMode === "list"
                  ? "bg-amber-50 text-amber-900"
                  : "text-muted-foreground hover:bg-muted/40"
              )}
              data-testid="page-view-mode-list"
            >
              <LayoutList className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setViewMode("strip")}
              aria-pressed={viewMode === "strip"}
              aria-label="Filmstrip view"
              title="Filmstrip view — horizontal thumbnails for fast moves"
              className={cn(
                "px-2 py-1 transition-colors border-l border-border/60",
                viewMode === "strip"
                  ? "bg-amber-50 text-amber-900"
                  : "text-muted-foreground hover:bg-muted/40"
              )}
              data-testid="page-view-mode-strip"
            >
              <GalleryHorizontal className="h-3.5 w-3.5" />
            </button>
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
      </div>


      {/* Filmstrip — horizontal scrolling thumb row rendered ABOVE the
          preview in strip mode. Card-style thumbs (image-on-top, label-
          below) at ~80px wide so 12-15 fit in view at 1280px. Drag path
          flows naturally downward into the preview / drop overlay. */}
      {viewMode === "strip" && (
        <div className="mb-3 rounded-md border border-border/60 bg-background overflow-hidden">
          <div className="px-3 py-1.5 bg-muted/40 border-b border-border/60 flex items-center justify-between">
            <span className="text-[9px] font-mono tracking-[0.2em] text-muted-foreground uppercase">
              Pages
            </span>
            <span className="text-[9px] font-mono tabular-nums text-muted-foreground">
              {visiblePages.length}/{pages.length}
            </span>
          </div>
          <div
            className="flex gap-2 overflow-x-auto p-2"
            data-testid="filmstrip"
          >
            {visiblePages.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-muted-foreground italic">
                No pages match.
              </div>
            ) : (
              visiblePages.map((pg) => {
                const o = overrides.get(pg.page_id);
                const isActive = activePage?.page_id === pg.page_id;
                return (
                  <FilmstripThumb
                    key={pg.page_id}
                    orgId={orgId}
                    packageId={packageId}
                    pg={pg}
                    isActive={isActive}
                    override={o}
                    isDraggingThis={draggingPageId === pg.page_id}
                    activeRef={isActive ? activeThumbRef : undefined}
                    onClick={() => {
                      setActivePageId(pg.page_id);
                      closePicker();
                    }}
                  />
                );
              })
            )}
          </div>
        </div>
      )}

      <div
        className="grid bg-background border border-border/60 rounded-md overflow-hidden"
        style={{
          gridTemplateColumns: viewMode === "strip" ? "1fr" : "180px 1fr",
        }}
      >
        {/* Left: thumbnail rail — only shown in list mode */}
        {viewMode === "list" && (
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
                    <DraggableThumb
                      key={pg.page_id}
                      orgId={orgId}
                      packageId={packageId}
                      pg={pg}
                      isActive={isActive}
                      override={o}
                      isDraggingThis={draggingPageId === pg.page_id}
                      onClick={() => {
                        setActivePageId(pg.page_id);
                        closePicker();
                      }}
                    />
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* Right (or full-width in strip mode): preview surface + action bar */}
        <div className="flex flex-col">
          {/* Preview toolbar — three slots: page identity (left), zoom +
              full-view (center/right cluster), current doc-type (right).
              `flex-wrap` keeps the row from clipping on narrow widths.
              Zoom controls were previously floating at bottom-right of the
              preview surface; relocating them here removes their overlap
              with the page image and with the "Current:" label. */}
          <div className="px-4 py-2 bg-muted/40 border-b border-border/60 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
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
              {/* PDF vs Image badge — content_signal comes from the ingest
                  stage's heuristic over PyMuPDF text extraction. Lets a
                  reviewer tell at a glance whether the page is a native
                  digital PDF (selectable text) or a scanned image (OCR
                  required for any field extraction). */}
              {activePage?.content_signal && (
                <span
                  className={cn(
                    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm font-mono text-[9px] uppercase tracking-[0.1em] border shrink-0",
                    activePage.content_signal === "text"
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : activePage.content_signal === "image"
                      ? "bg-blue-50 text-blue-700 border-blue-200"
                      : "bg-muted text-muted-foreground border-border"
                  )}
                  title={
                    activePage.content_signal === "text"
                      ? "Native PDF — text is embedded and selectable"
                      : activePage.content_signal === "image"
                      ? "Scanned image — no embedded text (OCR-only)"
                      : "Blank page — no extractable content"
                  }
                  data-testid="page-content-signal"
                >
                  {activePage.content_signal === "text"
                    ? "PDF"
                    : activePage.content_signal === "image"
                    ? "Image"
                    : "Blank"}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {activePage && (
                <>
                  <ZoomControls zoom={zoom} onChange={setZoom} />
                  <button
                    type="button"
                    onClick={() => setLightboxOpen(true)}
                    className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-border bg-card hover:bg-muted/60 transition-colors text-[10px] font-mono uppercase tracking-[0.1em]"
                    aria-label="Open full-page view"
                    title="Open full-page view"
                    data-testid="page-fullview-open"
                  >
                    <Expand className="h-3.5 w-3.5" />
                    Full view
                  </button>
                </>
              )}
              <div className="font-mono text-[10px] text-muted-foreground">
                Current:{" "}
                <span className="text-foreground font-medium">
                  {currentLabel}
                </span>
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
          </div>

          {/* Real PDF page preview — rendered on demand via PyMuPDF.
              Wrapper is `relative` so the floating zoom controls anchor to
              its bottom-right corner; the inner div is the actual scroll
              container (overflow-auto) for zoomed pages. Container height
              is viewport-relative so the preview adapts to screen size,
              and "fit" mode scales the image to fully fit it. */}
          <div
            className="flex-1 relative bg-amber-50/30"
            style={{
              // A4-sized viewer: A4 portrait is 210×297mm (aspect ~1.414).
              // For a typical viewer width of ~600–780px the matching height
              // is ~850–1100px. clamp(640, 88vh, 1100) sizes the surface so
              // a full A4/letter page renders at-scale in fit mode without
              // scroll on 1080p+ monitors. The 640px floor keeps the viewer
              // usable on 720p laptops (still ≥1 full page visible).
              height: "clamp(640px, 88vh, 1100px)",
            }}
            data-testid="page-preview-container"
          >
            <div className="absolute inset-0 overflow-auto">
              {activePage ? (
                zoom === "fit" ? (
                  // Fit mode: page card is forced to A4-ish portrait aspect
                  // and stretched to fill the viewer height (`h-full`). The
                  // image inside uses `object-contain` so it scales up to
                  // fill the card while preserving its native aspect — this
                  // is what makes a full A4 page actually show at A4 size
                  // instead of rendering at the source's intrinsic ~612×792
                  // pixels (which used to leave the page tiny inside the
                  // bigger viewer).
                  <div className="absolute inset-0 flex items-center justify-center p-4">
                    <div
                      className="bg-card border border-border shadow-sm rounded overflow-hidden h-full max-w-full flex items-center justify-center"
                      style={{ aspectRatio: "8.5 / 11" }}
                    >
                      <AuthImage
                        key={activePage.page_id}
                        path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${activePage.page_id}/image`}
                        orgId={orgId}
                        alt={`Page ${activePage.page_number}`}
                        className="block w-full h-full object-contain"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="p-4 inline-block">
                    <div className="bg-card border border-border shadow-sm rounded overflow-hidden">
                      <AuthImage
                        key={activePage.page_id}
                        path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${activePage.page_id}/image`}
                        orgId={orgId}
                        alt={`Page ${activePage.page_number}`}
                        className="block w-auto"
                        // 1050px ≈ "100%" anchor — sized to the new A4
                        // viewer (clamp(640, 88vh, 1100)) so 100% matches a
                        // full A4 page at native size. 200% ≈ 2100px, 50% ≈ 525px.
                        style={{ height: `${1050 * zoom}px` }}
                      />
                    </div>
                  </div>
                )
              ) : (
                <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground italic">
                  Select a page from the left.
                </div>
              )}
            </div>

            {/* Drop targets overlay — only rendered while a thumb is being
                dragged. Positioned `absolute inset-0` over the preview so
                the layout never reflows (the previous inline placements
                shifted the source thumbnail out from under the cursor on
                drag start). The left thumbnail column stays anchored, so
                the user can drag straight across. Two groups: doc-type
                targets + role targets; `handleDragEnd` branches on `kind`. */}
            {draggingPageId && (
              <div
                className="absolute inset-0 z-20 bg-amber-50/95 backdrop-blur-sm overflow-y-auto p-4 space-y-4"
                data-testid="doctype-drop-strip"
              >
                {moveOptions.length > 0 && (
                  <div>
                    <div className="font-mono text-[9px] tracking-[0.15em] text-amber-900 uppercase mb-2">
                      Drop on a doc type to move
                    </div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                      {moveOptions.map((dt) => (
                        <DocTypeDropZone
                          key={dt.key}
                          docType={dt.key}
                          label={dt.label}
                          isActive={!!draggingPageId}
                        />
                      ))}
                    </div>
                  </div>
                )}
                <div data-testid="role-drop-strip">
                  <div className="font-mono text-[9px] tracking-[0.15em] text-amber-900 uppercase mb-2">
                    Or set page role within {currentLabel}
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {ROLE_OPTIONS.map((role) => (
                      <RoleDropZone
                        key={role}
                        role={role}
                        isActive={!!draggingPageId}
                      />
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>


          {/* Move action bar */}
          {activePage && (() => {
            const q = pickerQuery.trim().toLowerCase();
            // Filter by label OR description so users can find a type by
            // searching for "loan application" → URLA_1003, etc.
            const filtered = q
              ? moveOptions.filter(
                  (opt) =>
                    opt.label.toLowerCase().includes(q) ||
                    (opt.description?.toLowerCase().includes(q) ?? false) ||
                    opt.key.toLowerCase().includes(q)
                )
              : moveOptions;
            // Catch-all (Others) is surfaced as a sticky footer button so
            // demoting a misclassified page is always one click away — no
            // scrolling required. We strip it out of the main list.
            const catchAllOption = moveOptions.find(
              (o) => o.group === "catch-all"
            );
            // Bucket by group for sectioned rendering. Order matters — the
            // user reads top-to-bottom and we want the package's configured
            // list to come first.
            const grouped = {
              configured: filtered.filter((o) => o.group === "configured"),
              detected: filtered.filter((o) => o.group === "detected"),
              suggested: filtered.filter((o) => o.group === "suggested"),
              "catch-all": filtered.filter((o) => o.group === "catch-all"),
            };
            const SECTION_LABELS: Record<MoveOption["group"], string> = {
              configured: "Expected for this package",
              detected: "Other detected types",
              suggested: "Other common types",
              "catch-all": "Catch-all",
            };
            const SECTION_ORDER: MoveOption["group"][] = [
              "configured",
              "detected",
              "suggested",
            ];

            const activeDraftOption = activeDraft
              ? moveOptions.find((o) => o.key === activeDraft)
              : null;
            const activeDraftLabel =
              activeDraftOption?.label ??
              (activeDraft
                ? (LOAN_DOC_TYPE_LABELS[activeDraft] ?? activeDraft)
                : "");
            const triggerDisabled =
              !!activeOverride ||
              busyPageId === activePage.page_id ||
              moveOptions.length === 0;
            return (
            <div className="px-4 py-3 border-t border-border/60 bg-card flex items-center gap-3">
              <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase shrink-0">
                Move to
              </span>
              <div className="flex-1">
                <button
                  ref={triggerRef}
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
                {pickerOpen && !activeOverride && pickerRect && typeof document !== "undefined" && createPortal(
                  <>
                    {/* Click-outside backdrop closes the popover. Portaled to
                        body so it sits above any ancestor overflow boxes. */}
                    <div
                      className="fixed inset-0 z-[90]"
                      onClick={closePicker}
                      aria-hidden
                    />
                    {/* Popover positioned via fixed coords anchored to the
                        trigger's bounding rect. Vertical placement is chosen
                        per-render: prefer ABOVE the trigger so the inline
                        action bar isn't covered, but fall back to BELOW when
                        the trigger is too close to the top of the viewport. */}
                    {(() => {
                      const VIEWPORT_GUTTER = 8;
                      const TRIGGER_GAP = 6;
                      const popoverWidth = Math.max(pickerRect.width, 360);
                      // Clamp horizontally inside the viewport.
                      const left = Math.max(
                        VIEWPORT_GUTTER,
                        Math.min(
                          pickerRect.left,
                          window.innerWidth - popoverWidth - VIEWPORT_GUTTER
                        )
                      );
                      // Choose the side with more room → clamp maxHeight to
                      // that side's actual space so the popover never
                      // overflows the viewport (which used to truncate the
                      // top rows when placed above).
                      const spaceAbove = pickerRect.top - VIEWPORT_GUTTER - TRIGGER_GAP;
                      const spaceBelow =
                        window.innerHeight -
                        pickerRect.bottom -
                        VIEWPORT_GUTTER -
                        TRIGGER_GAP;
                      const placeAbove = spaceAbove > spaceBelow;
                      const availableSpace = Math.max(
                        180,
                        placeAbove ? spaceAbove : spaceBelow
                      );
                      const popoverMaxHeight = Math.min(420, availableSpace);
                      const style: React.CSSProperties = placeAbove
                        ? {
                            position: "fixed",
                            left,
                            bottom:
                              window.innerHeight -
                              pickerRect.top +
                              TRIGGER_GAP,
                            width: popoverWidth,
                            maxHeight: popoverMaxHeight,
                          }
                        : {
                            position: "fixed",
                            left,
                            top: pickerRect.bottom + TRIGGER_GAP,
                            width: popoverWidth,
                            maxHeight: popoverMaxHeight,
                          };
                      return (
                    <div
                      className="z-[100] bg-popover border border-border rounded-md shadow-xl flex flex-col"
                      style={style}
                      role="listbox"
                    >
                      <div className="p-2 border-b border-border/60">
                        <input
                          // eslint-disable-next-line jsx-a11y/no-autofocus -- popover input: focusing search box on open is expected UX
                          autoFocus
                          value={pickerQuery}
                          onChange={(e) => setPickerQuery(e.target.value)}
                          placeholder="Search by name or description…"
                          className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                          aria-label="Search doc types"
                        />
                      </div>
                      <div className="overflow-y-auto flex-1 min-h-0">
                        {filtered.length === 0 ? (
                          <div className="px-3 py-6 text-[11px] text-muted-foreground italic text-center">
                            No doc types match &ldquo;{pickerQuery}&rdquo;.
                          </div>
                        ) : (
                          SECTION_ORDER.map((group) => {
                            const items = grouped[group];
                            if (items.length === 0) return null;
                            // Search bypasses the per-section cap — when the
                            // user is filtering, all matches should be
                            // visible (search IS the filter mechanism).
                            const isExpanded =
                              !!q || expandedSections.has(group);
                            const visible = isExpanded
                              ? items
                              : items.slice(0, SECTION_PAGE_SIZE);
                            const hiddenCount = items.length - visible.length;
                            return (
                              <div key={group}>
                                <div className="px-3 py-1.5 bg-muted/30 border-b border-border/40 sticky top-0 z-10 flex items-center justify-between gap-2">
                                  <div className="flex items-baseline gap-1.5">
                                    <span className="font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase">
                                      {SECTION_LABELS[group]}
                                    </span>
                                    <span className="font-mono text-[9px] tabular-nums text-muted-foreground/70">
                                      {isExpanded
                                        ? items.length
                                        : `${visible.length} / ${items.length}`}
                                    </span>
                                  </div>
                                </div>
                                {visible.map((opt) => {
                                  const selected = activeDraft === opt.key;
                                  return (
                                    <button
                                      key={opt.key}
                                      type="button"
                                      role="option"
                                      aria-selected={selected}
                                      onClick={() => {
                                        setDraftByPage((prev) => ({
                                          ...prev,
                                          [activePage.page_id]: opt.key,
                                        }));
                                        closePicker();
                                      }}
                                      className={cn(
                                        "w-full text-left px-3 py-2 hover:bg-muted/60 transition-colors flex items-start gap-2 border-b border-border/30 last:border-b-0",
                                        selected && "bg-amber-50/70"
                                      )}
                                      data-testid={`move-option-${opt.key}`}
                                    >
                                      <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                          <span
                                            className={cn(
                                              "text-xs truncate",
                                              selected
                                                ? "font-semibold text-foreground"
                                                : "font-medium text-foreground"
                                            )}
                                          >
                                            {opt.label}
                                          </span>
                                          {opt.required && (
                                            <span className="font-mono text-[8px] tracking-[0.1em] uppercase text-amber-800 bg-amber-100 ring-1 ring-amber-200 rounded px-1.5 py-0.5">
                                              Required
                                            </span>
                                          )}
                                        </div>
                                        {opt.description && (
                                          <div className="text-[10px] text-muted-foreground mt-0.5 truncate">
                                            {opt.description}
                                          </div>
                                        )}
                                      </div>
                                      {selected && (
                                        <Check className="h-3.5 w-3.5 text-amber-700 shrink-0 mt-0.5" />
                                      )}
                                    </button>
                                  );
                                })}
                                {/* Per-section "Show all / Show less" — only
                                    when not searching and the section has
                                    more than the page size. Sits inline at
                                    the bottom of each section so the user
                                    expands exactly what they need. */}
                                {!q && (hiddenCount > 0 || isExpanded) && (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setExpandedSections((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(group)) next.delete(group);
                                        else next.add(group);
                                        return next;
                                      });
                                    }}
                                    className="w-full text-left px-3 py-2 text-[11px] font-medium text-amber-800 hover:bg-amber-50 transition-colors border-b border-border/30 flex items-center gap-1.5"
                                    data-testid={`move-section-toggle-${group}`}
                                  >
                                    <ChevronDown
                                      className={cn(
                                        "h-3 w-3 transition-transform",
                                        isExpanded && "rotate-180"
                                      )}
                                    />
                                    {isExpanded
                                      ? "Show less"
                                      : `Show ${hiddenCount} more`}
                                  </button>
                                )}
                              </div>
                            );
                          })
                        )}
                      </div>
                      {/* Sticky catch-all footer — promotes the "Others"
                          option out of the scrollable list so demoting a
                          misclassified page is always one click away,
                          regardless of how the user has expanded sections
                          or what they're searching for. */}
                      {catchAllOption && (
                        <button
                          type="button"
                          role="option"
                          aria-selected={activeDraft === catchAllOption.key}
                          onClick={() => {
                            setDraftByPage((prev) => ({
                              ...prev,
                              [activePage.page_id]: catchAllOption.key,
                            }));
                            closePicker();
                          }}
                          className={cn(
                            "border-t border-border/60 bg-muted/30 px-3 py-2.5 text-left hover:bg-muted/60 transition-colors flex items-start gap-2",
                            activeDraft === catchAllOption.key &&
                              "bg-amber-50/70"
                          )}
                          data-testid={`move-option-${catchAllOption.key}`}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-xs font-medium text-foreground">
                                Move to Others
                              </span>
                              <span className="font-mono text-[8px] tracking-[0.1em] uppercase text-muted-foreground bg-background ring-1 ring-border rounded px-1.5 py-0.5">
                                Catch-all
                              </span>
                            </div>
                            <div className="text-[10px] text-muted-foreground mt-0.5">
                              Pages that don&rsquo;t fit any expected document
                              type
                            </div>
                          </div>
                          {activeDraft === catchAllOption.key && (
                            <Check className="h-3.5 w-3.5 text-amber-700 shrink-0 mt-0.5" />
                          )}
                        </button>
                      )}
                      <div className="px-3 py-1.5 border-t border-border/60 bg-muted/40 font-mono text-[9px] tracking-[0.15em] text-muted-foreground uppercase tabular-nums flex items-center justify-between">
                        <span>
                          {q
                            ? `${filtered.filter((o) => o.group !== "catch-all").length} match${filtered.filter((o) => o.group !== "catch-all").length === 1 ? "" : "es"}`
                            : `${moveOptions.filter((o) => o.group !== "catch-all").length} doc types`}
                        </span>
                        <span>Esc to close</span>
                      </div>
                    </div>
                      );
                    })()}
                  </>,
                  document.body
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
        Drag a thumbnail onto a doc type to move it, or onto a role to
        re-role it within this stack (promoting to <em>first page</em>{" "}
        splits the stack here).
      </div>
    </div>
    {/* Full-page lightbox — opens when the user hits "Full view" or presses
        Enter on the button. Renders the same `/image` endpoint at viewport
        size with its own zoom + page navigation. Backdrop click and Escape
        close; ←/→ paginate within the visible (filtered) pages. */}
    {lightboxOpen && activePage && (() => {
      const idx = visiblePages.findIndex((p) => p.page_id === activePageId);
      const prev = idx > 0 ? visiblePages[idx - 1] : null;
      const next =
        idx >= 0 && idx < visiblePages.length - 1
          ? visiblePages[idx + 1]
          : null;
      const positionLabel =
        idx >= 0 ? `${idx + 1} of ${visiblePages.length}` : null;
      return (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex flex-col"
          role="dialog"
          aria-modal="true"
          aria-label={`Page ${activePage.page_number} full view`}
          onClick={(e) => {
            if (e.target === e.currentTarget) setLightboxOpen(false);
          }}
          data-testid="page-lightbox"
        >
          {/* Header — page identity + zoom + close. White on dark to read
              against the backdrop image area. */}
          <div
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-3 bg-card/95 backdrop-blur border-b border-border/40 shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-baseline gap-4 min-w-0">
              <div className="text-base font-medium">
                Page {activePage.page_number}
                {positionLabel && (
                  <span className="text-muted-foreground text-xs font-normal ml-2">
                    ({positionLabel} in stack)
                  </span>
                )}
              </div>
              {activePage.page_role && (
                <div className="font-mono text-[10px] tracking-[0.15em] text-muted-foreground uppercase">
                  {activePage.page_role.replace(/_/g, " ")}
                </div>
              )}
              <div className="font-mono text-[10px] text-muted-foreground">
                {currentLabel}
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
            <div className="flex items-center gap-2">
              <ZoomControls zoom={lightboxZoom} onChange={setLightboxZoom} />
              <button
                type="button"
                onClick={() => setLightboxOpen(false)}
                className="p-1.5 rounded-md border border-border bg-card hover:bg-muted/60 transition-colors"
                aria-label="Close full view (Esc)"
                title="Close (Esc)"
                data-testid="page-lightbox-close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Image surface — fills available height. Scrollable when zoomed
              past "fit". Clicking the dim margin (not the image) closes. */}
          <div
            className="flex-1 relative overflow-hidden"
            onClick={(e) => {
              if (e.target === e.currentTarget) setLightboxOpen(false);
            }}
          >
            <div className="absolute inset-0 overflow-auto">
              {lightboxZoom === "fit" ? (
                // Same fit-fix as the inline viewer: use a portrait-aspect
                // wrapper at h-full so the image scales up via object-contain
                // instead of rendering at its intrinsic source resolution.
                <div className="absolute inset-0 flex items-center justify-center p-6">
                  <div
                    className="h-full max-w-full shadow-2xl rounded overflow-hidden bg-white flex items-center justify-center"
                    style={{ aspectRatio: "8.5 / 11" }}
                  >
                    <AuthImage
                      key={`lightbox-${activePage.page_id}`}
                      path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${activePage.page_id}/image`}
                      orgId={orgId}
                      alt={`Page ${activePage.page_number}`}
                      className="block w-full h-full object-contain"
                    />
                  </div>
                </div>
              ) : (
                <div className="p-6 inline-block">
                  <AuthImage
                    key={`lightbox-${activePage.page_id}`}
                    path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${activePage.page_id}/image`}
                    orgId={orgId}
                    alt={`Page ${activePage.page_number}`}
                    className="block w-auto shadow-2xl rounded"
                    // Larger anchor than the inline preview (1100 vs 800):
                    // a US-Letter render at the lightbox's bigger surface
                    // wants more pixels at "100%" before the user has to
                    // start zooming further.
                    style={{ height: `${1100 * (lightboxZoom as number)}px` }}
                  />
                </div>
              )}
            </div>

            {prev && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setActivePageId(prev.page_id);
                }}
                className="absolute left-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-card/95 border border-border hover:bg-muted/60 shadow-lg transition-colors"
                aria-label="Previous page (Left arrow)"
                title="Previous page (←)"
                data-testid="page-lightbox-prev"
              >
                <ChevronLeft className="h-5 w-5" />
              </button>
            )}
            {next && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setActivePageId(next.page_id);
                }}
                className="absolute right-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-card/95 border border-border hover:bg-muted/60 shadow-lg transition-colors"
                aria-label="Next page (Right arrow)"
                title="Next page (→)"
                data-testid="page-lightbox-next"
              >
                <ChevronRight className="h-5 w-5" />
              </button>
            )}
          </div>

          {/* Footer hint — keyboard shortcuts. Subtle, non-blocking. */}
          <div
            className="px-6 py-2 bg-card/95 backdrop-blur border-t border-border/40 text-[10px] font-mono tracking-[0.1em] uppercase text-muted-foreground shrink-0 flex items-center gap-4"
            onClick={(e) => e.stopPropagation()}
          >
            <span>← / → navigate</span>
            <span>0 fit</span>
            <span>Esc close</span>
          </div>
        </div>
      );
    })()}
    {/* Floating drag preview — without this the source thumb just dims
        in place, which reads as "drag isn't working" to most users.
        We portal a small chip showing the page number being moved. */}
    <DragOverlay dropAnimation={null}>
      {draggingPageId ? (
        <div className="rounded-md border border-amber-400 bg-amber-100 px-3 py-1.5 shadow-lg text-xs font-mono tabular-nums text-amber-900 cursor-grabbing">
          Moving page{" "}
          {pages.find((p) => p.page_id === draggingPageId)?.page_number ?? "?"}
        </div>
      ) : null}
    </DragOverlay>
    </DndContext>
  );
}

/** Discrete zoom levels for the page preview. Picked to mirror typical
 *  PDF-viewer presets (50/75/100/125/150/200/300%) without being overwhelming. */
const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3] as const;

function ZoomControls({
  zoom,
  onChange,
}: {
  zoom: number | "fit";
  onChange: (z: number | "fit") => void;
}) {
  const stepIndex =
    typeof zoom === "number" ? ZOOM_STEPS.indexOf(zoom as (typeof ZOOM_STEPS)[number]) : -1;
  const canZoomIn =
    zoom === "fit" || (stepIndex >= 0 && stepIndex < ZOOM_STEPS.length - 1);
  const canZoomOut = zoom !== "fit";

  const zoomIn = () => {
    if (zoom === "fit") return onChange(1);
    if (stepIndex >= 0 && stepIndex < ZOOM_STEPS.length - 1) {
      onChange(ZOOM_STEPS[stepIndex + 1]);
    }
  };
  const zoomOut = () => {
    if (zoom === "fit") return;
    if (stepIndex <= 0) return onChange("fit");
    onChange(ZOOM_STEPS[stepIndex - 1]);
  };

  const label = zoom === "fit" ? "Fit" : `${Math.round((zoom as number) * 100)}%`;

  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-card/95 backdrop-blur shadow-sm"
      data-testid="page-zoom-controls"
    >
      <button
        type="button"
        onClick={zoomOut}
        disabled={!canZoomOut}
        className="p-1.5 rounded-l-md hover:bg-muted/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        aria-label="Zoom out"
        data-testid="page-zoom-out"
      >
        <ZoomOut className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onClick={() => onChange("fit")}
        className={cn(
          "px-2 py-1 text-[10px] font-mono tabular-nums hover:bg-muted/60 transition-colors min-w-[44px] text-center",
          zoom === "fit" && "bg-amber-50 text-amber-900"
        )}
        aria-label="Fit page to screen"
        data-testid="page-zoom-fit"
      >
        {label}
      </button>
      <button
        type="button"
        onClick={() => onChange(1)}
        className="p-1.5 hover:bg-muted/60 transition-colors"
        aria-label="Reset zoom to 100%"
        data-testid="page-zoom-reset"
      >
        <Maximize2 className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onClick={zoomIn}
        disabled={!canZoomIn}
        className="p-1.5 rounded-r-md hover:bg-muted/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        aria-label="Zoom in"
        data-testid="page-zoom-in"
      >
        <ZoomIn className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

/**
 * Draggable thumbnail rendering the real `/thumb` image from the backend.
 * The button still functions as a click target to switch the active page —
 * dnd-kit's PointerSensor with `distance: 5` keeps simple clicks intact.
 */
function DraggableThumb({
  orgId,
  packageId,
  pg,
  isActive,
  override,
  isDraggingThis,
  onClick,
}: {
  orgId: string;
  packageId: string;
  pg: LoanStackPage;
  isActive: boolean;
  override: LoanPageOverride | undefined;
  isDraggingThis: boolean;
  onClick: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `lo-page-${pg.page_id}`,
    data: { pageId: pg.page_id, pageNumber: pg.page_number },
  });

  return (
    <button
      ref={setNodeRef}
      type="button"
      onClick={onClick}
      {...listeners}
      {...attributes}
      className={cn(
        "w-full flex items-center gap-2 px-2 py-2 text-left border-b border-border/60 transition-colors border-l-2 cursor-grab active:cursor-grabbing",
        isActive
          ? "bg-amber-50/70 border-l-amber-500"
          : "hover:bg-muted/40 border-l-transparent",
        (isDragging || isDraggingThis) && "opacity-40"
      )}
      data-testid={`thumb-${pg.page_number}`}
    >
      <div
        className={cn(
          "w-9 h-12 shrink-0 border rounded overflow-hidden",
          override
            ? "bg-amber-50 border-amber-300"
            : "bg-muted/40 border-border/60"
        )}
      >
        <AuthImage
          path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${pg.page_id}/thumb`}
          orgId={orgId}
          alt={`Page ${pg.page_number} thumbnail`}
          className="w-full h-full object-cover"
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
        {override && (
          <div className="font-mono text-[9px] text-amber-700 truncate mt-0.5">
            →{" "}
            {LOAN_DOC_TYPE_LABELS[override.assigned_doc_type] ??
              override.assigned_doc_type}
          </div>
        )}
      </div>
    </button>
  );
}

/**
 * Filmstrip-mode thumbnail — card layout (image on top, label below) sized
 * for horizontal scrolling. Same drag mechanics as `DraggableThumb`; only
 * the visual presentation differs. The active variant accepts a ref so the
 * parent can call `scrollIntoView` to keep the active page visible when
 * the strip overflows horizontally.
 */
function FilmstripThumb({
  orgId,
  packageId,
  pg,
  isActive,
  override,
  isDraggingThis,
  activeRef,
  onClick,
}: {
  orgId: string;
  packageId: string;
  pg: LoanStackPage;
  isActive: boolean;
  override: LoanPageOverride | undefined;
  isDraggingThis: boolean;
  activeRef?: React.MutableRefObject<HTMLButtonElement | null>;
  onClick: () => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `lo-page-${pg.page_id}`,
    data: { pageId: pg.page_id, pageNumber: pg.page_number },
  });

  // Compose dnd-kit's setNodeRef with the parent-supplied activeRef so the
  // active thumb can both participate in drag-and-drop AND be programmatic-
  // ally scrolled into view.
  const setRefs = (node: HTMLButtonElement | null) => {
    setNodeRef(node);
    if (activeRef) activeRef.current = node;
  };

  return (
    <button
      ref={setRefs}
      type="button"
      onClick={onClick}
      {...listeners}
      {...attributes}
      className={cn(
        "shrink-0 w-20 flex flex-col items-stretch gap-1 p-1 rounded-md border-2 transition-colors cursor-grab active:cursor-grabbing",
        isActive
          ? "border-amber-500 bg-amber-50/70"
          : "border-transparent hover:bg-muted/40",
        (isDragging || isDraggingThis) && "opacity-40"
      )}
      data-testid={`filmstrip-thumb-${pg.page_number}`}
    >
      <div
        className={cn(
          "w-full aspect-[3/4] border rounded overflow-hidden",
          override
            ? "bg-amber-50 border-amber-300"
            : "bg-muted/40 border-border/60"
        )}
      >
        <AuthImage
          path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${pg.page_id}/thumb`}
          orgId={orgId}
          alt={`Page ${pg.page_number} thumbnail`}
          className="w-full h-full object-cover"
        />
      </div>
      <div className="font-mono text-[10px] tabular-nums text-center">
        p. {pg.page_number}
      </div>
      {pg.page_role && (
        <div className="font-mono text-[8px] uppercase tracking-[0.05em] text-muted-foreground text-center truncate">
          {pg.page_role.replace(/_/g, " ")}
        </div>
      )}
      {override && (
        <div className="font-mono text-[8px] text-amber-700 text-center truncate">
          →{" "}
          {LOAN_DOC_TYPE_LABELS[override.assigned_doc_type] ??
            override.assigned_doc_type}
        </div>
      )}
    </button>
  );
}

/** Page roles surfaced as drop targets in the role drop strip. Order matches
 *  the natural reading order of a multi-page document. */
const ROLE_OPTIONS = [
  "first_page",
  "continuation",
  "last_page",
  "signature_page",
] as const satisfies readonly LoanPageRole[];

const ROLE_LABELS: Record<LoanPageRole, string> = {
  first_page: "First Page",
  continuation: "Continuation",
  last_page: "Last Page",
  signature_page: "Signature",
};

/**
 * One drop target for a page role. Drops here re-role the page within the
 * current stack's doc type (i.e. flip `page_role_override` only). On drop
 * the parent's `handleDragEnd` reads `kind: "role"` from `data.current` and
 * dispatches `onChangeRole`.
 */
function RoleDropZone({
  role,
  isActive,
}: {
  role: LoanPageRole;
  isActive: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `lo-role-${role}`,
    data: { kind: "role", role },
  });
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "rounded-md border-2 border-dashed px-3 py-2 text-xs font-medium transition-colors text-center",
        isOver
          ? "border-sky-500 bg-sky-100 text-sky-900"
          : isActive
            ? "border-sky-300/70 bg-sky-50 text-sky-800"
            : "border-border/60 bg-muted/30 text-muted-foreground"
      )}
      data-testid={`role-drop-${role}`}
    >
      {ROLE_LABELS[role]}
    </div>
  );
}

/**
 * One drop target for a doc type. Highlights when a thumb is being dragged
 * over it; on drop the parent's `handleDragEnd` reads the `docType` from
 * `data.current` and dispatches an override.
 */
function DocTypeDropZone({
  docType,
  label: labelOverride,
  isActive,
}: {
  docType: string;
  /** Optional pretty label from the rich `MoveOption`. Falls back to the
   *  legacy LOAN_DOC_TYPE_LABELS map → raw key chain so existing callers
   *  that don't pass this prop still render correctly. */
  label?: string;
  isActive: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `lo-doctype-${docType}`,
    data: { kind: "doctype", docType },
  });
  const label = labelOverride ?? LOAN_DOC_TYPE_LABELS[docType] ?? docType;
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "rounded-md border-2 border-dashed px-3 py-2 text-xs font-medium transition-colors text-center",
        isOver
          ? "border-amber-500 bg-amber-100 text-amber-900"
          : isActive
            ? "border-amber-300/70 bg-amber-50 text-amber-800"
            : "border-border/60 bg-muted/30 text-muted-foreground"
      )}
      data-testid={`doctype-drop-${docType}`}
    >
      {label}
    </div>
  );
}
