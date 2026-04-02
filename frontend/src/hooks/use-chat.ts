"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useOrg } from "./use-org";
import { getToken } from "@/lib/auth";
import { API_URL } from "@/lib/config";
import type { ChatMessage } from "@/lib/ti-types";

/**
 * Chat hook with an extended return shape: { messages, loading, sending,
 * sendMessage, cancelStream, clearChat, refetch }. Unlike standard data hooks
 * that return { data, loading, refetch }, this hook manages bidirectional
 * streaming state (sending, cancelStream) and optimistic message updates.
 */
export function useChat(packId: string) {
  const { orgFetch, currentOrgId } = useOrg();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const fetchHistory = useCallback(async () => {
    try {
      const data = await orgFetch<ChatMessage[]>(
        `/api/v1/apps/title-intelligence/packs/${packId}/chat`
      );
      setMessages(data);
    } catch {
      setMessages([]);
    } finally {
      setLoading(false);
    }
  }, [orgFetch, packId]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const sendMessage = async (message: string) => {
    setSending(true);

    // Add optimistic user message
    const userMsg: ChatMessage = {
      id: Math.random().toString(36).slice(2) + Date.now().toString(36),
      pack_id: packId,
      role: "user",
      content: message,
      citations: null,
      user_id: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    // Add placeholder assistant message for streaming
    const assistantId = Math.random().toString(36).slice(2) + Date.now().toString(36);
    const assistantMsg: ChatMessage = {
      id: assistantId,
      pack_id: packId,
      role: "assistant",
      content: "",
      citations: null,
      user_id: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      // Get auth token
      const token = getToken();

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      if (currentOrgId) {
        headers["X-Org-Id"] = currentOrgId;
      }

      // Create abort controller for cancellation
      abortControllerRef.current = new AbortController();

      const response = await fetch(
        `${API_URL}/api/v1/apps/title-intelligence/packs/${packId}/chat/stream`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ message }),
          signal: abortControllerRef.current.signal,
        }
      );

      if (!response.ok) {
        throw new Error(`Stream error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("No response body");
      }

      let fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = decoder.decode(value, { stream: true });
        const lines = text.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.type === "thinking") {
                // Show thinking indicator while AI processes tools
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId && !fullText
                      ? { ...m, content: "Thinking..." }
                      : m
                  )
                );
              } else if (data.type === "chunk") {
                fullText += data.content;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId ? { ...m, content: fullText } : m
                  )
                );
              } else if (data.type === "done") {
                // Extract citations from completed text
                const citations = extractCitations(fullText);
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId
                      ? { ...m, content: fullText, citations }
                      : m
                  )
                );
              } else if (data.type === "error") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId
                      ? { ...m, content: `Error: ${data.content}` }
                      : m
                  )
                );
              }
            } catch {
              // Skip malformed SSE data
            }
          }
        }
      }

      return assistantMsg;
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        // Cancelled by user
        return assistantMsg;
      }
      // Fallback to non-streaming
      try {
        const response = await orgFetch<ChatMessage>(
          `/api/v1/apps/title-intelligence/packs/${packId}/chat`,
          {
            method: "POST",
            body: JSON.stringify({ message }),
          }
        );
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? response : m
          )
        );
        return response;
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: "Failed to get response. Please try again." }
              : m
          )
        );
        return assistantMsg;
      }
    } finally {
      setSending(false);
      abortControllerRef.current = null;
    }
  };

  const cancelStream = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  const clearChat = useCallback(async () => {
    try {
      await orgFetch<{ deleted: number }>(
        `/api/v1/apps/title-intelligence/packs/${packId}/chat`,
        { method: "DELETE" }
      );
      setMessages([]);
    } catch {
      // ignore
    }
  }, [orgFetch, packId]);

  return {
    messages,
    loading,
    sending,
    sendMessage,
    cancelStream,
    clearChat,
    refetch: fetchHistory,
  };
}

function extractCitations(
  text: string
): { page_number: number; text_snippet: string }[] | null {
  const regex = /\[Page\s+(\d+)\]/g;
  const citations: { page_number: number; text_snippet: string }[] = [];
  const seen = new Set<number>();
  let match;

  while ((match = regex.exec(text)) !== null) {
    const pageNum = parseInt(match[1], 10);
    if (!seen.has(pageNum)) {
      seen.add(pageNum);
      citations.push({ page_number: pageNum, text_snippet: "" });
    }
  }

  return citations.length > 0 ? citations : null;
}
