import { useState, useRef, useCallback, useEffect } from "react";
import { parseSSEStream } from "@/lib/sse";
import type { Segment } from "@/lib/types";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface ProgressStatusData {
  status: string;
  node: string;
  nodeIndex: number;
  totalNodes: number;
}

export interface ActivityContent {
  title: string;
  progress: number;
  details: string;
}

interface UseSegmentStreamReturn {
  messages: Message[];
  segment: Segment | null;
  progressStatus: ProgressStatusData | null;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  isGenerating: boolean;
  sendMessage: (content: string) => void;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setSegment: React.Dispatch<React.SetStateAction<Segment | null>>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSegmentStream(threadId: string): UseSegmentStreamReturn {
  // ---- Core state ----
  const [messages, setMessages] = useState<Message[]>([]);
  const [segment, setSegment] = useState<Segment | null>(null);
  const [progressStatus, setProgressStatus] =
    useState<ProgressStatusData | null>(null);
  const [currentActivity, setCurrentActivity] =
    useState<ActivityContent | null>(null);
  const [currentReasoning, setCurrentReasoning] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);

  // ---- Refs for stable closures ----
  const threadIdRef = useRef(threadId);
  threadIdRef.current = threadId;

  const abortRef = useRef<AbortController | null>(null);

  // Accumulator refs used inside the streaming loop
  const textAccRef = useRef("");
  const toolCallIdRef = useRef("");
  const toolCallNameRef = useRef("");
  const toolCallArgsRef = useRef("");
  const reasoningAccRef = useRef("");

  // ---- Reset all state when threadId changes ----
  useEffect(() => {
    setMessages([]);
    setSegment(null);
    setProgressStatus(null);
    setCurrentActivity(null);
    setCurrentReasoning("");
    setIsGenerating(false);

    // Abort any in-flight request from the previous thread
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, [threadId]);

  // ---- sendMessage ----
  const sendMessage = useCallback(
    async (content: string) => {
      // 1. Build & append user message
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content,
      };
      setMessages((prev) => [...prev, userMsg]);

      // 2. Clear transient state, mark generating
      setIsGenerating(true);
      setProgressStatus(null);
      setCurrentActivity(null);
      setCurrentReasoning("");
      textAccRef.current = "";
      toolCallIdRef.current = "";
      toolCallNameRef.current = "";
      toolCallArgsRef.current = "";
      reasoningAccRef.current = "";

      // 3. Abort any previous in-flight request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // 4. POST to backend
        const res = await fetch(`${BACKEND_URL}/api/v1/segment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            thread_id: threadIdRef.current,
            messages: [{ role: "user", content }],
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          console.error("Segment stream request failed:", res.status);
          setIsGenerating(false);
          return;
        }

        // 5. Parse the SSE stream
        const reader = res.body.getReader();

        for await (const event of parseSSEStream(reader)) {
          if (controller.signal.aborted) break;

          const eventType = event.type as string;

          switch (eventType) {
            // -- Run lifecycle --
            case "RUN_STARTED":
              // Already set isGenerating above
              break;

            case "RUN_FINISHED":
              setIsGenerating(false);
              break;

            case "RUN_ERROR":
              setIsGenerating(false);
              console.error("RUN_ERROR:", event.message);
              break;

            // -- Messages & state snapshots --
            case "MESSAGES_SNAPSHOT":
              // Ignore during active generation; we manage local messages
              break;

            case "STATE_SNAPSHOT": {
              const snapshot = event.snapshot as Record<string, unknown> | undefined;
              if (snapshot && snapshot.name && snapshot.condition_groups) {
                setSegment(snapshot as unknown as Segment);
              }
              break;
            }

            case "STATE_DELTA":
              // Ignore for now; STATE_SNAPSHOT delivers the final state
              break;

            // -- Tool calls (progress status) --
            case "TOOL_CALL_START":
              toolCallIdRef.current = (event.tool_call_id as string) || "";
              toolCallNameRef.current = (event.tool_call_name as string) || "";
              toolCallArgsRef.current = "";
              break;

            case "TOOL_CALL_ARGS":
              toolCallArgsRef.current += (event.delta as string) || "";
              break;

            case "TOOL_CALL_END":
              if (toolCallNameRef.current === "update_progress_status") {
                try {
                  const parsed = JSON.parse(toolCallArgsRef.current);
                  setProgressStatus({
                    status: parsed.status,
                    node: parsed.node,
                    nodeIndex: parsed.node_index,
                    totalNodes: parsed.total_nodes,
                  });
                } catch {
                  console.warn(
                    "Failed to parse update_progress_status args:",
                    toolCallArgsRef.current,
                  );
                }
              }
              // Reset tool-call refs
              toolCallIdRef.current = "";
              toolCallNameRef.current = "";
              toolCallArgsRef.current = "";
              break;

            // -- Activity --
            case "ACTIVITY_SNAPSHOT": {
              const actContent = event.content as ActivityContent | undefined;
              if (actContent) {
                setCurrentActivity(actContent);
              }
              break;
            }

            // -- Reasoning --
            case "REASONING_START":
              reasoningAccRef.current = "";
              setCurrentReasoning("");
              break;

            case "REASONING_MESSAGE_CONTENT": {
              const delta = event.delta as string;
              if (delta) {
                reasoningAccRef.current += delta;
                setCurrentReasoning(reasoningAccRef.current);
              }
              break;
            }

            // -- Text message streaming --
            case "TEXT_MESSAGE_START":
              textAccRef.current = "";
              break;

            case "TEXT_MESSAGE_CONTENT": {
              const textDelta = event.delta as string;
              if (textDelta) {
                textAccRef.current += textDelta;
              }
              break;
            }

            case "TEXT_MESSAGE_END": {
              const assistantMsg: Message = {
                id: (event.message_id as string) || crypto.randomUUID(),
                role: "assistant",
                content: textAccRef.current,
              };
              setMessages((prev) => [...prev, assistantMsg]);
              textAccRef.current = "";
              break;
            }

            // -- Events we acknowledge but don't act on --
            case "STEP_STARTED":
            case "STEP_FINISHED":
            case "REASONING_MESSAGE_START":
            case "REASONING_MESSAGE_END":
            case "REASONING_END":
              break;

            default:
              // Unknown event type — silently skip
              break;
          }
        }
      } catch (err: unknown) {
        // Abort errors are expected when we cancel a previous request
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        console.error("Segment stream error:", err);
        setIsGenerating(false);
      }
    },
    [threadId],
  );

  return {
    messages,
    segment,
    progressStatus,
    currentActivity,
    currentReasoning,
    isGenerating,
    sendMessage,
    setMessages,
    setSegment,
  };
}
