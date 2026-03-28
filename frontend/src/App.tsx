import { useEffect } from "react";
import { useAgentThread } from "@/hooks/useAgentThread";
import { useSegmentStream } from "@/hooks/useSegmentStream";
import { useRestoreThread } from "@/hooks/useRestoreThread";
import { ChatSidebar } from "@/components/ChatSidebar";
import { Nav } from "@/components/Nav";
import { SegmentCard } from "@/components/SegmentCard";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ReconnectionBanner } from "@/components/ReconnectionBanner";
import { AgentHistoryPanel } from "@/components/AgentHistoryPanel";
import { ProgressStatus } from "@/components/ProgressStatus";

export default function App() {
  const { threadId, isExistingThread, ready, startNewThread, switchToThread } =
    useAgentThread();

  const {
    messages,
    segment,
    progressStatus,
    currentActivity,
    currentReasoning,
    isGenerating,
    sendMessage,
    setMessages,
    setSegment,
  } = useSegmentStream(threadId);

  const {
    isRestoring,
    isStreamActive,
    isCatchingUp,
    currentActivity: restoreActivity,
    currentReasoning: restoreReasoning,
    restoredSegment,
  } = useRestoreThread(threadId, isExistingThread, setMessages, setSegment);

  // Apply restored segment from reconnection
  useEffect(() => {
    if (restoredSegment) {
      setSegment(restoredSegment);
    }
  }, [restoredSegment, setSegment]);

  // Merge activity/reasoning from reconnection when not actively generating
  const activeActivity = isGenerating
    ? currentActivity
    : restoreActivity;
  const activeReasoning = isGenerating
    ? currentReasoning
    : restoreReasoning;

  if (!ready) return null;

  return (
    <>
      <AgentHistoryPanel
        agentType="segment"
        currentThreadId={threadId}
        onNewThread={startNewThread}
        onSelectThread={switchToThread}
      />

      <ChatSidebar
        messages={messages}
        isGenerating={isGenerating}
        currentActivity={activeActivity}
        currentReasoning={activeReasoning}
        onSendMessage={sendMessage}
      >
        <div className="h-screen flex flex-col">
          <ReconnectionBanner
            isRestoring={isRestoring}
            isStreamActive={isStreamActive}
            isCatchingUp={isCatchingUp}
            currentActivity={restoreActivity}
            currentReasoning={restoreReasoning}
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
              ) : (isStreamActive || isGenerating) && activeActivity ? (
                <div className="space-y-4">
                  <ActivityIndicator
                    activityType="processing"
                    content={activeActivity}
                  />
                  {activeReasoning && (
                    <ReasoningPanel reasoning={activeReasoning} defaultOpen />
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
      </ChatSidebar>
    </>
  );
}
