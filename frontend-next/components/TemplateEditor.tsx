"use client";

import type { EmailTemplate } from "@/lib/types";
import { TemplatePreview } from "./TemplatePreview";

interface TemplateEditorProps {
  template: EmailTemplate;
  onHtmlChange?: (html: string) => void;
}

export function TemplateEditor({ template, onHtmlChange }: TemplateEditorProps) {
  return (
    <div className="flex flex-col h-full">
      {/* Metadata bar */}
      <div className="flex items-center gap-4 px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 truncate">
          {template.subject || "Untitled"}
        </h3>
        {template.preview_text && (
          <span className="text-xs text-gray-500 truncate hidden sm:inline">
            {template.preview_text}
          </span>
        )}
        <span className="text-xs text-gray-400 ml-auto shrink-0">
          v{template.version}
        </span>
      </div>

      {/* Editable preview */}
      <div className="flex-1 min-h-0">
        <TemplatePreview
          html={template.html}
          css={template.css}
          editable
          onHtmlChange={onHtmlChange}
        />
      </div>
    </div>
  );
}
