"use client";

import { Suspense, useState, useCallback, useEffect } from "react";
import {
  CopilotKit,
  useCoAgent,
  useCopilotAction,
  useCopilotChat,
} from "@copilotkit/react-core";
import {
  CopilotSidebar,
  RenderMessageProps,
  AssistantMessage as DefaultAssistantMessage,
  UserMessage as DefaultUserMessage,
  ImageRenderer as DefaultImageRenderer,
} from "@copilotkit/react-ui";
import { Nav } from "@/components/Nav";
import { TemplateEditorCanvas } from "@/components/TemplateEditorCanvas";
import { useAgentThread } from "@/hooks/useAgentThread";
import { TEMPLATE_COMPONENTS } from "@/lib/template-components";
import type { EmailTemplate, TemplateSection } from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────

function assembleHtmlClient(sections: TemplateSection[]): string {
  if (sections.length === 0) return "";
  const parts = sections.map((s) => {
    const id = s.id;
    const content = s.content || "";
    switch (s.type) {
      case "header":
        return `<tr><td id="${id}" style="background-color:#333;color:#fff;padding:20px;text-align:center;font-size:24px;font-family:Arial,sans-serif;">${content}</td></tr>`;
      case "image":
        return `<tr><td id="${id}" style="text-align:center;padding:0;"><img src="${content}" alt="" style="width:100%;max-width:600px;display:block;" /></td></tr>`;
      case "cta":
        return `<tr><td id="${id}" style="text-align:center;padding:30px;"><a href="#" style="background-color:#007bff;color:#fff;padding:14px 28px;text-decoration:none;border-radius:4px;font-family:Arial,sans-serif;font-size:16px;">${content}</a></td></tr>`;
      case "footer":
        return `<tr><td id="${id}" style="background-color:#f5f5f5;color:#999;padding:20px;text-align:center;font-size:12px;font-family:Arial,sans-serif;">${content}</td></tr>`;
      case "divider":
        return `<tr><td id="${id}" style="padding:10px 20px;"><hr style="border:none;border-top:1px solid #e0e0e0;margin:0;" /></td></tr>`;
      case "spacer":
        return `<tr><td id="${id}" style="padding:0;height:20px;line-height:20px;font-size:1px;">&nbsp;</td></tr>`;
      case "social_links":
        return `<tr><td id="${id}" style="text-align:center;padding:20px;font-family:Arial,sans-serif;font-size:14px;">${content}</td></tr>`;
      case "columns": {
        const cols = content.includes("|")
          ? content.split("|")
          : [content, content];
        return `<tr><td id="${id}" style="padding:20px;"><table width="100%" cellpadding="0" cellspacing="0"><tr><td width="50%" style="padding-right:10px;font-family:Arial,sans-serif;font-size:14px;vertical-align:top;">${cols[0]?.trim()}</td><td width="50%" style="padding-left:10px;font-family:Arial,sans-serif;font-size:14px;vertical-align:top;">${cols[1]?.trim() ?? ""}</td></tr></table></td></tr>`;
      }
      default: // body, text_block
        return `<tr><td id="${id}" style="padding:20px;font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#333;">${content}</td></tr>`;
    }
  });

  return `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#f5f5f5;"><table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;"><tr><td align="center"><table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;max-width:600px;width:100%;">${parts.join("\n")}</table></td></tr></table></body></html>`;
}

// ── Custom message renderer ──────────────────────────────────────────

