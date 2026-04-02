"use client";

import Link from "next/link";
import { FileText } from "lucide-react";

export function CitationBadge({
  pageNumber,
  packId,
}: {
  pageNumber: number;
  packId: string;
}) {
  const params = new URLSearchParams({ page: String(pageNumber) });

  return (
    <Link
      href={`/apps/title-intelligence/packs/${packId}/documents?${params.toString()}`}
      className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20 transition-colors"
    >
      <FileText className="h-3 w-3" />
      Page {pageNumber}
    </Link>
  );
}
