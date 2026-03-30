"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useOrg } from "@/hooks/use-org";
import { apiFetchBlob } from "@/lib/api";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  Layers,
  Eye,
  EyeOff,
  ZoomIn,
  ZoomOut,
  Maximize2,
  FileSearch,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { SECTION_TYPE_LABELS } from "@/lib/ti-constants";
import type { PageData, Section } from "@/lib/ti-types";

/* ── Authenticated image loader ── */
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
  const srcRef = useRef<string | null>(null);

  useEffect(() => {
    let revoked = false;
    setError(false);
    setSrc(null);
    
    apiFetchBlob(path, { orgId })
      .then((blob) => {
        if (!revoked) {
          const url = URL.createObjectURL(blob);
          srcRef.current = url;
          setSrc(url);
        }
      })
      .catch((err) => {
        console.error(`Failed to load image ${path}:`, err);
        if (!revoked) {
          setError(true);
        }
      });
    return () => {
      revoked = true;
      if (srcRef.current) URL.revokeObjectURL(srcRef.current);
    };
  }, [path, orgId]);

  if (error) {
    return (
      <div className={cn("bg-red-50 flex items-center justify-center text-red-400", className)} style={style}>
        <FileSearch className="h-6 w-6" />
      </div>
    );
  }

  if (!src) {
    return <div className={cn("bg-muted/40 animate-pulse rounded", className)} style={style} />;
  }

  return <img src={src} alt={alt} className={className} style={style} />;
}

/* ── Zoom levels ── */
const ZOOM_LEVELS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const DEFAULT_ZOOM_INDEX = 2; // 100%

