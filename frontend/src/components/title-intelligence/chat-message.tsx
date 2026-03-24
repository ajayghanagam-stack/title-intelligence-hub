"use client";

import { CitationBadge } from "./citation-badge";
import type { ChatMessage } from "@/lib/ti-types";

export function ChatMessageBubble({
  message,
  packId,
}: {
  message: ChatMessage;
  packId?: string;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 ${
          isUser
            ? "bg-primary text-primary-foreground rounded-br-md"
            : "bg-muted rounded-bl-md"
        }`}
      >
        <p className="text-sm whitespace-pre-wrap leading-relaxed">{message.content}</p>
        {message.citations && message.citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {message.citations.map((cit, i) =>
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
                  {cit.text_snippet && `: ${cit.text_snippet.slice(0, 80)}...`}
                </span>
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
