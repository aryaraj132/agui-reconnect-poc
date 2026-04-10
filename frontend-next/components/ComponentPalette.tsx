"use client";

import { TEMPLATE_COMPONENTS } from "@/lib/template-components";

interface ComponentPaletteProps {
  disabled?: boolean;
}

export function ComponentPalette({ disabled = false }: ComponentPaletteProps) {
  return (
    <div className="w-48 border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 p-3 overflow-y-auto">
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-3">
        Components
      </h3>
      <div className="space-y-2">
        {TEMPLATE_COMPONENTS.map((comp) => (
          <div
            key={comp.type}
            draggable={!disabled}
            onDragStart={(e) => {
              if (disabled) return;
              e.dataTransfer.setData("component-type", comp.type);
              e.dataTransfer.effectAllowed = "copy";
            }}
            className={`flex items-center gap-2 px-3 py-2 rounded-md border text-sm transition-colors ${
              disabled
                ? "opacity-50 cursor-not-allowed border-gray-200 dark:border-gray-700"
                : "cursor-grab active:cursor-grabbing border-gray-300 dark:border-gray-600 hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20"
            }`}
          >
            <span className="w-6 h-6 flex items-center justify-center rounded bg-gray-200 dark:bg-gray-700 text-xs font-mono font-bold">
              {comp.icon}
            </span>
            <span className="truncate">{comp.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
