"use client";

/**
 * 3-column extraction review workbench:
 *
 *   ┌──────────┬─────────────────────────┬───────────────────────┐
 *   │ Documents│   PDF page viewer       │  Field list           │
 *   │  (sidebar│   + bbox highlight      │  + pencil edit /      │
 *   │   list)  │                         │    save / cancel      │
 *   └──────────┴─────────────────────────┴───────────────────────┘
 *
 * Selecting a field on the right column scrolls the middle column to the
 * page where that field was located and overlays its bounding box on the
 * rendered page image. Bounding boxes are normalized 0–1 coordinates emitted
 * by the extraction agent (`[x1, y1, x2, y2]`) and positioned with
 * percentage offsets so they track the image at any size.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  FileSearch,
  FileText,
  Maximize2,
  Pencil,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { apiFetchBlob } from "@/lib/api";
import { fetchPageWords, type LoanPageWord } from "@/lib/loan-onboarding/api";
import type { LoanStack, LoanStackExtraction } from "@/lib/loan-onboarding/types";
import { cn } from "@/lib/utils";

export type WorkbenchFieldRow = {
  /** Composite override key — `${stackId}::${docType}::${fieldName}`. */
  key: string;
  stackId: string;
  docType: string;
  docTypeLabel: string;
  fieldName: string;
  /** Cosmetic chip ("Currency", "Date", "Address", …). */
  fieldTypeLabel: string;
  originalValue: string | null;
  confidence: number | null;
  status: "located" | "low_confidence" | "missing";
  /** Absolute page number in the source PDF (1-indexed) or null. */
  page: number | null;
  /** [x1, y1, x2, y2] normalized 0..1, or null if unknown. */
  bbox: number[] | null;
};

interface ExtractionWorkbenchProps {
  orgId: string;
  packageId: string;
  /** Extractions already merged with placeholder rows (parent owns merge). */
  extractions: LoanStackExtraction[];
  /** Real stacks (used to resolve page_id for image fetch). */
  stacks: LoanStack[];
  /** Pre-built rows (one per field, includes placeholders). */
  rows: WorkbenchFieldRow[];
  /** Persistence state — keyed by `WorkbenchFieldRow.key`. */
  fieldEdits: Record<string, string>;
  fieldSaved: Record<string, string>;
  fieldErrors: Record<string, string | null>;
  fieldBusy: Record<string, boolean>;
  onChangeDraft: (row: WorkbenchFieldRow, value: string) => void;
  onSaveDraft: (row: WorkbenchFieldRow) => void;
  onCancelDraft: (row: WorkbenchFieldRow) => void;
}

// ──────────────────────────────────────────────────────────────────────
// Authenticated <img> loader — fetches page JPEG via apiFetchBlob (which
// injects auth + org headers), renders via createObjectURL, revokes on
// unmount. Mirrors the pattern used by stack-expanded.tsx.
// ──────────────────────────────────────────────────────────────────────
function AuthImage({
  path,
  orgId,
  alt,
  className,
  onLoad,
}: {
  path: string;
  orgId: string;
  alt: string;
  className?: string;
  onLoad?: (img: HTMLImageElement) => void;
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
      if (srcRef.current) {
        URL.revokeObjectURL(srcRef.current);
        srcRef.current = null;
      }
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
    return <div className={cn("bg-muted/40 animate-pulse rounded", className)} />;
  }

  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onLoad={(e) => onLoad?.(e.currentTarget)}
    />
  );
}