function CustomRenderMessage({
  message,
  inProgress,
  index,
  isCurrentMessage,
  AssistantMessage = DefaultAssistantMessage,
  UserMessage = DefaultUserMessage,
  ImageRenderer = DefaultImageRenderer,
}: RenderMessageProps) {
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

// ── Page content (inside CopilotKit) ─────────────────────────────────

function TemplateEditorContent({ mode }: { mode: "fe-tools" | "be-only" }) {
  const { state: template, setState: setTemplate } =
    useCoAgent<EmailTemplate>({ name: "default" });

  const { isLoading } = useCopilotChat();

  const currentTemplate: EmailTemplate = template ?? {
    html: "",
    css: "",
    subject: "",
    preview_text: "",
    sections: [],
    version: 0,
  };

  // ── FE-side tool handlers (side effects for FE-tools mode) ────────

  useCopilotAction({
    name: "add_section",
    parameters: [
      { name: "section_type", type: "string", description: "Section type" },
      { name: "content", type: "string", description: "Section content" },
      {
        name: "position",
        type: "number",
        description: "Insert position (-1 for end)",
      },
    ],
    handler: ({ section_type, content, position }) => {
      if (mode === "be-only") return;
      const defaults = TEMPLATE_COMPONENTS.find(
        (c) => c.type === section_type
      );
      const sections = [...(currentTemplate.sections ?? [])];
      const newSection: TemplateSection = {
        id: `s${sections.length + 1}`,
        type: section_type,
        content: content || defaults?.defaultContent || "",
        styles: defaults?.defaultStyles ?? {},
      };
      const pos = position >= 0 ? position : sections.length;
      sections.splice(pos, 0, newSection);
      const html = assembleHtmlClient(sections);
      setTemplate({
        ...currentTemplate,
        sections,
        html,
        version: (currentTemplate.version ?? 0) + 1,
      });
    },
  });

  useCopilotAction({
    name: "update_section",
    parameters: [
      { name: "section_id", type: "string", description: "Section ID" },
      { name: "content", type: "string", description: "New content" },
      { name: "styles", type: "string", description: "JSON styles" },
    ],
    handler: ({ section_id, content, styles }) => {
      if (mode === "be-only") return;
      const sections = (currentTemplate.sections ?? []).map((s) => {
        if (s.id !== section_id) return s;
        const updated = { ...s };
        if (content) updated.content = content;
        if (styles) {
          try {
            updated.styles = { ...s.styles, ...JSON.parse(styles) };
          } catch {
            /* ignore parse errors */
          }
        }
        return updated;
      });
      const html = assembleHtmlClient(sections);
      setTemplate({
        ...currentTemplate,
        sections,
        html,
        version: (currentTemplate.version ?? 0) + 1,
      });
    },
  });

  useCopilotAction({
    name: "remove_section",
    parameters: [
      { name: "section_id", type: "string", description: "Section ID" },
    ],
    handler: ({ section_id }) => {
      if (mode === "be-only") return;
      const sections = (currentTemplate.sections ?? []).filter(
        (s) => s.id !== section_id
      );
      const html = assembleHtmlClient(sections);
      setTemplate({
        ...currentTemplate,
        sections,
        html,
        version: (currentTemplate.version ?? 0) + 1,
      });
    },
  });

  // ── Drag-and-drop handlers (always local, no AI) ───────────────────

  const handleAddSection = useCallback(
    (type: string, position?: number) => {
      const defaults = TEMPLATE_COMPONENTS.find((c) => c.type === type);
      const sections = [...(currentTemplate.sections ?? [])];
      const newSection: TemplateSection = {
        id: `s${Date.now()}`,
        type,
        content: defaults?.defaultContent || "",
        styles: defaults?.defaultStyles ?? {},
      };
      if (position !== undefined && position >= 0) {
        sections.splice(position, 0, newSection);
      } else {
        sections.push(newSection);
      }
      const html = assembleHtmlClient(sections);
      setTemplate({
        ...currentTemplate,
        sections,
        html,
        version: (currentTemplate.version ?? 0) + 1,
      });
    },
    [currentTemplate, setTemplate]
  );

  const handleRemoveSection = useCallback(
    (sectionId: string) => {
      const sections = (currentTemplate.sections ?? []).filter(
        (s) => s.id !== sectionId
      );
      const html = assembleHtmlClient(sections);
      setTemplate({
        ...currentTemplate,
        sections,
        html,
        version: (currentTemplate.version ?? 0) + 1,
      });
    },
    [currentTemplate, setTemplate]
  );

  return (
    <div className="h-screen flex flex-col">
      <Nav />
      <main className="flex-1 overflow-hidden">
        {isLoading && (
          <div className="px-4 py-1 bg-blue-50 dark:bg-blue-900/30 text-xs text-blue-600 dark:text-blue-300 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            AI is working...
          </div>
        )}
        <div className="h-full">
          <TemplateEditorCanvas
            template={currentTemplate}
            disabled={isLoading}
            onAddSection={handleAddSection}
            onRemoveSection={handleRemoveSection}
            onHtmlChange={(html) =>
              setTemplate({ ...currentTemplate, html })
            }
          />
        </div>
      </main>
    </div>
  );
}

// ── Page wrapper (CopilotKit provider) ───────────────────────────────

function TemplateEditorInner() {
  const [mode, setMode] = useState<"fe-tools" | "be-only">(() => {
    if (typeof window === "undefined") return "fe-tools";
    const params = new URLSearchParams(window.location.search);
    const m = params.get("mode");
    return m === "be-only" ? "be-only" : "fe-tools";
  });
  const { threadId, ready, startNewThread } = useAgentThread();

  const runtimeUrl =
    mode === "fe-tools"
      ? "/api/copilotkit/template-editor/fe-tools"
      : "/api/copilotkit/template-editor/be-only";

  // Keep mode in URL in sync
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("mode") !== mode) {
      params.set("mode", mode);
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}?${params.toString()}`
      );
    }
  }, [mode, threadId]);

  const handleModeSwitch = useCallback(
    (newMode: "fe-tools" | "be-only") => {
      if (newMode === mode) return;
      setMode(newMode);
      startNewThread();
    },
    [mode, startNewThread]
  );

  // Expose mode switch to Nav via window (simple cross-component comm)
  if (typeof window !== "undefined") {
    (window as any).__templateEditorMode = mode;
    (window as any).__templateEditorSetMode = handleModeSwitch;
  }

  return (
    <>
      {ready ? (
        <CopilotKit
          key={`${threadId}-${mode}`}
          runtimeUrl={runtimeUrl}
          threadId={threadId}
        >
          <CopilotSidebar
            defaultOpen={true}
            RenderMessage={CustomRenderMessage}
            instructions="You are an email template editor. Help the user build and improve email templates."
            labels={{
              title: "Template Editor",
              initial:
                'Drag components from the left panel to build your template, then ask me to improve it.\n\nOr try: **"Create a welcome email for new SaaS users"**',
            }}
          >
            <TemplateEditorContent mode={mode} />
          </CopilotSidebar>
        </CopilotKit>
      ) : null}
    </>
  );
}

export default function TemplateEditorPage() {
  return (
    <Suspense>
      <TemplateEditorInner />
    </Suspense>
  );
}
