"use client";

import { Suspense, useState, useEffect } from "react";
import {
  CopilotKit,
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
import { TemplateEditor } from "@/components/TemplateEditor";
import { ReasoningPanel } from "@/components/ReasoningPanel";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { useAgentThread } from "@/hooks/useAgentThread";
import { ProgressStatus } from "@/components/ProgressStatus";
import type { EmailTemplate } from "@/lib/types";

const TEMPLATE_NODE_LABELS: Record<string, string> = {
  generate_template: "Generate",
  modify_template: "Modify",
  analyze_template: "Analyze",
  quality_check: "Quality",
};

const TEMPLATE_NODE_ORDER = [
  "generate_template",
  "analyze_template",
  "quality_check",
];

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
  if (message.role === "activity") {
    if (!inProgress) return null;
    const fromOldTurn = messages
      .slice(index + 1)
      .some((m) => m.role === "assistant" && m.content);
    if (fromOldTurn) return null;
    return (
      <ActivityIndicator
        activityType={(message as any).activityType ?? "processing"}
        content={message.content as any}
      />
    );
  }

  if (message.role === "reasoning") {
    // Hide reasoning from old turns (a user message follows)
    const fromOldTurn = messages
      .slice(index + 1)
      .some((m) => m.role === "user");
    if (fromOldTurn) return null;
    return (
      <ReasoningPanel
        reasoning={message.content}
        defaultOpen={inProgress}
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

function TemplatePageContent() {
  const { state: template, setState: setTemplate } =
    useCoAgent<EmailTemplate>({ name: "default" });

  const [progressStatus, setProgressStatus] = useState<{
    status: string;
    node: string;
    nodeIndex: number;
    totalNodes: number;
  } | null>(null);

  // Track whether the modify path was taken (persists across node transitions)
  const [isModifyPath, setIsModifyPath] = useState(false);

  // Reset progress when co-agent state is cleared (start of new run)
  useEffect(() => {
    if (template && !template.subject) {
      setProgressStatus(null);
      setIsModifyPath(false);
    }
  }, [template]);

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
        setIsModifyPath(false);
        return;
      }
      if (node === "modify_template") {
        setIsModifyPath(true);
      }
      setProgressStatus({ status, node, nodeIndex: node_index, totalNodes: total_nodes });
    },
  });

  // Determine node order based on whether we're generating or modifying
  const nodeOrder = isModifyPath
    ? ["modify_template", "analyze_template", "quality_check"]
    : TEMPLATE_NODE_ORDER;

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 overflow-hidden">
        <div className="h-full flex flex-col">
          {progressStatus && (
            <div className="px-8 pt-4">
              <ProgressStatus
                status={progressStatus.status}
                node={progressStatus.node}
                nodeIndex={progressStatus.nodeIndex}
                totalNodes={progressStatus.totalNodes}
                nodeLabels={TEMPLATE_NODE_LABELS}
                nodeOrder={nodeOrder}
                completedLabel="Template Complete"
              />
            </div>
          )}
          {template?.subject ? (
            <div className="flex-1 overflow-hidden">
              <TemplateEditor
                template={template}
                onHtmlChange={(html) => setTemplate({ ...template, html })}
              />
            </div>
          ) : !progressStatus ? (
            <div className="flex items-center justify-center flex-1">
              <p className="text-sm text-gray-400">
                Describe your email template in the sidebar to get started.
              </p>
            </div>
          ) : (
            <div className="flex-1" />
          )}
        </div>
      </main>
    </div>
  );
}

function TemplatePageInner() {
  const { threadId, ready } = useAgentThread();

  return (
    <>
      {ready ? (
        <CopilotKit
          key={threadId}
          runtimeUrl="/api/copilotkit/template"
          threadId={threadId}
        >
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are an email template design assistant. Help the user create and modify professional HTML email templates."
            labels={{
              title: "Template Creator",
              initial:
                'Describe the email template you want to create.\n\nTry: **"A welcome email for new SaaS users with a hero image and CTA button"**',
            }}
          >
            <TemplatePageContent />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function TemplatePage() {
  return (
    <Suspense>
      <TemplatePageInner />
    </Suspense>
  );
}
