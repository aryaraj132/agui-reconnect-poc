"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useCopilotMessagesContext } from "@copilotkit/react-core";
import { TextMessage, Role } from "@copilotkit/runtime-client-gql";
import type { ThreadData, Segment } from "@/lib/types";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

interface ActivityContent {
  title: string;
  progress: number;
  details: string;
}

interface RestoreResult {
  threadData: ThreadData | null;
  isRestoring: boolean;
  isStreamActive: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  restoredSegment: Segment | null;
}

/**
 * Parse SSE events from a streaming response body.
 * Yields parsed JSON objects from `data: {...}` lines.
 */
async function* parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>
): AsyncGenerator<Record<string, unknown>> {
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    // Keep the last incomplete line in the buffer
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("data: ")) {
        const jsonStr = trimmed.slice(6);
        try {
          yield JSON.parse(jsonStr);
        } catch {
          // Skip unparseable lines
        }
      }
    }
  }

  // Process any remaining data in buffer
  if (buffer.trim().startsWith("data: ")) {
    try {
      yield JSON.parse(buffer.trim().slice(6));
    } catch {
      // Skip
    }
  }
}

export function useRestoreThread(
  threadId: string,
  isExistingThread = true
): RestoreResult {
  const { setMessages } = useCopilotMessagesContext();
  const setMessagesRef = useRef(setMessages);
  setMessagesRef.current = setMessages;

  const [threadData, setThreadData] = useState<ThreadData | null>(null);
  const [isRestoring, setIsRestoring] = useState(isExistingThread);
  const [isStreamActive, setIsStreamActive] = useState(false);
  const [currentActivity, setCurrentActivity] =
    useState<ActivityContent | null>(null);
  const [currentReasoning, setCurrentReasoning] = useState("");
  const [restoredSegment, setRestoredSegment] = useState<Segment | null>(null);

  // Fallback: fetch thread data via REST (used when SSE fails)
  const restoreFallback = useCallback(
    async (abortSignal: AbortSignal) => {
      try {
        const res = await fetch(
          `${BACKEND_URL}/api/v1/threads/${threadId}`,
          { signal: abortSignal }
        );
        if (!res.ok) return;
        const data: ThreadData = await res.json();
        if (abortSignal.aborted) return;

        setThreadData(data);

        // Restore messages into CopilotKit
        if (data.messages?.length > 0) {
          const msgs = data.messages.map(
            (m) =>
              new TextMessage({
                id: crypto.randomUUID(),
                content: m.content || "",
                role: m.role === "user" ? Role.User : Role.Assistant,
              })
          );
          setMessagesRef.current(msgs);
        }

        // Restore segment state
        if (data.state && (data.state as Record<string, unknown>).name) {
          setRestoredSegment(data.state as unknown as Segment);
        }
      } catch (e) {
        if (!abortSignal.aborted) {
          console.error("Fallback restore failed:", e);
        }
      }
    },
    [threadId]
  );

  useEffect(() => {
    setThreadData(null);
    setCurrentActivity(null);
    setCurrentReasoning("");
    setRestoredSegment(null);
    setIsStreamActive(false);

    if (!isExistingThread) {
      setIsRestoring(false);
      return;
    }

    const abortController = new AbortController();
    const signal = abortController.signal;

    async function reconnect() {
      try {
        // Connect to SSE reconnection endpoint
        const res = await fetch(
          `${BACKEND_URL}/api/v1/reconnect/${threadId}`,
          { signal }
        );

        if (!res.ok || !res.body) {
          // Fallback to REST
          await restoreFallback(signal);
          return;
        }

        setIsStreamActive(true);
        const reader = res.body.getReader();
        let reasoningBuffer = "";

        for await (const event of parseSSEStream(reader)) {
          if (signal.aborted) break;

          const eventType = event.type as string;

          switch (eventType) {
            case "MESSAGES_SNAPSHOT": {
              const messages = event.messages as Array<{
                role: string;
                content: string;
              }>;
              if (messages?.length > 0) {
                const msgs = messages.map(
                  (m) =>
                    new TextMessage({
                      id: crypto.randomUUID(),
                      content: m.content || "",
                      role: m.role === "user" ? Role.User : Role.Assistant,
                    })
                );
                setMessagesRef.current(msgs);
              }
              break;
            }

            case "STATE_SNAPSHOT": {
              const snapshot = event.snapshot as Record<string, unknown>;
              if (snapshot) {
                // Build threadData-like object for state restoration
                setThreadData((prev) => ({
                  messages: prev?.messages || [],
                  events: [],
                  state: snapshot,
                  agent_type: "segment",
                  created_at: prev?.created_at || new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                }));

                // If this looks like a segment (has name + condition_groups)
                if (snapshot.name && snapshot.condition_groups) {
                  setRestoredSegment(snapshot as unknown as Segment);
                }
              }
              break;
            }

            case "ACTIVITY_SNAPSHOT": {
              const content = event.content as ActivityContent;
              if (content) {
                setCurrentActivity(content);
              }
              break;
            }

            case "REASONING_START": {
              reasoningBuffer = "";
              setCurrentReasoning("");
              break;
            }

            case "REASONING_MESSAGE_CONTENT": {
              const delta = event.delta as string;
              if (delta) {
                reasoningBuffer += delta;
                setCurrentReasoning(reasoningBuffer);
              }
              break;
            }

            case "TEXT_MESSAGE_CONTENT": {
              // Text messages will be restored via MESSAGES_SNAPSHOT or added to existing
              break;
            }

            case "RUN_FINISHED":
            case "RUN_ERROR": {
              setIsStreamActive(false);
              // Clear transient UI after a brief delay
              setTimeout(() => {
                setCurrentActivity(null);
                setCurrentReasoning("");
              }, 1000);
              break;
            }
          }
        }
      } catch (e) {
        if (!signal.aborted) {
          console.error("SSE reconnection failed, falling back to REST:", e);
          await restoreFallback(signal);
        }
      } finally {
        if (!signal.aborted) {
          setIsRestoring(false);
          setIsStreamActive(false);
        }
      }
    }

    reconnect();

    return () => {
      abortController.abort();
    };
  }, [threadId, isExistingThread, restoreFallback]);

  return {
    threadData,
    isRestoring,
    isStreamActive,
    currentActivity,
    currentReasoning,
    restoredSegment,
  };
}
