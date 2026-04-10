"use client";

import type { TemplateSection } from "@/lib/types";
import { TEMPLATE_COMPONENTS } from "@/lib/template-components";
import { useState } from "react";

interface SectionDropZoneProps {
  sections: TemplateSection[];
  disabled?: boolean;
  onAddSection: (type: string, position?: number) => void;
  onRemoveSection: (sectionId: string) => void;
}

/**
 * A section card that doubles as a drop target.
 * Dropping on the top half inserts before; bottom half inserts after.
 */
function SectionCard({
  section,
  index,
  disabled,
  onAddSection,
  onRemoveSection,
}: {
  section: TemplateSection;
  index: number;
  disabled: boolean;
  onAddSection: (type: string, position: number) => void;
  onRemoveSection: (id: string) => void;
}) {
  const [dropHalf, setDropHalf] = useState<"top" | "bottom" | null>(null);

  const labelFor = (type: string) =>
    TEMPLATE_COMPONENTS.find((c) => c.type === type)?.label ?? type;

  const handleDragOver = (e: React.DragEvent) => {
    if (disabled) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
    const rect = e.currentTarget.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    setDropHalf(e.clientY < midY ? "top" : "bottom");
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDropHalf(null);
    if (disabled) return;
    const type = e.dataTransfer.getData("component-type");
    if (type) {
      // Compute position from drop coordinates directly (more robust
      // than relying on dragover state which may not have fired yet)
      const rect = e.currentTarget.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      const position = e.clientY < midY ? index : index + 1;
      onAddSection(type, position);
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={() => setDropHalf(null)}
      onDrop={handleDrop}
      className="relative"
    >
      {/* Top drop indicator line */}
      {dropHalf === "top" && (
        <div className="absolute top-0 left-0 right-0 h-0.5 bg-blue-500 z-10 -translate-y-px" />
      )}

      {/* Section card */}
      <div className="group flex items-center gap-2 p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <span className="w-6 h-6 flex items-center justify-center rounded bg-gray-200 dark:bg-gray-700 text-xs font-mono font-bold shrink-0">
          {TEMPLATE_COMPONENTS.find((c) => c.type === section.type)?.icon ??
            "?"}
        </span>
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium text-gray-500">
            {labelFor(section.type)}
          </span>
          <p className="text-sm text-gray-700 dark:text-gray-300 truncate">
            {section.content || "(empty)"}
          </p>
        </div>
        {!disabled && (
          <button
            onClick={() => onRemoveSection(section.id)}
            className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 text-xs px-1 transition-opacity"
            title="Remove section"
          >
            x
          </button>
        )}
      </div>

      {/* Bottom drop indicator line */}
      {dropHalf === "bottom" && (
        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-500 z-10 translate-y-px" />
      )}
    </div>
  );
}

export function SectionDropZone({
  sections,
  disabled = false,
  onAddSection,
  onRemoveSection,
}: SectionDropZoneProps) {
  const [containerDragOver, setContainerDragOver] = useState(false);

  const handleContainerDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setContainerDragOver(false);
    if (disabled) return;
    const type = e.dataTransfer.getData("component-type");
    if (type) {
      // Append to end (fallback when dropping on empty space)
      onAddSection(type, sections.length);
    }
  };

  return (
    <div
      onDragOver={(e) => {
        if (disabled) return;
        e.preventDefault();
        setContainerDragOver(true);
      }}
      onDragLeave={(e) => {
        // Only clear if leaving the container itself, not entering a child
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
          setContainerDragOver(false);
        }
      }}
      onDrop={handleContainerDrop}
      className={`flex-1 min-h-0 overflow-y-auto p-4 transition-colors ${
        containerDragOver && !disabled
          ? "bg-blue-50/50 dark:bg-blue-900/10"
          : "bg-white dark:bg-gray-950"
      }`}
    >
      {sections.length === 0 ? (
        <div className="flex items-center justify-center h-full">
          <p className="text-sm text-gray-400">
            {disabled
              ? "AI is working..."
              : "Drag components here to build your template"}
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          {sections.map((section, index) => (
            <SectionCard
              key={section.id}
              section={section}
              index={index}
              disabled={disabled}
              onAddSection={onAddSection}
              onRemoveSection={onRemoveSection}
            />
          ))}
        </div>
      )}
    </div>
  );
}
