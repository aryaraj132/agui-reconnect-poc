"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import {
  CopilotKit,
  useCoAgentStateRender,
  useCoAgent,
  useCopilotAction,
} from "@copilotkit/react-core";
import {
  CopilotSidebar,
  RenderMessageProps,
  AssistantMessage as DefaultAssistantMessage,
  UserMessage as DefaultUserMessage,
  ImageRenderer as DefaultImageRenderer,
} from "@copilotkit/react-ui";
import { Nav } from "@/components/Nav";
import { SegmentCard } from "@/components/SegmentCard";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { ReconnectionBanner } from "@/components/ReconnectionBanner";
import { AgentHistoryPanel } from "@/components/AgentHistoryPanel";
import { useAgentThread } from "@/hooks/useAgentThread";
import { useRestoreThread } from "@/hooks/useRestoreThread";
import { ProgressStatus } from "@/components/ProgressStatus";
import type { Segment } from "@/lib/types";

function CustomRenderMessage({
  message,
  messages,
  inProgress,
  index,
  isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
  if (message.role === "reasoning" || message.role === "activity") {
    // Hide when no run is active
    if (!inProgress) return null;
    // Hide if this belongs to a completed turn
    const fromOldTurn = messages
      .slice(index + 1)
      .some((m) => m.role === "assistant" && m.content);
    if (fromOldTurn) return null;

    // Only render the LAST message of this role type — skip older ones
    // so activity replaces (not stacks) and reasoning shows only the latest
    const hasNewerOfSameRole = messages
      .slice(index + 1)
      .some((m) => m.role === message.role);
    if (hasNewerOfSameRole) return null;

    if (message.role === "reasoning") {
      return <ReasoningPanel reasoning={message.content} defaultOpen />;
    }
    return (
      <ActivityIndicator
        activityType={(message as any).activityType ?? "processing"}
        content={message.content as any}
      />
    );
  }

  if (message.role === "user") {
    return (
      <UserMessage
        key={index}
        rawData={message}
        message={message}
        ImageRenderer={ImageRenderer}
      />
    );
  }

  if (message.role === "assistant") {
    return (
      <AssistantMessage
        key={index}
        rawData={message}
        message={message}
        isLoading={inProgress && isCurrentMessage && !message.content}
        isGenerating={inProgress && isCurrentMessage && !!message.content}
        isCurrentMessage={isCurrentMessage}
      />
    );
  }

  return null;
}

function SegmentPageContent({
  threadId,
  isExistingThread,
}: {
  threadId: string;
  isExistingThread: boolean;
}) {
  useCoAgentStateRender({
    name: "default",
    render: ({ state }) =>
      state?.condition_groups ? <SegmentCard segment={state} /> : null,
  });

  const { state: segment, setState: setSegment } = useCoAgent<Segment>({
    name: "default",
  });

  const setSegmentRef = useRef(setSegment);
  setSegmentRef.current = setSegment;

  const {
    threadData,
    isRestoring,
    isStreamActive,
    isCatchingUp,
    currentActivity,
    currentReasoning,
    restoredSegment,
  } = useRestoreThread(threadId, isExistingThread);

  const [progressStatus, setProgressStatus] = useState<{
    status: string;
    node: string;
    nodeIndex: number;
    totalNodes: number;
  } | null>(null);

  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string", description: "Current status" },
      { name: "node", type: "string", description: "Current node name" },
      { name: "node_index", type: "number", description: "Current node index" },
      { name: "total_nodes", type: "number", description: "Total number of nodes" },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      setProgressStatus({
        status,
        node,
        nodeIndex: node_index,
        totalNodes: total_nodes,
      });
    },
  });

  // Restore segment state from reconnection
  useEffect(() => {
    if (restoredSegment) {
      setSegmentRef.current(restoredSegment);
    }
  }, [restoredSegment]);

  // Fallback: restore from threadData.state
  useEffect(() => {
    if (
      !restoredSegment &&
      threadData?.state &&
      (threadData.state as Record<string, unknown>).name
    ) {
      setSegmentRef.current(threadData.state as unknown as Segment);
    }
  }, [threadData, restoredSegment]);

  return (
    <div className="h-screen flex flex-col">
      <ReconnectionBanner
        isRestoring={isRestoring}
        isStreamActive={isStreamActive}
        isCatchingUp={isCatchingUp}
        currentActivity={currentActivity}
        currentReasoning={currentReasoning}
      />
      <Nav />
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && (
            <ProgressStatus
              status={progressStatus.status}
              node={progressStatus.node}
              nodeIndex={progressStatus.nodeIndex}
              totalNodes={progressStatus.totalNodes}
            />
          )}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : isStreamActive && currentActivity ? (
            <div className="space-y-4">
              <ActivityIndicator
                activityType="processing"
                content={currentActivity}
              />
              {currentReasoning && (
                <ReasoningPanel reasoning={currentReasoning} defaultOpen />
              )}
            </div>
          ) : !progressStatus ? (
            <p className="text-sm text-gray-400 text-center">
              Describe your audience in the sidebar to generate a segment.
            </p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function SegmentPageInner() {
  const {
    threadId,
    isExistingThread,
    ready,
    startNewThread,
    switchToThread,
  } = useAgentThread();

  return (
    <>
      <AgentHistoryPanel
        agentType="segment"
        currentThreadId={threadId}
        onNewThread={startNewThread}
        onSelectThread={switchToThread}
      />
      {ready ? (
        <CopilotKit
          key={threadId}
          runtimeUrl="/api/copilotkit/segment"
          threadId={threadId}
        >
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are a user segmentation assistant. The user will describe a target audience and you will generate a structured segment definition with conditions."
            labels={{
              title: "Segment Builder",
              initial:
                'Describe your target audience and I\'ll generate a structured segment.\n\nTry: **"Users from the US who signed up in the last 30 days and made a purchase"**',
            }}
          >
            <SegmentPageContent
              threadId={threadId}
              isExistingThread={isExistingThread}
            />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function SegmentPage() {
  return (
    <Suspense>
      <SegmentPageInner />
    </Suspense>
  );
}
