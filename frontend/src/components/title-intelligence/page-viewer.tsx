"use client";

import type { PageData } from "@/lib/ti-types";

export function PageViewer({
  pages,
  baseUrl,
  packId,
}: {
  pages: PageData[];
  baseUrl: string;
  packId: string;
}) {
  if (pages.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No pages yet. Process the pack to render pages.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-4 gap-4">
      {pages.map((page) => (
        <div key={page.id} className="space-y-1">
          <div className="aspect-[8.5/11] rounded border overflow-hidden bg-muted">
            <img
              src={`${baseUrl}/api/v1/apps/title-intelligence/packs/${packId}/pages/${page.page_number}/thumb`}
              alt={`Page ${page.page_number}`}
              className="w-full h-full object-contain"
            />
          </div>
          <p className="text-xs text-center text-muted-foreground">
            Page {page.page_number}
          </p>
        </div>
      ))}
    </div>
  );
}
