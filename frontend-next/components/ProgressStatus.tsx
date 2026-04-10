"use client";

interface ProgressStatusProps {
  status: string;
  node: string;
  nodeIndex: number;
  totalNodes: number;
  nodeLabels?: Record<string, string>;
  nodeOrder?: string[];
  completedLabel?: string;
}

const SEGMENT_NODE_LABELS: Record<string, string> = {
  analyze_requirements: "Analyze",
  extract_entities: "Entities",
  validate_fields: "Validate",
  map_operators: "Operators",
  generate_conditions: "Conditions",
  optimize_conditions: "Optimize",
  estimate_scope: "Scope",
  build_segment: "Build",
};

const SEGMENT_NODE_ORDER = [
  "analyze_requirements",
  "extract_entities",
  "validate_fields",
  "map_operators",
  "generate_conditions",
  "optimize_conditions",
  "estimate_scope",
  "build_segment",
];

export function ProgressStatus({
  status,
  node,
  nodeIndex,
  totalNodes,
  nodeLabels = SEGMENT_NODE_LABELS,
  nodeOrder = SEGMENT_NODE_ORDER,
  completedLabel = "Segment Complete",
}: ProgressStatusProps) {
  const isCompleted = status === "completed";

  return (
    <div className="w-full max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {isCompleted
            ? completedLabel
            : `${nodeLabels[node] || node}...`}
        </span>
        <span className="text-xs text-gray-500">
          {isCompleted
            ? `${totalNodes}/${totalNodes}`
            : `${nodeIndex + 1}/${totalNodes}`}
        </span>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-1">
        {nodeOrder.slice(0, totalNodes).map((nodeName, i) => {
          let stepState: "completed" | "active" | "pending";
          if (isCompleted || i < nodeIndex) {
            stepState = "completed";
          } else if (i === nodeIndex) {
            stepState = "active";
          } else {
            stepState = "pending";
          }

          return (
            <div key={nodeName} className="flex-1 flex flex-col items-center">
              {/* Step indicator */}
              <div className="flex items-center w-full">
                {/* Line before */}
                {i > 0 && (
                  <div
                    className={`flex-1 h-0.5 ${
                      stepState === "pending"
                        ? "bg-gray-200 dark:bg-gray-700"
                        : "bg-green-500"
                    }`}
                  />
                )}

                {/* Circle */}
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
                    stepState === "completed"
                      ? "bg-green-500 text-white"
                      : stepState === "active"
                      ? "bg-blue-500 text-white"
                      : "bg-gray-200 dark:bg-gray-700 text-gray-400"
                  }`}
                >
                  {stepState === "completed" ? (
                    <svg
                      className="w-3.5 h-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={3}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  ) : stepState === "active" ? (
                    <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-gray-400" />
                  )}
                </div>

                {/* Line after */}
                {i < totalNodes - 1 && (
                  <div
                    className={`flex-1 h-0.5 ${
                      stepState === "completed" && i < nodeIndex
                        ? "bg-green-500"
                        : "bg-gray-200 dark:bg-gray-700"
                    }`}
                  />
                )}
              </div>

              {/* Label */}
              <span
                className={`text-[10px] mt-1 text-center leading-tight ${
                  stepState === "completed"
                    ? "text-green-600 dark:text-green-400"
                    : stepState === "active"
                    ? "text-blue-600 dark:text-blue-400 font-medium"
                    : "text-gray-400"
                }`}
              >
                {nodeLabels[nodeName] || nodeName}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
