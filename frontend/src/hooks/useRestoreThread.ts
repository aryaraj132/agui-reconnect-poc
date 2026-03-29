import { useState, useEffect, useRef, useCallback } from "react";
import { useCopilotMessagesContext } from "@copilotkit/react-core";
import { TextMessage, Role } from "@copilotkit/runtime-client-gql";
import { parseSSEStream } from "@/lib/sse";
import type { ThreadData, Segment } from "@/lib/types";

export type ReconnectPhase =
  | "idle"
  | "connecting"
  | "catching_up"
  | "live"
  | "stale_recovery"
  | "done"
  | "error";

const BACKEND_URL =
  process.env.BACKEND_URL || "http://localhost:8000";

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
  reconnectPhase: ReconnectPhase;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  restoredSegment: Segment | null;
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
  const [isCatchingUp, setIsCatchingUp] = useState(false);
  const [reconnectPhase, setReconnectPhase] = useState<ReconnectPhase>("idle");

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
    setIsCatchingUp(false);
    setReconnectPhase("idle");

    if (!isExistingThread) {
      setIsRestoring(false);
      return;
    }

    const abortController = new AbortController();
    const signal = abortController.signal;

    async function reconnect() {
      try {
        // Connect to SSE reconnection endpoint
        setReconnectPhase("connecting");
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
        setReconnectPhase("catching_up");

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
                setThreadData((prev) => ({
                  messages: prev?.messages || [],
                  events: [],
                  state: snapshot,
                  agent_type: "segment",
                  created_at: prev?.created_at || new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                }));

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
              break;
            }

            case "TOOL_CALL_START":
            case "TOOL_CALL_ARGS":
            case "TOOL_CALL_END": {
              break;
            }

            case "STEP_STARTED":
            case "STEP_FINISHED": {
              break;
            }

            case "CUSTOM": {
              const customName = event.name as string;
              if (customName === "run_stale") {
                setReconnectPhase("stale_recovery");
                setCurrentActivity(null);
                setCurrentReasoning("");
              } else if (customName === "run_restarted") {
                setReconnectPhase("catching_up");
              } else if (customName === "catchup_complete") {
                setReconnectPhase("live");
                setIsCatchingUp(false);
              }
              break;
            }

            case "RUN_FINISHED": {
              if (catchingUp) {
                catchingUp = false;
                setIsCatchingUp(false);
              }
              setReconnectPhase("done");
              setIsStreamActive(false);
              setTimeout(() => {
                setCurrentActivity(null);
                setCurrentReasoning("");
              }, 1000);
              break;
            }

            case "RUN_ERROR": {
              if (catchingUp) {
                catchingUp = false;
                setIsCatchingUp(false);
              }
              setReconnectPhase("error");
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
          setReconnectPhase("error");
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
    reconnectPhase,
    currentActivity,
    currentReasoning,
    restoredSegment,
  };
}
