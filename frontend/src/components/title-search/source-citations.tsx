"use client";

import { ExternalLink, Globe } from "lucide-react";

interface Citation {
  url: string;
  title: string;
}

interface SourceCitationsProps {
  citations: Citation[];
}

export function SourceCitations({ citations }: SourceCitationsProps) {
  if (citations.length === 0) {
    return null;
  }

  return (
    <div className="card-warm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 bg-gradient-to-r from-amber-50 to-amber-100/60 border-b border-amber-200/40">
        <Globe className="h-4 w-4 text-amber-700" />
        <span className="text-sm font-semibold text-amber-900">
          Sources ({citations.length})
        </span>
      </div>
      <ul className="divide-y divide-amber-100/50">
        {citations.map((citation, idx) => (
          <li key={idx} className="px-4 py-2.5 hover:bg-amber-50/30 transition-colors">
            <a
              href={citation.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-2 group"
            >
              <ExternalLink className="h-3.5 w-3.5 mt-0.5 shrink-0 text-amber-500 group-hover:text-amber-700 transition-colors" />
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground group-hover:text-amber-800 transition-colors truncate">
                  {citation.title}
                </p>
                <p className="text-[11px] text-muted-foreground truncate mt-0.5">
                  {citation.url}
                </p>
              </div>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
