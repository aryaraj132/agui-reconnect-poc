"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";

export function Nav() {
  const pathname = usePathname();
  const isEditorPage = pathname === "/template-editor";

  const [editorMode, setEditorMode] = useState<"fe-tools" | "be-only">(
    "fe-tools"
  );

  // Sync with page state via window
  useEffect(() => {
    if (!isEditorPage) return;
    const mode = (window as any).__templateEditorMode;
    if (mode) setEditorMode(mode);
  }, [isEditorPage, pathname]);

  const handleModeToggle = (newMode: "fe-tools" | "be-only") => {
    setEditorMode(newMode);
    const setter = (window as any).__templateEditorSetMode;
    if (setter) setter(newMode);
  };

  const tabs = [
    { href: "/segment", label: "Segment Builder" },
    { href: "/stateful-segment", label: "Stateful Segment" },
    { href: "/template", label: "Template Builder" },
    { href: "/template-editor", label: "Template Editor" },
  ];

  return (
    <header className="border-b border-gray-200 dark:border-gray-700 px-6 py-3 flex items-center justify-between">
      <Link href="/" className="text-lg font-semibold">
        Stream Reconnection Demo
      </Link>
      <div className="flex items-center gap-4">
        <nav className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
          {tabs.map((tab) => {
            const isActive = pathname === tab.href;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-white dark:bg-gray-700 shadow-sm"
                    : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                }`}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>

        {isEditorPage && (
          <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
            <button
              onClick={() => handleModeToggle("fe-tools")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                editorMode === "fe-tools"
                  ? "bg-blue-500 text-white shadow-sm"
                  : "text-gray-500 hover:text-gray-700 dark:text-gray-400"
              }`}
            >
              FE Tools
            </button>
            <button
              onClick={() => handleModeToggle("be-only")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                editorMode === "be-only"
                  ? "bg-blue-500 text-white shadow-sm"
                  : "text-gray-500 hover:text-gray-700 dark:text-gray-400"
              }`}
            >
              BE Only
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