export default function DocumentsPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const packId = params.packId as string;
  const { orgFetch, currentOrgId } = useOrg();

  const [pages, setPages] = useState<PageData[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPage, setSelectedPage] = useState<number>(1);
  const [showOcr, setShowOcr] = useState(false);
  const [showSections, setShowSections] = useState(false);
  const [zoomIndex, setZoomIndex] = useState(DEFAULT_ZOOM_INDEX);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [highlightSnippet, setHighlightSnippet] = useState<string | null>(null);

  const { showToast } = useToast();
  const thumbsRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLElement | null>(null);

  const zoom = ZOOM_LEVELS[zoomIndex];

  // Fetch pages and trigger pre-rendering
  useEffect(() => {
    orgFetch<PageData[]>(`/api/v1/apps/title-intelligence/packs/${packId}/pages`)
      .then((data) => {
        setPages(data);
        const pageParam = searchParams.get("page");
        if (pageParam) {
          const num = parseInt(pageParam, 10);
          if (num >= 1 && num <= data.length) {
            setSelectedPage(num);
          }
        } else if (data.length > 0) {
          setSelectedPage(data[0].page_number);
        }

        const snippet = searchParams.get("highlight");
        if (snippet) {
          setHighlightSnippet(snippet);
          setShowOcr(true);
        }
        
        // Trigger pre-rendering of first 20 pages in background
        if (data.length > 0) {
          orgFetch(`/api/v1/apps/title-intelligence/packs/${packId}/pages/prerender?start_page=1&count=20`, {
            method: 'POST'
          }).catch(() => {}); // Silently fail if pre-render doesn't work
        }
      })
      .catch(() => { setPages([]); showToast("error", "Failed to load pages"); })
      .finally(() => setLoading(false));
  }, [orgFetch, packId, searchParams]);

  // Scroll to highlighted text once OCR panel renders it
  useEffect(() => {
    if (highlightSnippet && showOcr && highlightRef.current) {
      highlightRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [highlightSnippet, showOcr, selectedPage]);

  // Fetch sections
  useEffect(() => {
    orgFetch<Section[]>(`/api/v1/apps/title-intelligence/packs/${packId}/sections`)
      .then((data) => setSections(data))
      .catch(() => { setSections([]); });
  }, [orgFetch, packId]);

  // Keyboard navigation
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowLeft" && selectedPage > 1) {
        setSelectedPage((p) => p - 1);
      } else if (e.key === "ArrowRight" && selectedPage < pages.length) {
        setSelectedPage((p) => p + 1);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [selectedPage, pages.length]);

  // Scroll thumbnail into view
  useEffect(() => {
    if (thumbsRef.current) {
      const activeThumb = thumbsRef.current.querySelector(
        `[data-page="${selectedPage}"]`
      );
      activeThumb?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedPage]);

  const goToPage = useCallback(
    (num: number) => {
      setSelectedPage(num);
      setActiveSectionId(null);
      router.replace(
        `/apps/title-intelligence/packs/${packId}/documents?page=${num}`,
        { scroll: false }
      );
    },
    [router, packId]
  );

  const goToSection = useCallback(
    (section: Section) => {
      setSelectedPage(section.start_page);
      setActiveSectionId(section.id);
      router.replace(
        `/apps/title-intelligence/packs/${packId}/documents?page=${section.start_page}`,
        { scroll: false }
      );
    },
    [router, packId]
  );

  // Section for the current page — prefer the explicitly clicked section,
  // fall back to the most specific (latest-starting) section containing this page
  const currentSection = activeSectionId
    ? sections.find((s) => s.id === activeSectionId)
    : [...sections]
        .filter((s) => selectedPage >= s.start_page && selectedPage <= s.end_page)
        .sort((a, b) => b.start_page - a.start_page)[0] || null;

  // Split OCR text around the highlight snippet for rendering
  const ocrParts = useMemo(() => {
    const text = pages.find((p) => p.page_number === selectedPage)?.ocr_text ?? "";
    if (!highlightSnippet || !text) return null;
    const idx = text.indexOf(highlightSnippet);
    if (idx === -1) return null;
    return {
      before: text.slice(0, idx),
      match: text.slice(idx, idx + highlightSnippet.length),
      after: text.slice(idx + highlightSnippet.length),
    };
  }, [pages, selectedPage, highlightSnippet]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh] gap-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading pages...</p>
      </div>
    );
  }

  if (pages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50">
          <FileSearch className="h-8 w-8 text-muted-foreground/50" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">No pages available</p>
          <p className="text-xs text-muted-foreground mt-1">
            Process the pack first to render document pages.
          </p>
        </div>
      </div>
    );
  }

  const currentPage = pages.find((p) => p.page_number === selectedPage);

  return (
    <div className="flex gap-0 h-[calc(100vh-8rem)] rounded-xl border bg-card overflow-hidden shadow-sm">
      {/* ── Left: Thumbnail strip ── */}
      <div
        ref={thumbsRef}
        className="w-[88px] shrink-0 overflow-y-auto border-r bg-muted/30 p-2 space-y-2 scrollbar-thin"
      >
        {pages.map((page) => {
          const isActive = selectedPage === page.page_number;
          const pageSection = sections.find(
            (s) => page.page_number >= s.start_page && page.page_number <= s.end_page
          );
          return (
            <button
              key={page.id}
              data-page={page.page_number}
              onClick={() => goToPage(page.page_number)}
              className={cn(
                "group relative block w-full rounded-lg overflow-hidden transition-all",
                isActive
                  ? "ring-2 ring-primary shadow-md"
                  : "ring-1 ring-border hover:ring-primary/40 hover:shadow-sm"
              )}
            >
              {currentOrgId && (
                <AuthImage
                  path={`/api/v1/apps/title-intelligence/packs/${packId}/pages/${page.page_number}/thumb`}
                  orgId={currentOrgId}
                  alt={`Page ${page.page_number}`}
                  className="w-full aspect-[8.5/11] object-cover"
                />
              )}
              <div className={cn(
                "flex items-center justify-center gap-1 py-1 text-[10px] font-semibold transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted/60 text-muted-foreground group-hover:bg-muted"
              )}>
                {page.page_number}
                {page.page_type && page.page_type !== "content" && (
                  <span className={cn(
                    "text-[8px] px-1 rounded font-medium leading-none",
                    page.page_type === "blank" && "bg-gray-200 text-gray-500",
                    page.page_type === "cover" && "bg-blue-100 text-blue-600",
                    page.page_type === "signature" && "bg-amber-100 text-amber-600",
                    !["blank", "cover", "signature"].includes(page.page_type) && "bg-muted text-muted-foreground",
                  )}>
                    {page.page_type}
                  </span>
                )}
              </div>
              {/* Section indicator dot */}
              {pageSection && (
                <div className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-amber-400 ring-1 ring-white" />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Sections panel ── */}
      {showSections && (
        <div className="w-56 shrink-0 overflow-y-auto border-r bg-background">
          <div className="px-4 py-3 border-b bg-gradient-to-r from-muted/40 to-transparent">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Layers className="h-3.5 w-3.5" />
              Document Sections
            </h3>
          </div>
          {sections.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <Layers className="h-5 w-5 text-muted-foreground/30 mx-auto mb-2" />
              <p className="text-xs text-muted-foreground">No sections detected.</p>
            </div>
          ) : (
            <div className="py-1">
              {sections.map((section) => {
                const isActive = currentSection?.id === section.id;
                return (
                  <button
                    key={section.id}
                    onClick={() => goToSection(section)}
                    className={cn(
                      "w-full text-left px-4 py-2.5 transition-all",
                      isActive
                        ? "bg-amber-50 border-l-[3px] border-l-amber-500"
                        : "border-l-[3px] border-l-transparent hover:bg-muted/30"
                    )}
                  >
                    <div className={cn(
                      "text-[13px] font-medium leading-tight",
                      isActive ? "text-amber-800" : "text-foreground/80"
                    )}>
                      {SECTION_TYPE_LABELS[section.section_type] || section.section_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </div>
                    <div className={cn(
                      "text-[11px] mt-0.5",
                      isActive ? "text-amber-600/60" : "text-muted-foreground"
                    )}>
                      {section.start_page === section.end_page
                        ? `Page ${section.start_page}`
                        : `Pages ${section.start_page} - ${section.end_page}`}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Center: main viewer ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b bg-card px-4 py-2 gap-4">
          {/* Left: toggle buttons */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setShowSections(!showSections)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all",
                showSections
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <Layers className="h-3.5 w-3.5" />
              Sections
            </button>
            <button
              onClick={() => setShowOcr(!showOcr)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all",
                showOcr
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              {showOcr ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              OCR Text
            </button>
          </div>

          {/* Center: page navigation */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => goToPage(selectedPage - 1)}
              disabled={selectedPage <= 1}
              className="inline-flex items-center justify-center h-8 w-8 rounded-md border bg-card text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-30 disabled:pointer-events-none"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-1.5 px-2 min-w-[120px] justify-center">
              <span className="text-sm font-semibold text-foreground">{selectedPage}</span>
              <span className="text-xs text-muted-foreground">of {pages.length}</span>
            </div>
            <button
              onClick={() => goToPage(selectedPage + 1)}
              disabled={selectedPage >= pages.length}
              className="inline-flex items-center justify-center h-8 w-8 rounded-md border bg-card text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-30 disabled:pointer-events-none"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* Right: zoom + section badge */}
          <div className="flex items-center gap-2">
            {currentSection && (
              <span className="hidden lg:inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200/60">
                {SECTION_TYPE_LABELS[currentSection.section_type] || currentSection.section_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </span>
            )}
            <div className="flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
              <button
                onClick={() => setZoomIndex((i) => Math.max(0, i - 1))}
                disabled={zoomIndex <= 0}
                className="inline-flex items-center justify-center h-7 w-7 rounded text-muted-foreground hover:bg-card hover:text-foreground transition-colors disabled:opacity-30"
              >
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <span className="text-[11px] font-medium text-muted-foreground min-w-[36px] text-center">
                {Math.round(zoom * 100)}%
              </span>
              <button
                onClick={() => setZoomIndex((i) => Math.min(ZOOM_LEVELS.length - 1, i + 1))}
                disabled={zoomIndex >= ZOOM_LEVELS.length - 1}
                className="inline-flex items-center justify-center h-7 w-7 rounded text-muted-foreground hover:bg-card hover:text-foreground transition-colors disabled:opacity-30"
              >
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setZoomIndex(DEFAULT_ZOOM_INDEX)}
                className="inline-flex items-center justify-center h-7 w-7 rounded text-muted-foreground hover:bg-card hover:text-foreground transition-colors"
                title="Reset zoom"
              >
                <Maximize2 className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-hidden flex">
          {/* Image viewport */}
          <div
            className={cn(
              "overflow-auto flex items-start justify-center bg-gradient-to-b from-muted/20 to-muted/5",
              showOcr ? "w-3/5" : "w-full"
            )}
          >
            <div className="p-6" style={{ minWidth: "fit-content" }}>
              {currentOrgId && (
                <AuthImage
                  path={`/api/v1/apps/title-intelligence/packs/${packId}/pages/${selectedPage}/image`}
                  orgId={currentOrgId}
                  alt={`Page ${selectedPage}`}
                  className="rounded-sm border shadow-lg bg-white transition-transform duration-200"
                  style={{
                    transform: `scale(${zoom})`,
                    transformOrigin: "top center",
                  }}
                />
              )}
            </div>
          </div>

          {/* OCR text panel */}
          {showOcr && currentPage && (
            <div className="w-2/5 border-l overflow-y-auto bg-background">
              <div className="sticky top-0 z-10 flex items-center gap-2 px-4 py-2.5 border-b bg-gradient-to-r from-muted/40 to-transparent backdrop-blur-sm">
                <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  OCR Text
                </h3>
                <span className="text-[10px] text-muted-foreground/60 ml-auto">
                  Page {selectedPage}
                </span>
              </div>
              <div className="ocr-text-overlay p-4">
                {currentPage.ocr_text ? (
                  <pre className="text-[13px] whitespace-pre-wrap font-mono leading-relaxed text-foreground/70 selection:bg-amber-200/40">
                    {ocrParts ? (
                      <>
                        {ocrParts.before}
                        <mark
                          ref={(el) => { highlightRef.current = el; }}
                          className="bg-amber-300/70 text-amber-950 rounded-sm px-0.5 not-italic font-semibold"
                        >
                          {ocrParts.match}
                        </mark>
                        {ocrParts.after}
                      </>
                    ) : (
                      currentPage.ocr_text
                    )}
                  </pre>
                ) : (
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <FileText className="h-6 w-6 text-muted-foreground/30 mb-2" />
                    <p className="text-xs text-muted-foreground">
                      No OCR text available for this page.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
