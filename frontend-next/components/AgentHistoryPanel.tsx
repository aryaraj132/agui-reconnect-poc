"use client";

import { useState } from "react";
import { useThreadHistory } from "@/hooks/useThreadHistory";

interface AgentHistoryPanelProps {
  agentType: string;
  currentThreadId: string;
  onNewThread: () => void;
  onSelectThread: (threadId: string) => void;
}

export function AgentHistoryPanel({
  agentType,
  currentThreadId,
  onNewThread,
  onSelectThread,
}: AgentHistoryPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { threads, loading, refetch } = useThreadHistory(agentType);

  return (
    <>
      {/* Toggle button - always visible */}
      <button
        onClick={() => {
          setIsOpen(!isOpen);
          if (!isOpen) refetch();
        }}
        className="fixed left-0 top-1/2 -translate-y-1/2 z-30 bg-white dark:bg-gray-900 border border-l-0 border-gray-200 dark:border-gray-700 rounded-r-lg px-1.5 py-3 shadow-sm hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        title={isOpen ? "Close history" : "Open history"}
      >
        <span className="text-xs font-medium text-gray-500 [writing-mode:vertical-lr]">
          {isOpen ? "Close" : "History"}
        </span>
      </button>

      {/* History panel */}
      {isOpen && (
        <div className="fixed left-0 top-0 h-full w-64 z-20 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 shadow-lg flex flex-col">
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              History
            </span>
            <button
              onClick={onNewThread}
              className="text-xs bg-blue-500 text-white px-2.5 py-1 rounded-md hover:bg-blue-600 transition-colors"
            >
              + New
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading && (
              <p className="px-4 py-3 text-xs text-gray-400">Loading...</p>
            )}
            {!loading && threads.length === 0 && (
              <p className="px-4 py-3 text-xs text-gray-400">
                No past conversations
              </p>
            )}
            {threads.map((thread) => (
              <button
                key={thread.id}
                onClick={() => onSelectThread(thread.id)}
                className={`w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors ${
                  thread.id === currentThreadId
                    ? "bg-blue-50 dark:bg-blue-900/20 border-l-2 border-l-blue-500"
                    : ""
                }`}
              >
                <p className="text-xs text-gray-700 dark:text-gray-300 truncate">
                  {thread.first_message || "Empty conversation"}
                </p>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-xs text-gray-400">
                    {thread.message_count} msg
                    {thread.message_count !== 1 ? "s" : ""}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(thread.updated_at).toLocaleDateString()}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
