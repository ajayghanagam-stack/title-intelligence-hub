"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send } from "lucide-react";
import { ChatMessageBubble } from "./chat-message";
import { SuggestedQuestions } from "./suggested-questions";
import type { ChatMessage } from "@/lib/ti-types";

export function ChatPanel({
  messages,
  sending,
  onSend,
  onCancel,
  packId,
}: {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (message: string) => void;
  onCancel?: () => void;
  packId?: string;
}) {
  const [input, setInput] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;
    onSend(input.trim());
    setInput("");
  };

  const handleSuggestion = (question: string) => {
    if (sending) return;
    onSend(question);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto space-y-4 p-4" aria-live="polite" aria-label="Chat messages">
        {messages.length === 0 && (
          <SuggestedQuestions onSelect={handleSuggestion} />
        )}
        {messages.map((msg) => (
          <ChatMessageBubble key={msg.id} message={msg} packId={packId} />
        ))}
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 border-t bg-muted/30 px-4 py-5 shrink-0"
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about this document..."
          aria-label="Chat message"
          disabled={sending}
          className="flex-1 min-w-0 h-12 bg-background"
        />
        {sending && onCancel ? (
          <Button type="button" variant="outline" size="icon" onClick={onCancel} aria-label="Stop generating">
            <span className="h-4 w-4 block rounded-sm bg-foreground" />
          </Button>
        ) : (
          <Button type="submit" size="icon" disabled={sending || !input.trim()} aria-label="Send message">
            <Send className="h-4 w-4" />
          </Button>
        )}
      </form>
    </div>
  );
}
