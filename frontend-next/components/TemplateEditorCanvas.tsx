"use client";

import type { EmailTemplate } from "@/lib/types";
import { ComponentPalette } from "./ComponentPalette";
import { SectionDropZone } from "./SectionDropZone";
import { TemplatePreview } from "./TemplatePreview";

interface TemplateEditorCanvasProps {
  template: EmailTemplate;
  disabled?: boolean;
  onAddSection: (type: string, position?: number) => void;
  onRemoveSection: (sectionId: string) => void;
  onHtmlChange?: (html: string) => void;
}

export function TemplateEditorCanvas({
  template,
  disabled = false,
  onAddSection,
  onRemoveSection,
  onHtmlChange,
}: TemplateEditorCanvasProps) {
  return (
    <div className="flex h-full">
      {/* Left: Component palette */}
      <ComponentPalette disabled={disabled} />

      {/* Center: Section list (drop zone) */}
      <div className="w-72 border-r border-gray-200 dark:border-gray-700 flex flex-col">
        <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
          <span className="text-xs font-medium text-gray-500">Sections</span>
          <span className="text-xs text-gray-400">
            {template.sections?.length ?? 0} items
          </span>
        </div>
        <SectionDropZone
          sections={template.sections ?? []}
          disabled={disabled}
          onAddSection={onAddSection}
          onRemoveSection={onRemoveSection}
        />
      </div>

      {/* Right: Live preview */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Metadata bar */}
        <div className="flex items-center gap-4 px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 truncate">
            {template.subject || "Untitled Template"}
          </h3>
          {template.preview_text && (
            <span className="text-xs text-gray-500 truncate hidden sm:inline">
              {template.preview_text}
            </span>
          )}
          <span className="text-xs text-gray-400 ml-auto shrink-0">
            v{template.version ?? 0}
          </span>
        </div>

        {/* Preview iframe */}
        <div className="flex-1 min-h-0">
          <TemplatePreview
            html={template.html ?? ""}
            css={template.css ?? ""}
            editable={!disabled}
            onHtmlChange={onHtmlChange}
          />
        </div>
      </div>
    </div>
  );
}
