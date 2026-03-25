"use client";

import { useEffect } from "react";
import { X, MessageSquare, Trash2 } from "lucide-react";
import { ChatPanel } from "./chat-panel";
import { useChat } from "@/hooks/use-chat";
import { useFocusTrap } from "@/hooks/use-focus-trap";

export function ChatSlidePanel({
  packId,
  open,
  onClose,
  initialQuestion,
}: {
  packId: string;
  open: boolean;
  onClose: () => void;
  initialQuestion?: string;
}) {
  const { messages, sending, sendMessage, cancelStream, clearChat } = useChat(packId);

  // Auto-send initialQuestion when panel opens with one
  useEffect(() => {
    if (open && initialQuestion && !sending) {
      sendMessage(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialQuestion]);
  const trapRef = useFocusTrap(open);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="AI Chat"
        className="fixed right-0 top-0 z-50 h-full w-[440px] max-w-full bg-background border-l shadow-2xl flex flex-col animate-in slide-in-from-right duration-200"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-primary" />
            <h3 className="font-semibold text-sm">AI Chat</h3>
          </div>
          <div className="flex items-center gap-1">
            {messages.length > 0 && (
              <button
                onClick={clearChat}
                aria-label="Clear chat"
                className="rounded-full p-1.5 text-muted-foreground hover:bg-red-50 hover:text-red-600 transition-colors"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
            <button
              onClick={onClose}
              aria-label="Close chat"
              className="rounded-full p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Chat content */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <ChatPanel
            messages={messages}
            sending={sending}
            onSend={sendMessage}
            onCancel={cancelStream}
            packId={packId}
          />
        </div>
      </div>
    </>
  );
}
