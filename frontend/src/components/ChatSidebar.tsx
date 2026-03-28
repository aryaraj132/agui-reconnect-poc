import { useState, useRef, useEffect } from "react";
import type { Message, ActivityContent } from "@/hooks/useSegmentStream";
import { ActivityIndicator } from "./ActivityIndicator";
import { ReasoningPanel } from "./ReasoningPanel";

interface ChatSidebarProps {
  messages: Message[];
  isGenerating: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
  onSendMessage: (content: string) => void;
  children: React.ReactNode;
}

export function ChatSidebar({
  messages,
  isGenerating,
  currentActivity,
  currentReasoning,
  onSendMessage,
  children,
}: ChatSidebarProps) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentActivity, currentReasoning]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isGenerating) return;
    onSendMessage(trimmed);
    setInput("");
  };

  return (
    <div className="flex h-screen">
      {/* Main content area */}
      <div className="flex-1 overflow-auto">{children}</div>

      {/* Chat sidebar */}
      <div className="w-[420px] border-l border-gray-800 flex flex-col bg-gray-950">
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-200">
            Segment Builder
          </h2>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
          {messages.length === 0 && !isGenerating && (
            <div className="text-sm text-gray-400 leading-relaxed">
              <p>
                Describe your target audience and I'll generate a structured
                segment.
              </p>
              <p className="mt-3">
                Try:{" "}
                <strong className="text-gray-300">
                  "Users from the US who signed up in the last 30 days and made
                  a purchase"
                </strong>
              </p>
            </div>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-purple-600 text-white"
                    : "bg-gray-800 text-gray-200"
                }`}
              >
                <AssistantContent content={msg.content} role={msg.role} />
              </div>
            </div>
          ))}

          {/* Active generation indicators */}
          {isGenerating && (
            <div className="space-y-3">
              {currentActivity && (
                <ActivityIndicator
                  activityType="processing"
                  content={currentActivity}
                />
              )}
              {currentReasoning && (
                <ReasoningPanel reasoning={currentReasoning} defaultOpen />
              )}
              {!currentActivity && !currentReasoning && (
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                  Starting generation...
                </div>
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <form
          onSubmit={handleSubmit}
          className="px-4 py-3 border-t border-gray-800"
        >
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                isGenerating
                  ? "Generating segment..."
                  : "Describe your target audience..."
              }
              disabled={isGenerating}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-500 focus:outline-none focus:border-purple-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isGenerating || !input.trim()}
              className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** Render message content — handles **bold** for assistant messages */
function AssistantContent({
  content,
  role,
}: {
  content: string;
  role: string;
}) {
  if (role !== "assistant") return <>{content}</>;

  // Split on **bold** markers and render as React elements
  const parts = content.split(/(\*\*.*?\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}
