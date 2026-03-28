import { useState, useEffect, useRef, useCallback } from "react";
import { parseSSEStream } from "@/lib/sse";
import type { ThreadData, Segment } from "@/lib/types";

const BACKEND_URL =
  process.env.BACKEND_URL || "http://localhost:8000";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

interface ActivityContent {
  title: string;
  progress: number;
  details: string;
}

interface RestoreResult {
  threadData: ThreadData | null;
  isRestoring: boolean;
  isStreamActive: boolean;
  isCatchingUp: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  restoredSegment: Segment | null;
}

export function useRestoreThread(
  threadId: string,
  isExistingThread: boolean,
  setMessages: (msgs: Message[]) => void,
  setSegment: (seg: Segment | null) => void
): RestoreResult {
  const setMessagesRef = useRef(setMessages);
  setMessagesRef.current = setMessages;

  const setSegmentRef = useRef(setSegment);
  setSegmentRef.current = setSegment;

  const [threadData, setThreadData] = useState<ThreadData | null>(null);
  const [isRestoring, setIsRestoring] = useState(isExistingThread);
  const [isStreamActive, setIsStreamActive] = useState(false);
  const [currentActivity, setCurrentActivity] =
    useState<ActivityContent | null>(null);
  const [currentReasoning, setCurrentReasoning] = useState("");
  const [restoredSegment, setRestoredSegment] = useState<Segment | null>(null);
  const [isCatchingUp, setIsCatchingUp] = useState(false);

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

        // Restore messages
        if (data.messages?.length > 0) {
          const msgs: Message[] = data.messages.map((m) => ({
            id: crypto.randomUUID(),
            role: m.role === "user" ? ("user" as const) : ("assistant" as const),
            content: m.content || "",
          }));
          setMessagesRef.current(msgs);
        }

        // Restore segment state
        if (data.state && (data.state as Record<string, unknown>).name) {
          const seg = data.state as unknown as Segment;
          setRestoredSegment(seg);
          setSegmentRef.current(seg);
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
    setIsCatchingUp(false);

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

        let catchingUp = true;
        setIsCatchingUp(true);

        for await (const event of parseSSEStream(reader)) {
          if (signal.aborted) break;

          const eventType = event.type as string;

          // Fast-forward delay during catch-up (XRANGE events arrive in burst)
          if (
            catchingUp &&
            eventType !== "RUN_STARTED" &&
            eventType !== "MESSAGES_SNAPSHOT" &&
            eventType !== "STATE_SNAPSHOT" &&
            eventType !== "RUN_FINISHED" &&
            eventType !== "RUN_ERROR"
          ) {
            await new Promise((r) => setTimeout(r, 100));
          }

          switch (eventType) {
            case "MESSAGES_SNAPSHOT": {
              const messages = event.messages as Array<{
                role: string;
                content: string;
              }>;
              if (messages?.length > 0) {
                const msgs: Message[] = messages.map((m) => ({
                  id: crypto.randomUUID(),
                  role: m.role === "user" ? ("user" as const) : ("assistant" as const),
                  content: m.content || "",
                }));
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
                  const seg = snapshot as unknown as Segment;
                  setRestoredSegment(seg);
                  setSegmentRef.current(seg);
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

            case "TOOL_CALL_START":
            case "TOOL_CALL_ARGS":
            case "TOOL_CALL_END": {
              // Tool call events replay update_progress_status during catch-up
              break;
            }

            case "STEP_STARTED":
            case "STEP_FINISHED": {
              // Step events replayed during catch-up for progression
              break;
            }

            case "RUN_FINISHED":
            case "RUN_ERROR": {
              if (catchingUp) {
                catchingUp = false;
                setIsCatchingUp(false);
              }
              setIsStreamActive(false);
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
          setIsCatchingUp(false);
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
    isCatchingUp,
    currentActivity,
    currentReasoning,
    restoredSegment,
  };
}
