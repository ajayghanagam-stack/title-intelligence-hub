"use client";

import { CitationBadge } from "./citation-badge";
import type { ChatMessage, EvidenceRef } from "@/lib/ti-types";

export function ChatMessageBubble({
  message,
  packId,
  totalPages,
}: {
  message: ChatMessage;
  packId?: string;
  totalPages?: number;
}) {
  const isUser = message.role === "user";

  // Filter citations to only pages that exist in the document
  const validCitations = (message.citations ?? []).filter(
    (cit) => cit.page_number >= 1 && (!totalPages || cit.page_number <= totalPages)
  );

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
          isUser
            ? "bg-primary text-primary-foreground rounded-br-md"
            : "bg-muted rounded-bl-md"
        }`}
      >
        <p className="text-sm whitespace-pre-wrap leading-relaxed">
          {message.content}
        </p>
        {!isUser && validCitations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {validCitations.map((cit, i) =>
              packId ? (
                <CitationBadge
                  key={i}
                  pageNumber={cit.page_number}
                  packId={packId}
                />
              ) : (
                <span
                  key={i}
                  className="inline-flex items-center gap-1 rounded-full bg-black/10 px-2 py-0.5 text-xs"
                >
                  Page {cit.page_number}
                </span>
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
