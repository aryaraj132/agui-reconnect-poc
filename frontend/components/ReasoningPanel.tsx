"use client";

import { useState } from "react";

export function ReasoningPanel({
  reasoning,
  defaultOpen = false,
}: {
  reasoning: string;
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  if (!reasoning) return null;
  return (
    <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 my-2 text-sm overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-3 py-2 flex items-center gap-2 text-xs font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
      >
        <span className={`transition-transform ${isOpen ? "rotate-90" : ""}`}>
          &#9654;
        </span>
        Chain of Thought
      </button>
      {isOpen && (
        <div className="px-3 pb-3 text-xs text-amber-800 dark:text-amber-200 whitespace-pre-wrap font-mono">
          {reasoning}
        </div>
      )}
    </div>
  );
}