// ──────────────────────────────────────────────────────────────────────
// Workbench
// ──────────────────────────────────────────────────────────────────────
export function ExtractionWorkbench({
  orgId,
  packageId,
  extractions,
  stacks,
  rows,
  fieldEdits,
  fieldSaved,
  fieldErrors,
  fieldBusy,
  onChangeDraft,
  onSaveDraft,
  onCancelDraft,
}: ExtractionWorkbenchProps) {
  // Group rows by stack_id so the doc-list column (left) can show one row
  // per document with a field count, and the field-list column (right) can
  // show only the fields for the currently selected document.
  const groups = useMemo(() => {
    const order: string[] = [];
    const byStack = new Map<string, WorkbenchFieldRow[]>();
    for (const r of rows) {
      if (!byStack.has(r.stackId)) {
        byStack.set(r.stackId, []);
        order.push(r.stackId);
      }
      byStack.get(r.stackId)!.push(r);
    }
    return order.map((stackId) => ({
      stackId,
      docType: byStack.get(stackId)![0].docType,
      docTypeLabel: byStack.get(stackId)![0].docTypeLabel,
      fields: byStack.get(stackId)!,
    }));
  }, [rows]);

  // page_id lookup keyed by absolute page_number — driven off real stacks,
  // so placeholder docs (no stack) just won't have a viewer image.
  const pageIdByNumber = useMemo(() => {
    const m = new Map<number, string>();
    for (const s of stacks) {
      for (const p of s.pages) {
        m.set(p.page_number, p.page_id);
      }
    }
    return m;
  }, [stacks]);

  // Look up the LoanStack matching the selected doc group so we can list
  // its pages in the viewer toolbar.
  const stacksByStackId = useMemo(() => {
    const m = new Map<string, LoanStack>();
    for (const s of stacks) m.set(s.id, s);
    return m;
  }, [stacks]);

  // Selection state — selected doc group + selected field within it.
  const [selectedStackId, setSelectedStackId] = useState<string | null>(
    groups[0]?.stackId ?? null
  );
  // If the parent's row set changes (e.g., extractions reload) and the
  // current selection disappears, fall back to the first group.
  useEffect(() => {
    if (groups.length === 0) {
      setSelectedStackId(null);
      return;
    }
    if (
      selectedStackId === null ||
      !groups.some((g) => g.stackId === selectedStackId)
    ) {
      setSelectedStackId(groups[0].stackId);
    }
  }, [groups, selectedStackId]);

  const selectedGroup = useMemo(
    () => groups.find((g) => g.stackId === selectedStackId) ?? null,
    [groups, selectedStackId]
  );

  // Active field — drives bbox overlay + page navigation.
  const [activeFieldKey, setActiveFieldKey] = useState<string | null>(null);
  // Edit mode — only one field at a time has its textarea revealed.
  const [editingKey, setEditingKey] = useState<string | null>(null);

  // Reset active/editing field when the selected doc changes.
  useEffect(() => {
    setActiveFieldKey(null);
    setEditingKey(null);
  }, [selectedStackId]);

  // Active page number for the viewer. Defaults to the active field's page
  // when one is selected, falls back to the first page of the stack.
  const stackPages = useMemo<number[]>(() => {
    if (!selectedGroup) return [];
    const stack = stacksByStackId.get(selectedGroup.stackId);
    if (!stack) return [];
    return stack.pages.map((p) => p.page_number).sort((a, b) => a - b);
  }, [selectedGroup, stacksByStackId]);

  const activeRow = useMemo(
    () => rows.find((r) => r.key === activeFieldKey) ?? null,
    [rows, activeFieldKey]
  );

  const [viewerPage, setViewerPage] = useState<number | null>(null);

  // Selected stack (used for words prefetch + detected_fields fallback).
  const selectedStack = selectedGroup
    ? stacksByStackId.get(selectedGroup.stackId) ?? null
    : null;

  // Per-page word coords (PyMuPDF, fetched on demand). Cached in a ref by
  // pageId so re-renders don't refetch and switching back/forth is instant.
  // Also caches `page_width`/`page_height` (PDF user-space pixels, e.g.
  // 612x792 for letter) so we can correctly normalize agent-emitted bboxes
  // — Claude/Gemini tend to emit in PDF user-space coords, NOT 0..1, NOT
  // [0, 1000]. Without the real page dims we can only guess the divisor.
  const wordsCacheRef = useRef<Map<string, LoanPageWord[]>>(new Map());
  const dimsCacheRef = useRef<Map<string, { width: number; height: number }>>(
    new Map()
  );
  const [wordsByPageId, setWordsByPageId] = useState<Record<string, LoanPageWord[]>>(
    {}
  );
  const [dimsByPageId, setDimsByPageId] = useState<
    Record<string, { width: number; height: number }>
  >({});

  // Prefetch words for ALL pages in the selected stack so the resolver can
  // search the whole document — not just the current viewer page. This lets
  // us auto-jump the viewer when a field's text lives on a later page.
  useEffect(() => {
    if (!selectedStack) return;
    let cancelled = false;
    const targets = selectedStack.pages
      .map((p) => p.page_id)
      .filter((id): id is string => !!id && !wordsCacheRef.current.has(id));
    if (targets.length === 0) return;

    Promise.all(
      targets.map((id) =>
        fetchPageWords(orgId, packageId, id)
          .then((res) => ({
            id,
            words: res.words,
            width: res.page_width,
            height: res.page_height,
          }))
          .catch((err) => {
            console.warn(`fetchPageWords failed for ${id}:`, err);
            return {
              id,
              words: [] as LoanPageWord[],
              width: 0,
              height: 0,
            };
          })
      )
    ).then((results) => {
      if (cancelled) return;
      const nextWords: Record<string, LoanPageWord[]> = {};
      const nextDims: Record<string, { width: number; height: number }> = {};
      for (const r of results) {
        wordsCacheRef.current.set(r.id, r.words);
        nextWords[r.id] = r.words;
        if (r.width > 0 && r.height > 0) {
          const d = { width: r.width, height: r.height };
          dimsCacheRef.current.set(r.id, d);
          nextDims[r.id] = d;
        }
      }
      setWordsByPageId((m) => ({ ...m, ...nextWords }));
      setDimsByPageId((m) => ({ ...m, ...nextDims }));
    });

    return () => {
      cancelled = true;
    };
  }, [selectedStack, orgId, packageId]);

  // Resolve the field's location across the whole stack. Tries text match
  // on every page; returns the first page whose words contain the value.
  const resolvedTarget = useMemo(
    () =>
      _resolveTarget(activeRow, selectedStack, wordsByPageId, dimsByPageId),
    [activeRow, selectedStack, wordsByPageId, dimsByPageId]
  );

  // When the user picks a field, jump the viewer to:
  //   1. The page where its text was matched (best — auto-locate).
  //   2. The agent-emitted page if any.
  //   3. The first page of the stack (fallback).
  // When the doc changes (no active field), reset to the first page.
  useEffect(() => {
    if (resolvedTarget && stackPages.includes(resolvedTarget.page)) {
      setViewerPage(resolvedTarget.page);
      return;
    }
    if (activeRow?.page && stackPages.includes(activeRow.page)) {
      setViewerPage(activeRow.page);
      return;
    }
    setViewerPage(stackPages[0] ?? null);
  }, [activeRow, resolvedTarget, stackPages]);

  const viewerPageId =
    viewerPage != null ? pageIdByNumber.get(viewerPage) ?? null : null;

  // Show overlay only when the resolved target's page matches what's on
  // screen. Falls back to the per-page resolver (agent bbox / detected
  // fields) if cross-stack text match returned nothing.
  const overlayBbox = useMemo(() => {
    if (resolvedTarget && resolvedTarget.page === viewerPage) {
      return resolvedTarget.bbox;
    }
    const pageWords = viewerPageId ? wordsByPageId[viewerPageId] : undefined;
    const pageDims = viewerPageId ? dimsByPageId[viewerPageId] : undefined;
    return _resolveOverlayBbox(
      activeRow,
      viewerPage,
      selectedStack,
      pageWords,
      pageDims
    );
  }, [
    resolvedTarget,
    viewerPage,
    viewerPageId,
    wordsByPageId,
    dimsByPageId,
    activeRow,
    selectedStack,
  ]);

  // Hint when an active field is selected but precise location can't be
  // resolved (text not present, OCR-only PDF, words still loading, etc.).
  // Suppress until at least one of the stack's pages has finished loading.
  const anyWordsLoaded = selectedStack
    ? selectedStack.pages.some((p) => p.page_id in wordsByPageId)
    : false;
  const hintNoBbox =
    activeRow != null && overlayBbox == null && anyWordsLoaded;

  return (
    <div
      className="bg-card border border-border"
      data-testid="extraction-workbench"
    >
      <div className="px-6 py-4 border-b border-border flex items-start justify-between gap-4">
        <div>
          <div className="font-mono text-[10px] tracking-[0.2em] text-muted-foreground uppercase">
            Extracted field values
          </div>
          <div className="text-[12px] text-muted-foreground mt-1">
            Pick a document, click a field to highlight it on the page, and
            use the pencil to edit. Save or Cancel commits the change.
          </div>
        </div>
        <div className="text-right font-mono text-[10px] text-muted-foreground tabular-nums shrink-0">
          {extractions.length} doc{extractions.length === 1 ? "" : "s"} ·{" "}
          {rows.length} field{rows.length === 1 ? "" : "s"}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_360px] min-h-[560px]">
        {/* ─── Column 1 — Documents ────────────────────────────────── */}
        <DocumentsColumn
          groups={groups}
          stacksByStackId={stacksByStackId}
          fieldSaved={fieldSaved}
          selectedStackId={selectedStackId}
          onSelect={setSelectedStackId}
        />

        {/* ─── Column 2 — Viewer ───────────────────────────────────── */}
        <ViewerColumn
          orgId={orgId}
          packageId={packageId}
          stackPages={stackPages}
          viewerPage={viewerPage}
          viewerPageId={viewerPageId}
          overlayBbox={overlayBbox}
          hintNoBbox={hintNoBbox}
          activeFieldName={activeRow?.fieldName ?? null}
          onPrev={() => {
            if (viewerPage == null) return;
            const idx = stackPages.indexOf(viewerPage);
            if (idx > 0) {
              setViewerPage(stackPages[idx - 1]);
              setActiveFieldKey(null);
            }
          }}
          onNext={() => {
            if (viewerPage == null) return;
            const idx = stackPages.indexOf(viewerPage);
            if (idx >= 0 && idx < stackPages.length - 1) {
              setViewerPage(stackPages[idx + 1]);
              setActiveFieldKey(null);
            }
          }}
        />

        {/* ─── Column 3 — Fields ───────────────────────────────────── */}
        <FieldsColumn
          group={selectedGroup}
          activeFieldKey={activeFieldKey}
          editingKey={editingKey}
          // Editing only makes sense when the viewer has something to
          // show — placeholder docs (configured doc-type with no matching
          // stack) carry no pages, so the pencil would open an editor
          // with nothing to review against.
          canEdit={
            !!selectedStack &&
            selectedStack.pages.some((p) => !!p.page_id)
          }
          fieldEdits={fieldEdits}
          fieldSaved={fieldSaved}
          fieldErrors={fieldErrors}
          fieldBusy={fieldBusy}
          onActivate={(row) => {
            setActiveFieldKey(row.key);
            setEditingKey(null);
          }}
          onBeginEdit={(row) => {
            setActiveFieldKey(row.key);
            setEditingKey(row.key);
          }}
          onChangeDraft={onChangeDraft}
          onSave={async (row) => {
            await onSaveDraft(row);
            // Close the editor only if save succeeded — parent clears
            // fieldErrors[row.key] on success.
            setEditingKey((cur) => (cur === row.key ? null : cur));
          }}
          onCancel={(row) => {
            onCancelDraft(row);
            setEditingKey((cur) => (cur === row.key ? null : cur));
          }}
        />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Column 1 — Documents sidebar
// ──────────────────────────────────────────────────────────────────────
interface DocumentsColumnProps {
  groups: Array<{
    stackId: string;
    docType: string;
    docTypeLabel: string;
    fields: WorkbenchFieldRow[];
  }>;
  stacksByStackId: Map<string, LoanStack>;
  fieldSaved: Record<string, string>;
  selectedStackId: string | null;
  onSelect: (stackId: string) => void;
}

function DocumentsColumn({
  groups,
  stacksByStackId,
  fieldSaved,
  selectedStackId,
  onSelect,
}: DocumentsColumnProps) {
  return (
    <div
      className="border-b lg:border-b-0 lg:border-r border-border bg-muted/20"
      data-testid="workbench-documents-column"
    >
      <div className="px-4 py-3 border-b border-border/60 font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
        Documents
      </div>
      {groups.length === 0 ? (
        <div className="px-4 py-6 text-[12px] text-muted-foreground italic">
          No documents.
        </div>
      ) : (
        <ul className="overflow-auto max-h-[600px]">
          {groups.map((g) => {
            const stack = stacksByStackId.get(g.stackId);
            const isPlaceholder = !stack;
            const located = g.fields.filter(
              (f) => f.status === "located" || f.status === "low_confidence"
            ).length;
            const editedInDoc = g.fields.filter(
              (f) => fieldSaved[f.key] !== undefined
            ).length;
            const isActive = selectedStackId === g.stackId;
            return (
              <li key={g.stackId}>
                <button
                  type="button"
                  onClick={() => onSelect(g.stackId)}
                  className={cn(
                    "w-full text-left px-4 py-3 border-b border-border/60 transition-colors flex flex-col gap-1",
                    isActive
                      ? "bg-amber-50/70"
                      : "bg-transparent hover:bg-muted/40"
                  )}
                  data-testid={`workbench-doc-${g.docType}`}
                  aria-current={isActive ? "true" : undefined}
                >
                  <div className="flex items-start gap-2 min-w-0">
                    <FileText
                      className={cn(
                        "h-3.5 w-3.5 mt-0.5 shrink-0",
                        isActive ? "text-amber-600" : "text-muted-foreground"
                      )}
                    />
                    <span
                      className={cn(
                        "font-serif text-[13px] leading-tight truncate",
                        isActive ? "text-foreground" : "text-foreground/90"
                      )}
                    >
                      {g.docTypeLabel}
                    </span>
                  </div>
                  <div className="font-mono text-[9px] tracking-[0.12em] text-muted-foreground tabular-nums uppercase pl-5">
                    {isPlaceholder
                      ? "no stack · "
                      : `${stack!.page_count}pp · `}
                    {located}/{g.fields.length} located
                    {editedInDoc > 0 && (
                      <span className="text-emerald-600">
                        {" "}
                        · {editedInDoc} edited
                      </span>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Column 2 — Page viewer with bbox overlay
// ──────────────────────────────────────────────────────────────────────
interface ViewerColumnProps {
  orgId: string;
  packageId: string;
  stackPages: number[];
  viewerPage: number | null;
  viewerPageId: string | null;
  overlayBbox: number[] | null;
  hintNoBbox: boolean;
  activeFieldName: string | null;
  onPrev: () => void;
  onNext: () => void;
}

// Zoom presets — keep in step with the buttons' enabled state.
const ZOOM_LEVELS = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3] as const;
const ZOOM_DEFAULT = 1.5;
const VIEWER_BASE_HEIGHT = 520; // px at zoom=1; matches the original max-h-[520px]

function ViewerColumn({
  orgId,
  packageId,
  stackPages,
  viewerPage,
  viewerPageId,
  overlayBbox,
  hintNoBbox,
  activeFieldName,
  onPrev,
  onNext,
}: ViewerColumnProps) {
  const idx = viewerPage != null ? stackPages.indexOf(viewerPage) : -1;
  const hasPrev = idx > 0;
  const hasNext = idx >= 0 && idx < stackPages.length - 1;

  const [zoom, setZoom] = useState<number>(ZOOM_DEFAULT);
  const minZoom = ZOOM_LEVELS[0];
  const maxZoom = ZOOM_LEVELS[ZOOM_LEVELS.length - 1];
  const zoomIn = () => {
    const next = ZOOM_LEVELS.find((z) => z > zoom + 1e-6);
    if (next != null) setZoom(next);
  };
  const zoomOut = () => {
    const prev = [...ZOOM_LEVELS].reverse().find((z) => z < zoom - 1e-6);
    if (prev != null) setZoom(prev);
  };
  const zoomReset = () => setZoom(ZOOM_DEFAULT);

  return (
    <div
      className="flex flex-col border-b lg:border-b-0 lg:border-r border-border"
      data-testid="workbench-viewer-column"
    >
      <div className="px-4 py-3 border-b border-border/60 flex items-center justify-between gap-3 flex-wrap">
        <div className="font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase">
          Viewer
        </div>
        <div className="flex items-center gap-2">
          {/* Zoom group */}
          <div className="flex items-center gap-1 pr-2 mr-1 border-r border-border/60">
            <button
              type="button"
              onClick={zoomOut}
              disabled={zoom <= minZoom + 1e-6}
              aria-label="Zoom out"
              title="Zoom out"
              className="h-6 w-6 inline-flex items-center justify-center rounded border border-border bg-background hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="workbench-viewer-zoom-out"
            >
              <ZoomOut className="h-3 w-3" />
            </button>
            <button
              type="button"
              onClick={zoomReset}
              aria-label="Reset zoom"
              title={`Reset zoom (${Math.round(ZOOM_DEFAULT * 100)}%)`}
              className="h-6 px-1.5 inline-flex items-center justify-center gap-1 rounded border border-border bg-background hover:bg-muted/40 font-mono text-[10px] text-muted-foreground tabular-nums"
              data-testid="workbench-viewer-zoom-reset"
            >
              <Maximize2 className="h-2.5 w-2.5" />
              {Math.round(zoom * 100)}%
            </button>
            <button
              type="button"
              onClick={zoomIn}
              disabled={zoom >= maxZoom - 1e-6}
              aria-label="Zoom in"
              title="Zoom in"
              className="h-6 w-6 inline-flex items-center justify-center rounded border border-border bg-background hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="workbench-viewer-zoom-in"
            >
              <ZoomIn className="h-3 w-3" />
            </button>
          </div>
          {/* Page nav */}
          <button
            type="button"
            onClick={onPrev}
            disabled={!hasPrev}
            aria-label="Previous page"
            className="h-6 w-6 inline-flex items-center justify-center rounded border border-border bg-background hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="workbench-viewer-prev"
          >
            <ChevronLeft className="h-3 w-3" />
          </button>
          <span className="font-mono text-[10px] text-muted-foreground tabular-nums">
            {viewerPage != null && stackPages.length > 0
              ? `Page ${viewerPage} · ${idx + 1}/${stackPages.length}`
              : "—"}
          </span>
          <button
            type="button"
            onClick={onNext}
            disabled={!hasNext}
            aria-label="Next page"
            className="h-6 w-6 inline-flex items-center justify-center rounded border border-border bg-background hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="workbench-viewer-next"
          >
            <ChevronRight className="h-3 w-3" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-amber-50/30 min-h-[420px]">
        <div className="px-6 py-6 flex items-start justify-center min-h-full">
          {viewerPageId ? (
            <div
              className="relative bg-card border border-border shadow-sm rounded overflow-hidden inline-block"
              style={{ height: `${VIEWER_BASE_HEIGHT * zoom}px` }}
              data-testid="workbench-viewer-stage"
            >
              <AuthImage
                key={viewerPageId}
                path={`/api/v1/apps/loan-onboarding/packages/${packageId}/pages/${viewerPageId}/image`}
                orgId={orgId}
                alt={
                  activeFieldName
                    ? `Page ${viewerPage} (highlight: ${activeFieldName})`
                    : `Page ${viewerPage}`
                }
                className="block h-full w-auto max-w-none"
              />
              {overlayBbox && (
                <BboxOverlay bbox={overlayBbox} label={activeFieldName} />
              )}
            </div>
          ) : (
            <div className="text-[12px] text-muted-foreground italic text-center max-w-xs self-center">
              {stackPages.length === 0
                ? "No pages in this document — fields are configured but no matching stack was produced."
                : "Loading page…"}
            </div>
          )}
        </div>
      </div>

      {overlayBbox && (
        <div
          className="px-4 py-2 border-t border-border/60 bg-muted/30 font-mono text-[10px] text-muted-foreground flex items-center gap-2"
          data-testid="workbench-bbox-hint-located"
        >
          <span className="h-2 w-2 rounded-sm bg-amber-500/60 ring-2 ring-amber-500" />
          Highlighting{" "}
          <span className="text-foreground font-medium">{activeFieldName}</span>{" "}
          on page {viewerPage}.
        </div>
      )}
      {!overlayBbox && hintNoBbox && (
        <div
          className="px-4 py-2 border-t border-border/60 bg-amber-50/60 font-mono text-[10px] text-amber-800 flex items-center gap-2"
          data-testid="workbench-bbox-hint-fallback"
        >
          <AlertCircle className="h-3 w-3" />
          <span className="text-foreground font-medium">{activeFieldName}</span>
          <span>
            is on page {viewerPage} — precise location not detected.
          </span>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Bbox resolver (with page-classifier fallback)
// ──────────────────────────────────────────────────────────────────────

function _norm(s: string | null | undefined): string {
  return (s ?? "")
    .toLowerCase()
    // Treat _ and - as separators so extraction-style "employee_name" matches
    // page-classifier-style "Employee Name" or "employee-name".
    .replace(/[_\-]+/g, " ")
    .replace(/[\s\u00a0]+/g, " ")
    .replace(/[^\w\s./]/g, "")
    .trim();
}

/**
 * Validate a bbox shape — `[x1, y1, x2, y2]` of finite numbers, non-zero,
 * non-degenerate. Doesn't enforce a coordinate convention; that's
 * `_normalizeAgentBbox`'s job.
 */
function _isValidBboxShape(bbox: unknown): bbox is number[] {
  if (!Array.isArray(bbox) || bbox.length !== 4) return false;
  if (bbox.some((n) => typeof n !== "number" || !Number.isFinite(n))) {
    return false;
  }
  const [x1, y1, x2, y2] = bbox as number[];
  if (x1 === 0 && y1 === 0 && x2 === 0 && y2 === 0) return false;
  if (Math.abs(x2 - x1) < 1e-6 || Math.abs(y2 - y1) < 1e-6) return false;
  return true;
}

/**
 * Normalize an AI-emitted bbox `[x1, y1, x2, y2]` into 0..1 space so
 * `BboxOverlay` can render it correctly. Both Claude (extraction agent) and
 * Gemini (page classifier) emit in inconsistent conventions:
 *   - already-0..1 (max ≤ 1.5) → use as-is
 *   - real PDF user-space pixels (e.g. 612×792 letter) → divide x by page
 *     width, y by page height (the only path that lines up exactly with
 *     PyMuPDF word coords, which the `/words` endpoint also returns in 0..1)
 *   - Gemini's [0, 1000] standard → divide by 1000 (used only when page
 *     dims are unknown AND the bbox max falls in that range)
 *   - other → divide by max bbox coord (last-resort guess)
 *
 * `pageDims` should be the page's real PDF user-space dimensions (from the
 * `/words` endpoint). When supplied AND the bbox values fit inside them
 * (with a 10% tolerance), we treat the bbox as PDF user-space and use the
 * exact divisors. This is the only path that produces visually-correct
 * highlights when both the words and the agent bbox are in PDF coords.
 *
 * Returns null if the bbox is unusable.
 */
function _normalizeAgentBbox(
  bbox: number[],
  pageDims?: { width: number; height: number } | null
): number[] | null {
  const maxC = Math.max(...bbox.map(Math.abs));
  if (maxC <= 1.5) return bbox;

  // Preferred: real PDF user-space dims from the /words endpoint.
  if (pageDims && pageDims.width > 0 && pageDims.height > 0) {
    const [x1, y1, x2, y2] = bbox;
    const tol = 1.1; // 10% slack — agents occasionally over/undershoot
    if (
      Math.abs(x1) <= pageDims.width * tol &&
      Math.abs(x2) <= pageDims.width * tol &&
      Math.abs(y1) <= pageDims.height * tol &&
      Math.abs(y2) <= pageDims.height * tol
    ) {
      return [
        x1 / pageDims.width,
        y1 / pageDims.height,
        x2 / pageDims.width,
        y2 / pageDims.height,
      ];
    }
  }

  // Gemini's [0, 1000] standard.
  if (maxC <= 1100) return bbox.map((v) => v / 1000);

  // Last-resort: divide by max coord seen.
  if (maxC <= 0) return null;
  return bbox.map((v) => v / maxC);
}


/**
 * Cross-stack target resolver. Searches every prefetched page in the stack
 * for the active field's text and returns the first hit's `{page, bbox}`.
 *
 * Priority:
 *   1. Agent-emitted `row.page` if its words contain the value.
 *   2. Any other page in the stack whose words contain the value.
 *   3. Cross-stack `detected_fields` match by field_name or value — covers
 *      the case where the extraction agent emitted bbox [0,0,0,0] AND the
 *      value's spelling on the page differs (e.g. paystub `employee_name`
 *      / `employer_name` rendered in stylized tabular headers that the
 *      PyMuPDF word stream reorders).
 *   4. null (caller falls back to per-page resolver).
 */
function _resolveTarget(
  row: WorkbenchFieldRow | null,
  stack: LoanStack | null,
  wordsByPageId: Record<string, LoanPageWord[]>,
  dimsByPageId: Record<string, { width: number; height: number }>
): { page: number; bbox: number[] } | null {
  if (!row || !stack) return null;
  const target = row.originalValue;

  const tryTextMatch = (
    text: string | null | undefined,
    pageId: string
  ): number[] | null => {
    if (!text || !text.trim()) return null;
    const words = wordsByPageId[pageId];
    if (!words || words.length === 0) return null;
    return _findTextBbox(words, text);
  };

  if (target && target.trim()) {
    // 1) Try declared page first when present.
    if (row.page != null) {
      const declared = stack.pages.find((p) => p.page_number === row.page);
      if (declared && declared.page_id) {
        const bbox = tryTextMatch(target, declared.page_id);
        if (bbox) return { page: declared.page_number, bbox };
      }
    }

    // 2) Search the whole stack in page order.
    for (const p of stack.pages) {
      if (!p.page_id) continue;
      if (row.page != null && p.page_number === row.page) continue; // already tried
      const bbox = tryTextMatch(target, p.page_id);
      if (bbox) return { page: p.page_number, bbox };
    }
  }

  // 3) detected_fields-driven cross-page resolution. Uses the classifier's
  //    own `value` (which is what literally appears on the page) to drive a
  //    text-match; falls back to the classifier bbox normalized against
  //    real PDF dims as a last resort.
  //
  // (The extraction agent's own raw bbox used to be path 3 here. It was
  // dropped because `stage_extract` feeds the agent text + detected_fields
  // only — zero coordinate signal — so any bbox the agent emits is
  // hallucinated. Trusting it produced confidently-placed highlights in
  // the wrong location. The classifier bbox below IS grounded — PyMuPDF
  // emits it during ingest from real word positions.)
  return _resolveDetectedFieldAcrossStack(
    row,
    stack,
    wordsByPageId,
    dimsByPageId
  );
}

/**
 * Walks every page's `detected_fields[]` looking for an entry whose
 * `field_name` matches `row.fieldName` (preferred) or whose `value`
 * matches `row.originalValue` (fallback). Returns the first usable
 * `{page, bbox}` it finds, or null.
 *
 * The page classifier emits these alongside doc-type detection and almost
 * always supplies a real bbox on form-style pages (paystubs, W-2s, 1003) —
 * making this a strong fallback when the extraction agent's bbox is
 * [0,0,0,0] (per its own prompt) or the value's exact text doesn't appear
 * verbatim on the page.
 */
function _resolveDetectedFieldAcrossStack(
  row: WorkbenchFieldRow,
  stack: LoanStack,
  wordsByPageId: Record<string, LoanPageWord[]>,
  dimsByPageId: Record<string, { width: number; height: number }>
): { page: number; bbox: number[] } | null {
  const targetName = _norm(row.fieldName);
  const targetValue = _norm(row.originalValue);
  if (!targetName && !targetValue) return null;

  // Try declared page first when present, then the rest in page order.
  const ordered = [...stack.pages].sort((a, b) => {
    if (row.page != null) {
      if (a.page_number === row.page) return -1;
      if (b.page_number === row.page) return 1;
    }
    return a.page_number - b.page_number;
  });

  const findEntry = (
    list: Array<Record<string, unknown>>
  ): Record<string, unknown> | null => {
    if (targetName) {
      for (const entry of list) {
        const n = _norm(
          typeof entry.field_name === "string" ? entry.field_name : null
        );
        if (
          n &&
          (n === targetName || n.includes(targetName) || targetName.includes(n))
        ) {
          return entry;
        }
      }
    }
    if (targetValue) {
      for (const entry of list) {
        const v = _norm(typeof entry.value === "string" ? entry.value : null);
        if (
          v &&
          (v === targetValue ||
            v.includes(targetValue) ||
            targetValue.includes(v))
        ) {
          return entry;
        }
      }
    }
    return null;
  };

  // First pass — find the field on every page and try the most reliable
  // anchor (PyMuPDF text-match on the classifier's literal value or the
  // extraction value). Keep a memo of bbox-only fallbacks for the second
  // pass so text-match wins over a coord-convention-guess.
  const bboxFallbacks: Array<{ page: number; bbox: number[] }> = [];

  for (const p of ordered) {
    const raw = (p.detected_fields ?? []) as unknown;
    const list: Array<Record<string, unknown>> = Array.isArray(raw)
      ? (raw as Array<Record<string, unknown>>)
      : [];
    if (list.length === 0) continue;
    const matched = findEntry(list);
    if (!matched) continue;

    // Drive a text-match using the classifier's own `value` (what literally
    // appears on the page) — most reliable when it works.
    const classifierValue =
      typeof matched.value === "string" ? matched.value : null;
    if (classifierValue && p.page_id) {
      const words = wordsByPageId[p.page_id];
      if (words && words.length > 0) {
        const bbox = _findTextBbox(words, classifierValue);
        if (bbox) return { page: p.page_number, bbox };
      }
    }

    // Try the extraction's own value text-match on this page.
    if (row.originalValue && p.page_id) {
      const words = wordsByPageId[p.page_id];
      if (words && words.length > 0) {
        const bbox = _findTextBbox(words, row.originalValue);
        if (bbox) return { page: p.page_number, bbox };
      }
    }

    // Memoize the classifier's bbox as a fallback. Normalize using
    // `_normalizeAgentBbox` with the real PDF page dims (from /words) so
    // PDF user-space coords (the typical case) render at the right spot.
    if (_isValidBboxShape(matched.bbox)) {
      const dims = p.page_id ? dimsByPageId[p.page_id] : undefined;
      const normalized = _normalizeAgentBbox(matched.bbox as number[], dims);
      if (normalized) {
        bboxFallbacks.push({ page: p.page_number, bbox: normalized });
      }
    }
  }

  return bboxFallbacks[0] ?? null;
}

/**
 * Resolves the bbox to render for the current selection. Priority order:
 *   1. **Text match against PyMuPDF word stream** — find the contiguous run
 *      of words on this page that best matches the extracted value, then
 *      return the union bbox. Most reliable: it highlights the actual text.
 *   2. **Classifier-driven text match** — look up `detected_fields[]` on
 *      this page for an entry matching the field name (or value), then
 *      text-match the classifier's literal `value` against the word stream.
 *      This rescues cases where the extraction value differs slightly from
 *      what's literally on the page.
 *   3. **Classifier bbox fallback** — when text-match fails, render the
 *      matched entry's own bbox normalized through `_normalizeAgentBbox`
 *      (handles pixel coords, Gemini's [0,1000], and already-0..1 inputs).
 *      This trades coord-convention guesswork for at least *some* highlight
 *      on form-style pages (paystubs, W-2s, 1003) where the classifier
 *      reliably reports field positions.
 */
function _resolveOverlayBbox(
  row: WorkbenchFieldRow | null,
  viewerPage: number | null,
  stack: LoanStack | null,
  pageWords: LoanPageWord[] | undefined,
  pageDims: { width: number; height: number } | undefined
): number[] | null {
  if (!row || viewerPage == null) return null;
  // If the row has a known page that doesn't match the viewer, no highlight.
  // If the row has no page, we still try matching against the current page.
  if (row.page != null && row.page !== viewerPage) return null;

  // 1) Text-search the word stream for the extracted value.
  if (pageWords && pageWords.length > 0) {
    const target = row.originalValue;
    if (target && target.trim().length > 0) {
      const found = _findTextBbox(pageWords, target);
      if (found) return found;
    }
  }

  // 2) Use the extraction row's own bbox if present. Backed by `/words`
  //    page dims, this lands on the right spot for PDF-user-space coords
  //    (the most common emitter convention) and works on image-only PDFs.
  if (_isValidBboxShape(row.bbox)) {
    const normalized = _normalizeAgentBbox(row.bbox as number[], pageDims);
    if (normalized) return normalized;
  }

  // 3) Page-classifier `detected_fields` — drive text-match using the
  //    classifier's literal `value`, then fall back to its bbox normalized
  //    against real PDF dims.
  if (!stack) return null;
  const page = stack.pages.find((p) => p.page_number === viewerPage);
  if (!page || !page.detected_fields) return null;
  const raw = page.detected_fields as unknown;
  const list: Array<Record<string, unknown>> = Array.isArray(raw)
    ? (raw as Array<Record<string, unknown>>)
    : [];
  if (list.length === 0) return null;
  const targetValue = _norm(row.originalValue);
  const targetName = _norm(row.fieldName);
  const findMatchedEntry = (): Record<string, unknown> | null => {
    if (targetName) {
      for (const entry of list) {
        const n = _norm(
          typeof entry.field_name === "string" ? entry.field_name : null
        );
        if (
          n &&
          (n === targetName || n.includes(targetName) || targetName.includes(n))
        ) {
          return entry;
        }
      }
    }
    if (targetValue) {
      for (const entry of list) {
        const v = _norm(typeof entry.value === "string" ? entry.value : null);
        if (
          v &&
          (v === targetValue ||
            v.includes(targetValue) ||
            targetValue.includes(v))
        ) {
          return entry;
        }
      }
    }
    return null;
  };
  const matched = findMatchedEntry();
  if (!matched) return null;

  // Prefer text-matching the classifier's literal `value` against the word
  // stream — most reliable when it works.
  const classifierValue =
    typeof matched.value === "string" ? matched.value : null;
  if (
    classifierValue &&
    classifierValue.trim() &&
    pageWords &&
    pageWords.length > 0
  ) {
    const found = _findTextBbox(pageWords, classifierValue);
    if (found) return found;
  }

  // Fallback: render the classifier's own bbox normalized into 0..1 using
  // the real PDF page dims from `/words`.
  if (_isValidBboxShape(matched.bbox)) {
    const normalized = _normalizeAgentBbox(matched.bbox as number[], pageDims);
    if (normalized) return normalized;
  }
  return null;
}

/**
 * Finds the location of the extracted value on a page by matching its text
 * against the PyMuPDF word stream. Returns a union bbox covering the matched
 * region, or null if no reasonable match exists.
 *
 * Strategy — seed-and-expand:
 *   1. Tokenize the target. Use up to the first 6 meaningful tokens as a
 *      "seed" so long paragraph values (e.g. `schedule_b_exceptions`) still
 *      match on their opening words.
 *   2. Slide a window of `seedLen` over the page's tokens, score each window
 *      by exact-token + substring equality.
 *   3. Score ≥ 0.5 wins. Extend the bbox to cover up to `targetLen` tokens
 *      starting at the seed, OR until the line breaks visibly.
 *   4. Single-token targets fall back to first-equal then first-substring.
 *
 * Numeric commas in the target are stripped first so "$5,400.00" matches a
 * page word "$5,400.00" (which the page-side `_normToken` flattens to
 * "5400.00").
 */
function _findTextBbox(
  words: LoanPageWord[],
  target: string
): number[] | null {
  const targetTokens = _tokenize(target);
  if (targetTokens.length === 0) return null;

  const pageTokens: string[] = words.map((w) => _normToken(w.text));
  if (pageTokens.length < 1) return null;

  // Single-token: equality first, substring fallback.
  if (targetTokens.length === 1) {
    const t = targetTokens[0];
    for (let i = 0; i < pageTokens.length; i++) {
      if (pageTokens[i] === t) return _wordsToBbox([words[i]]);
    }
    for (let i = 0; i < pageTokens.length; i++) {
      const p = pageTokens[i];
      if (!p) continue;
      if (p.length >= 3 && t.length >= 3 && (p.includes(t) || t.includes(p))) {
        return _wordsToBbox([words[i]]);
      }
    }
    return null;
  }

  // Multi-token: anchor + tail.
  //   1. Find the seed (first ~6 tokens of the value) anywhere on the page —
  //      this anchors the *start* of the highlight.
  //   2. Find the tail (last ~6 tokens of the value) somewhere AFTER the
  //      seed — this anchors the *end* of the highlight.
  //   3. Union every word from start..end so the entire paragraph (line
  //      wraps and all) is covered.
  // If the tail can't be located, fall back to spanning the target length —
  // the user explicitly wants the full value highlighted, so over-covering a
  // few neighboring words is preferable to under-highlighting.
  const seedLen = Math.min(targetTokens.length, 6);
  const seed = targetTokens.slice(0, seedLen);
  const seedHit = _bestWindow(pageTokens, seed, 0);
  if (!seedHit) return null;

  const start = seedHit.start;
  const targetLen = targetTokens.length;
  // Default to highlighting only what we matched (the seed). Extending past
  // the seed without a confirmed tail anchor used to sweep in `targetLen`
  // worth of unrelated neighbors when the value's tail words appeared
  // elsewhere on the page or not at all.
  let endExclusive = Math.min(start + seedLen, words.length);

  // Tail search — only useful when the value has more tokens than the seed.
  if (targetLen > seedLen) {
    const tailLen = Math.min(targetLen - seedLen, 6);
    const tail = targetTokens.slice(targetLen - tailLen);
    const tailHit = _bestWindow(pageTokens, tail, start + seedLen);
    if (tailHit) {
      endExclusive = Math.min(tailHit.start + tailLen, words.length);
    }
  }

  // Sanity cap — never highlight more than 250 words from the seed.
  endExclusive = Math.min(endExclusive, start + 250, words.length);
  if (endExclusive <= start) endExclusive = Math.min(start + seedLen, words.length);

  const union = _wordsToBbox(words.slice(start, endExclusive));
  if (!union) return null;

  // Plausibility guard: a contiguous union that spans many lines almost
  // always means we joined a real seed match with words from a different
  // row/cell of the page (e.g. seed on line 1 + tail on line 6, with five
  // lines of unrelated content in between). Better to fall through to the
  // "precise location not detected" hint than render a confidently-wrong
  // rectangle.
  const wordHeights = words
    .map((w) => Math.max(0, w.y1 - w.y0))
    .filter((h) => h > 0)
    .sort((a, b) => a - b);
  const medianH =
    wordHeights.length > 0
      ? wordHeights[Math.floor(wordHeights.length / 2)]
      : 0;
  const [ux0, uy0, ux1, uy1] = union;
  const uw = Math.max(0, ux1 - ux0);
  const uh = Math.max(0, uy1 - uy0);
  if (medianH > 0 && uh > medianH * 6) return null;
  if (uw * uh > 0.35) return null;

  return union;
}

/**
 * Find the best-scoring contiguous window of `seed.length` tokens in
 * `pageTokens`, scanning from index `from` onward. Returns `{start, score}`
 * for the best window with score ≥ 0.5, or null.
 */
function _bestWindow(
  pageTokens: string[],
  seed: string[],
  from: number
): { start: number; score: number } | null {
  const winLen = seed.length;
  if (winLen === 0) return null;
  let bestStart = -1;
  let bestScore = 0;
  const limit = pageTokens.length - winLen + 1;
  for (let i = Math.max(0, from); i < limit; i++) {
    let hits = 0;
    for (let j = 0; j < winLen; j++) {
      const a = pageTokens[i + j];
      const b = seed[j];
      if (!a || !b) continue;
      if (a === b) {
        hits += 1;
      } else if (
        (a.length >= 3 || b.length >= 3) &&
        (a.includes(b) || b.includes(a))
      ) {
        hits += 0.6;
      }
    }
    const score = hits / winLen;
    if (score > bestScore) {
      bestScore = score;
      bestStart = i;
      if (score >= 0.999) break;
    }
  }
  if (bestStart < 0 || bestScore < 0.5) return null;
  return { start: bestStart, score: bestScore };
}

/** Lowercase + strip punctuation/whitespace; preserves digits, dots, slashes. */
function _normToken(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^\w.\-/]/g, "")
    .trim();
}

/** Splits target into normalized non-empty tokens. */
function _tokenize(s: string): string[] {
  // Collapse numeric thousand-separator commas first ("5,400" → "5400") so
  // "$5,400.00" ends up as a single page-aligned token.
  const cleaned = s.replace(/(\d),(?=\d{3}\b)/g, "$1");
  return cleaned
    .split(/[\s,;:|()\[\]{}'"`]+/)
    .map(_normToken)
    .filter((t) => t.length > 0);
}

/** Returns the union bbox `[x1, y1, x2, y2]` of a non-empty word list. */
function _wordsToBbox(slice: LoanPageWord[]): number[] | null {
  if (slice.length === 0) return null;
  let x0 = 1;
  let y0 = 1;
  let x1 = 0;
  let y1 = 0;
  for (const w of slice) {
    if (w.x0 < x0) x0 = w.x0;
    if (w.y0 < y0) y0 = w.y0;
    if (w.x1 > x1) x1 = w.x1;
    if (w.y1 > y1) y1 = w.y1;
  }
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

/**
 * Translucent amber overlay positioned by % offsets so it tracks the image
 * at any scale. Bbox is `[x1, y1, x2, y2]` normalized 0..1.
 */
function BboxOverlay({
  bbox,
  label,
}: {
  bbox: number[];
  label: string | null;
}) {
  const [x1, y1, x2, y2] = bbox;
  // Pad the box a hair on each side (0.5% horizontal, 0.3% vertical) so
  // the highlight visibly covers ascenders/descenders/whitespace instead
  // of clipping at the glyph baseline. Padding is applied BEFORE the
  // [0,1] clamp so the box never escapes the page edge.
  const PAD_X = 0.005;
  const PAD_Y = 0.003;
  const minX = Math.min(x1, x2) - PAD_X;
  const minY = Math.min(y1, y2) - PAD_Y;
  const maxX = Math.max(x1, x2) + PAD_X;
  const maxY = Math.max(y1, y2) + PAD_Y;
  // Defensive clamp — coordinates occasionally fall slightly outside [0,1]
  // when the source PDF was rotated or cropped pre-render, and after the
  // padding above.
  const left = Math.max(0, Math.min(1, minX)) * 100;
  const top = Math.max(0, Math.min(1, minY)) * 100;
  const right = Math.max(0, Math.min(1, maxX)) * 100;
  const bottom = Math.max(0, Math.min(1, maxY)) * 100;
  const width = Math.max(0, right - left);
  const height = Math.max(0, bottom - top);
  return (
    <div
      className="absolute pointer-events-none border-2 border-amber-500 bg-amber-400/25 rounded-sm shadow-[0_0_0_2px_rgba(255,255,255,0.6)]"
      style={{
        left: `${left}%`,
        top: `${top}%`,
        width: `${width}%`,
        height: `${height}%`,
      }}
      data-testid="workbench-bbox-overlay"
      aria-label={label ?? undefined}
    />
  );
}

// ──────────────────────────────────────────────────────────────────────
// Column 3 — Field list with pencil → save / cancel
// ──────────────────────────────────────────────────────────────────────
interface FieldsColumnProps {
  group: {
    stackId: string;
    docType: string;
    docTypeLabel: string;
    fields: WorkbenchFieldRow[];
  } | null;
  activeFieldKey: string | null;
  editingKey: string | null;
  /** When false, the pencil/edit affordance is disabled — used when the
   *  viewer has nothing to show (placeholder doc with no real stack), so
   *  starting an edit would orphan the user against an empty pane. */
  canEdit: boolean;
  fieldEdits: Record<string, string>;
  fieldSaved: Record<string, string>;
  fieldErrors: Record<string, string | null>;
  fieldBusy: Record<string, boolean>;
  onActivate: (row: WorkbenchFieldRow) => void;
  onBeginEdit: (row: WorkbenchFieldRow) => void;
  onChangeDraft: (row: WorkbenchFieldRow, value: string) => void;
  onSave: (row: WorkbenchFieldRow) => void | Promise<void>;
  onCancel: (row: WorkbenchFieldRow) => void;
}

function FieldsColumn({
  group,
  activeFieldKey,
  editingKey,
  canEdit,
  fieldEdits,
  fieldSaved,
  fieldErrors,
  fieldBusy,
  onActivate,
  onBeginEdit,
  onChangeDraft,
  onSave,
  onCancel,
}: FieldsColumnProps) {
  const getDraft = (row: WorkbenchFieldRow): string => {
    if (fieldEdits[row.key] !== undefined) return fieldEdits[row.key];
    if (fieldSaved[row.key] !== undefined) return fieldSaved[row.key];
    return row.originalValue ?? "";
  };

  return (
    <div
      className="flex flex-col bg-background"
      data-testid="workbench-fields-column"
    >
      <div className="px-4 py-3 border-b border-border/60 font-mono text-[9px] tracking-[0.2em] text-muted-foreground uppercase flex items-center justify-between gap-3">
        <span>Fields</span>
        {group && (
          <span className="font-mono text-[9px] text-muted-foreground tabular-nums normal-case tracking-normal">
            {group.fields.length} field
            {group.fields.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {!group || group.fields.length === 0 ? (
        <div className="px-4 py-8 text-[12px] text-muted-foreground italic text-center">
          {group ? "No fields configured for this doc." : "Select a document."}
        </div>
      ) : (
        <ul className="divide-y divide-border overflow-auto max-h-[600px]">
          {group.fields.map((row) => {
            const isActive = row.key === activeFieldKey;
            const isEditing = row.key === editingKey;
            const isSaved = fieldSaved[row.key] !== undefined;
            const isEdited = fieldEdits[row.key] !== undefined;
            const isBusy = fieldBusy[row.key] === true;
            const error = fieldErrors[row.key];
            const draft = getDraft(row);
            const wasMissing = row.status === "missing";
            const displayValue = isSaved
              ? fieldSaved[row.key]
              : row.originalValue ?? "";
            return (
              <li
                key={row.key}
                className={cn(
                  "transition-colors",
                  isActive ? "bg-amber-50/60" : "bg-transparent"
                )}
                data-testid={`workbench-field-row-${row.key}`}
              >
                <button
                  type="button"
                  onClick={() => onActivate(row)}
                  disabled={isEditing}
                  className={cn(
                    "w-full text-left px-4 py-3",
                    isEditing
                      ? "cursor-default"
                      : "hover:bg-muted/30 cursor-pointer",
                    "disabled:hover:bg-transparent"
                  )}
                  aria-current={isActive ? "true" : undefined}
                  aria-expanded={isEditing}
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <span className="font-serif text-[13px] text-foreground leading-tight truncate">
                      {row.fieldName}
                    </span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {isSaved && (
                        <span
                          className="font-mono text-[8px] tracking-[0.15em] uppercase px-1.5 py-0.5 rounded bg-emerald-500 text-white"
                          data-testid="workbench-saved-badge"
                        >
                          Saved
                        </span>
                      )}
                      {!isEditing && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (!canEdit) return;
                            onBeginEdit(row);
                          }}
                          disabled={!canEdit}
                          aria-label={`Edit ${row.fieldName}`}
                          title={
                            canEdit
                              ? "Edit"
                              : "No pages available for this document — nothing to review against"
                          }
                          className="h-6 w-6 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/60 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
                          data-testid="workbench-edit-pencil"
                        >
                          <Pencil className="h-3 w-3" strokeWidth={2} />
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-[8.5px] tracking-[0.12em] uppercase text-muted-foreground">
                      {row.fieldTypeLabel}
                    </span>
                    {wasMissing && !isSaved ? (
                      <span className="font-mono text-[9px] text-amber-600">
                        Not extracted
                      </span>
                    ) : (
                      row.confidence != null && (
                        <span className="font-mono text-[9px] text-muted-foreground tabular-nums">
                          conf {row.confidence}%
                        </span>
                      )
                    )}
                    {row.page != null && (
                      <span className="font-mono text-[9px] text-muted-foreground tabular-nums">
                        pg {row.page}
                      </span>
                    )}
                  </div>
                  {!isEditing && (
                    <div
                      className={cn(
                        "px-2.5 py-1.5 rounded-md font-mono text-[12px] min-h-[30px] flex items-center break-words whitespace-pre-wrap",
                        isSaved
                          ? "border border-emerald-200 bg-emerald-50/60 text-foreground"
                          : "border border-slate-200 bg-slate-50 text-slate-700"
                      )}
                    >
                      {displayValue ? (
                        displayValue
                      ) : (
                        <span className="text-slate-400 italic">
                          — no value —
                        </span>
                      )}
                    </div>
                  )}
                </button>

                {isEditing && (
                  <FieldEditor
                    row={row}
                    draft={draft}
                    error={error}
                    isBusy={isBusy}
                    isEdited={isEdited}
                    isSaved={isSaved}
                    onChange={(v) => onChangeDraft(row, v)}
                    onSave={() => onSave(row)}
                    onCancel={() => onCancel(row)}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

interface FieldEditorProps {
  row: WorkbenchFieldRow;
  draft: string;
  error: string | null | undefined;
  isBusy: boolean;
  isEdited: boolean;
  isSaved: boolean;
  onChange: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
}

function FieldEditor({
  row,
  draft,
  error,
  isBusy,
  isEdited,
  isSaved,
  onChange,
  onSave,
  onCancel,
}: FieldEditorProps) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  // Auto-grow + autofocus when the editor opens.
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.focus();
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, []);
  return (
    <div
      className="px-4 pb-4 -mt-1"
      data-testid="workbench-field-editor"
    >
      {row.originalValue && (
        <div className="mb-2">
          <div className="font-mono text-[8px] tracking-[0.2em] text-slate-500 uppercase mb-1">
            From document
          </div>
          <div className="px-2.5 py-1.5 border border-slate-200 bg-slate-50 rounded-md font-mono text-[11px] text-slate-700 break-words whitespace-pre-wrap">
            {row.originalValue}
          </div>
        </div>
      )}
      <div className="font-mono text-[8px] tracking-[0.2em] text-amber-700 uppercase mb-1">
        Reviewed value
      </div>
      <textarea
        ref={taRef}
        value={draft}
        onChange={(e) => {
          onChange(e.target.value);
          const el = e.currentTarget;
          el.style.height = "auto";
          el.style.height = `${el.scrollHeight}px`;
        }}
        onKeyDown={(e) => {
          // Cmd/Ctrl-Enter saves, Esc cancels — keyboard parity with Slack
          // / Linear-style inline editors.
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            onSave();
          } else if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        placeholder="Enter value…"
        disabled={isBusy}
        rows={1}
        className={cn(
          "w-full px-2.5 py-1.5 border rounded-md font-mono text-[12px] text-foreground min-h-[32px] resize-none overflow-hidden whitespace-pre-wrap break-words focus:outline-none focus:ring-2 transition-colors disabled:opacity-60",
          error
            ? "border-destructive bg-red-50/50 focus:border-destructive focus:ring-destructive/20"
            : "border-amber-200 bg-amber-50/40 focus:border-amber-500 focus:bg-white focus:ring-amber-500/20 placeholder:text-amber-700/40"
        )}
        data-testid="workbench-field-input"
      />
      {error && (
        <div className="mt-1.5 text-[11px] text-destructive flex items-start gap-1.5">
          <AlertCircle className="h-3 w-3 mt-0.5 shrink-0" />
          {error}
        </div>
      )}
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={isBusy}
          aria-label={isBusy ? "Saving" : "Save"}
          title={isBusy ? "Saving…" : "Save (⌘↵)"}
          className="h-7 px-2.5 inline-flex items-center gap-1 bg-emerald-500 text-white text-[11px] font-medium rounded-md shadow-sm hover:bg-emerald-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          data-testid="workbench-field-save"
        >
          <Check className="h-3 w-3" strokeWidth={2.5} /> Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          // Cancel's primary job is to close the editor — it must always
          // be live in edit mode, regardless of whether the user has typed
          // or previously saved. Only block while a save is in flight.
          disabled={isBusy}
          aria-label="Cancel"
          title="Cancel (Esc)"
          className="h-7 px-2.5 inline-flex items-center gap-1 bg-background border border-border text-foreground text-[11px] font-medium rounded-md hover:bg-muted/40 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid="workbench-field-cancel"
        >
          <X className="h-3 w-3" strokeWidth={2.5} /> Cancel
        </button>
      </div>
    </div>
  );
}
