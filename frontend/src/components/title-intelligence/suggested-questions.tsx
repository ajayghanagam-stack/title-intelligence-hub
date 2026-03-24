"use client";

import { SUGGESTED_QUESTIONS } from "@/lib/ti-constants";
import { MessageSquare } from "lucide-react";

export function SuggestedQuestions({
  onSelect,
}: {
  onSelect: (question: string) => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 mb-3">
        <MessageSquare className="h-6 w-6 text-primary" />
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Ask a question about this title document.
      </p>
      <div className="flex flex-wrap justify-center gap-2 max-w-md">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className="rounded-full border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs text-foreground hover:bg-primary/10 hover:border-primary/40 transition-all"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
