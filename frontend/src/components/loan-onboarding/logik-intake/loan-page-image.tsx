"use client";

// Phase 5 closing — page-image renderer for the classify + extract screens.
//
// LO ingest doesn't pre-render page JPEGs (it stores metadata-only LOPage
// rows), so the backend route at
//   GET /api/v1/apps/loan-onboarding/packages/{packageId}/pages/{pageId}/image
// renders on demand via PyMuPDF and caches the JPEG to storage. This
// component is the auth-blob loader — same shape as the TI `AuthImage` —
// that pulls the JPEG via `apiFetchBlob` (so the JWT + X-Org-Id headers
// land) and turns it into a URL-from-blob the <img> can render.
//
// `loanId` is reused as the package_id (the /loans alias maps 1:1 to the
// /packages prefix on the backend). `pageId` is the LOPage UUID surfaced
// on each `LoanStackPage` record.

import { useEffect, useRef, useState } from "react";
import { FileSearch } from "lucide-react";

import { apiFetchBlob } from "@/lib/api";
import { useOrg } from "@/hooks/use-org";
import { cn } from "@/lib/utils";

const BASE = "/api/v1/apps/loan-onboarding";

export function LoanPageImage({
  loanId,
  pageId,
  alt,
  className,
}: {
  loanId: string;
  pageId: string | null | undefined;
  alt: string;
  className?: string;
}) {
  const { currentOrgId } = useOrg();
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<boolean>(false);
  const srcRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    setSrc(null);
    if (!currentOrgId || !pageId) return;
    const path = `${BASE}/packages/${loanId}/pages/${pageId}/image`;
    apiFetchBlob(path, { orgId: currentOrgId })
      .then((blob) => {
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        srcRef.current = url;
        setSrc(url);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      if (srcRef.current) {
        URL.revokeObjectURL(srcRef.current);
        srcRef.current = null;
      }
    };
  }, [loanId, pageId, currentOrgId]);

  if (!pageId) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-muted/30 text-xs text-muted-foreground",
          className
        )}
      >
        No page selected
      </div>
    );
  }
  if (error) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-destructive/5 text-destructive",
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
        className={cn("animate-pulse bg-muted/40", className)}
        aria-label="Loading page image"
      />
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      className={cn("h-full w-full object-contain", className)}
    />
  );
}
