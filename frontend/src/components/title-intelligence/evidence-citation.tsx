"use client";

import { FileText } from "lucide-react";
import type { EvidenceRef } from "@/lib/ti-types";

export function EvidenceCitation({ refs }: { refs: EvidenceRef[] }) {
  if (refs.length === 0) return null;

  return (
    <div className="space-y-2">
      {refs.map((ref, i) => (
        <div
          key={i}
          className="flex items-start gap-2 rounded bg-muted p-2 text-xs"
        >
          <FileText className="mt-0.5 h-3 w-3 flex-shrink-0 text-muted-foreground" />
          <div>
            <span className="font-medium">Page {ref.page_number}</span>
            {ref.text_snippet && (
              <p className="mt-0.5 text-muted-foreground">{ref.text_snippet}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
