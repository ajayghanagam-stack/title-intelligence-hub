"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { SECTION_TYPE_LABELS } from "@/lib/ti-constants";
import type { PageData, Section } from "@/lib/ti-types";

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
  const srcRef = useRef<string | null>(null);

  useEffect(() => {
    let revoked = false;
    apiFetchBlob(path, { orgId })
      .then((blob) => {
        if (!revoked) {
          const url = URL.createObjectURL(blob);
          srcRef.current = url;
          setSrc(url);
        }
      })
      .catch(() => { /* Image load failure is non-critical — placeholder shown */ });
    return () => {
      revoked = true;
      if (srcRef.current) URL.revokeObjectURL(srcRef.current);
    };
  }, [path, orgId]);

  if (!src) {
    return <div className={`${className} bg-muted animate-pulse`} />;
  }

  return <img src={src} alt={alt} className={className} />;
}

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

  const { showToast } = useToast();
  const thumbsRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch pages
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
      })
      .catch(() => { setPages([]); showToast("error", "Failed to load pages"); })
      .finally(() => setLoading(false));
  }, [orgFetch, packId, searchParams]);

  // Fetch sections
  useEffect(() => {
    orgFetch<Section[]>(`/api/v1/apps/title-intelligence/packs/${packId}/sections`)
      .then((data) => setSections(data))
      .catch(() => { setSections([]); showToast("error", "Failed to load sections"); });
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
      router.replace(
        `/apps/title-intelligence/packs/${packId}/documents?page=${num}`,
        { scroll: false }
      );
    },
    [router, packId]
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading pages...</p>
      </div>
    );
  }

  if (pages.length === 0) {
    return (
      <div className="rounded-xl border-2 border-dashed p-12 text-center">
        <p className="text-muted-foreground">
          No pages available. Process the pack first to render document pages.
        </p>
      </div>
    );
  }

  const currentPage = pages.find((p) => p.page_number === selectedPage);

  return (
    <div ref={containerRef} className="flex gap-0 h-[calc(100vh-14rem)]">
      {/* Left: thumbnail strip */}
      <div
        ref={thumbsRef}
        className="w-20 shrink-0 overflow-y-auto border-r bg-muted/20 p-1.5 space-y-1.5"
      >
        {pages.map((page) => (
          <button
            key={page.id}
            data-page={page.page_number}
            onClick={() => goToPage(page.page_number)}
            className={`block w-full rounded border-2 overflow-hidden transition-all ${
              selectedPage === page.page_number
                ? "border-primary ring-2 ring-primary/20"
                : "border-transparent hover:border-muted-foreground/30"
            }`}
          >
            {currentOrgId && (
              <AuthImage
                path={`/api/v1/apps/title-intelligence/packs/${packId}/pages/${page.page_number}/thumb`}
                orgId={currentOrgId}
                alt={`Page ${page.page_number}`}
                className="w-full"
              />
            )}
            <p className="text-[10px] text-center py-0.5 bg-muted font-medium">
              {page.page_number}
            </p>
          </button>
        ))}
      </div>

      {/* Sections panel: between thumbnails and viewer */}
      {showSections && (
        <div className="w-52 shrink-0 overflow-y-auto border-r bg-background">
          <div className="px-3 py-2.5 border-b bg-muted/30">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5" />
              Sections
            </h3>
          </div>
          <div className="divide-y">
            {sections.length === 0 ? (
              <p className="px-3 py-3 text-xs text-muted-foreground">
                No sections detected.
              </p>
            ) : (
              sections.map((section) => (
                <button
                  key={section.id}
                  onClick={() => goToPage(section.start_page)}
                  className={`w-full text-left px-3 py-2.5 hover:bg-muted/30 transition-colors ${
                    selectedPage >= section.start_page &&
                    selectedPage <= section.end_page
                      ? "bg-primary/5 border-l-2 border-l-primary"
                      : ""
                  }`}
                >
                  <div className="text-sm font-medium">
                    {SECTION_TYPE_LABELS[section.section_type] || section.title}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    Pages {section.start_page}–{section.end_page}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Center: main viewer */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b px-3 py-2">
          <div className="flex items-center gap-1.5">
            <Button
              variant={showSections ? "default" : "outline"}
              size="sm"
              className="h-8"
              onClick={() => setShowSections(!showSections)}
            >
              <Layers className="mr-1.5 h-3.5 w-3.5" />
              Sections
            </Button>
            <Button
              variant={showOcr ? "default" : "outline"}
              size="sm"
              className="h-8"
              onClick={() => setShowOcr(!showOcr)}
            >
              {showOcr ? (
                <EyeOff className="mr-1.5 h-3.5 w-3.5" />
              ) : (
                <Eye className="mr-1.5 h-3.5 w-3.5" />
              )}
              OCR Text
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={() => goToPage(selectedPage - 1)}
              disabled={selectedPage <= 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm font-medium min-w-[100px] text-center">
              Page {selectedPage} of {pages.length}
            </span>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={() => goToPage(selectedPage + 1)}
              disabled={selectedPage >= pages.length}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-auto flex gap-0">
          {/* Image */}
          <div
            className={`${
              showOcr ? "w-3/5" : "w-full"
            } flex items-start justify-center overflow-auto p-4 bg-muted/10`}
          >
            {currentOrgId && (
              <AuthImage
                path={`/api/v1/apps/title-intelligence/packs/${packId}/pages/${selectedPage}/image`}
                orgId={currentOrgId}
                alt={`Page ${selectedPage}`}
                className="max-w-full border shadow-sm"
              />
            )}
          </div>

          {/* Right panel: OCR text */}
          {showOcr && currentPage && (
            <div className="w-2/5 border-l overflow-y-auto">
              <div className="ocr-text-overlay p-4">
                <div className="flex items-center gap-1.5 mb-2">
                  <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    OCR Text — Page {selectedPage}
                  </h3>
                </div>
                <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed text-muted-foreground">
                  {currentPage.ocr_text ||
                    "No OCR text available for this page."}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
