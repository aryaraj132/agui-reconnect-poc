"use client";

import { Suspense, useState, useEffect, type ReactNode } from "react";
import {
  CopilotKit,
  useCoAgent,
  useCoAgentStateRender,
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
import { useAgentThread } from "@/hooks/useAgentThread";
import { ProgressStatus } from "@/components/ProgressStatus";
import type { Segment } from "@/lib/types";

function InlineSegmentCard({ fallback }: { fallback?: ReactNode }) {
  const { state: segment } = useCoAgent<Segment>({ name: "default" });
  if (!segment?.condition_groups) return <>{fallback}</>;
  return <SegmentCard segment={segment} />;
}

function CustomRenderMessage({
  message, messages, inProgress, index, isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
  if (message.role === "reasoning" || message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages.slice(index + 1).some((m) => m.role === "user");
    if (fromOldTurn) return null;
    const hasNewerOfSameRole = messages.slice(index + 1).some((m) => m.role === message.role);
    if (hasNewerOfSameRole) return null;
    if (message.role === "reasoning") return <ReasoningPanel reasoning={message.content} defaultOpen />;
    return <ActivityIndicator activityType={(message as any).activityType ?? "processing"} content={message.content as any} />;
  }
  if (message.role === "user") return <UserMessage key={index} rawData={message} message={message} ImageRenderer={ImageRenderer} />;
  if (message.role === "assistant") {
    if (!message.content && !(inProgress && isCurrentMessage)) return null;
    const isLastAssistant = !!message.content && !messages.slice(index + 1).some((m) => m.role === "assistant" && m.content);
    const assistantMsg = <AssistantMessage key={index} rawData={message} message={message} isLoading={inProgress && isCurrentMessage && !message.content} isGenerating={inProgress && isCurrentMessage && !!message.content} isCurrentMessage={isCurrentMessage} />;
    if (isLastAssistant) {
      return <InlineSegmentCard fallback={assistantMsg} />;
    }
    return assistantMsg;
  }
  return null;
}

function SegmentPageContent() {
  const { state: segment } = useCoAgent<Segment>({ name: "default" });

  // Register state render handler so CopilotKit routes STATE_SNAPSHOT events
  // to useCoAgent. Render null here — the card is shown via InlineSegmentCard
  // in CustomRenderMessage (attached to the last assistant message only).
  useCoAgentStateRender({ name: "default", render: () => null });

  const [progressStatus, setProgressStatus] = useState<{ status: string; node: string; nodeIndex: number; totalNodes: number } | null>(null);

  // Reset progress when co-agent state is cleared (start of new run)
  useEffect(() => {
    if (segment && !segment.condition_groups) {
      setProgressStatus(null);
    }
  }, [segment]);

  useCopilotAction({
    name: "update_progress_status",
    parameters: [
      { name: "status", type: "string", description: "Current status" },
      { name: "node", type: "string", description: "Current node name" },
      { name: "node_index", type: "number", description: "Current node index" },
      { name: "total_nodes", type: "number", description: "Total number of nodes" },
    ],
    handler: ({ status, node, node_index, total_nodes }) => {
      if (status === "starting") {
        setProgressStatus(null);
        return;
      }
      setProgressStatus({ status, node, nodeIndex: node_index, totalNodes: total_nodes });
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-lg space-y-6">
          {progressStatus && <ProgressStatus status={progressStatus.status} node={progressStatus.node} nodeIndex={progressStatus.nodeIndex} totalNodes={progressStatus.totalNodes} />}
          {segment?.condition_groups ? (
            <SegmentCard segment={segment} />
          ) : !progressStatus ? (
            <p className="text-sm text-gray-400 text-center">Describe your audience in the sidebar to generate a segment.</p>
          ) : null}
        </div>
      </main>
    </div>
  );
}

function SegmentPageInner() {
  const { threadId, ready } = useAgentThread();
  return (
    <>
      {ready ? (
        <CopilotKit key={threadId} runtimeUrl="/api/copilotkit/segment" threadId={threadId}>
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are a user segmentation assistant. The user will describe a target audience and you will generate a structured segment definition with conditions."
            labels={{
              title: "Segment Builder",
              initial: 'Describe your target audience and I\'ll generate a structured segment.\n\nTry: **"Users from the US who signed up in the last 30 days and made a purchase"**',
            }}
          >
            <SegmentPageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function SegmentPage() {
  return <Suspense><SegmentPageInner /></Suspense>;
}
