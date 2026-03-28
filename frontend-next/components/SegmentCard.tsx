interface Condition {
  field: string;
  operator: string;
  value: string | number | string[];
}

interface ConditionGroup {
  logical_operator: "AND" | "OR";
  conditions: Condition[];
}

interface Segment {
  name: string;
  description: string;
  condition_groups: ConditionGroup[];
  estimated_scope?: string;
}

export function SegmentCard({ segment }: { segment: Segment }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden text-sm my-2 w-full">
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold text-gray-900 dark:text-gray-100">
            {segment.name}
          </span>
          <span className="shrink-0 text-xs bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300 px-2 py-0.5 rounded-full">
            Segment
          </span>
        </div>
        <p className="text-gray-500 dark:text-gray-400 mt-1 text-xs">
          {segment.description}
        </p>
      </div>

      <div className="px-4 py-3 space-y-4">
        {(segment.condition_groups ?? []).map((group, gi) => (
          <div key={gi}>
            {gi > 0 && (
              <div className="text-xs text-gray-400 font-medium text-center mb-3">
                — OR —
              </div>
            )}
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-2 font-medium">
              Group {gi + 1} &middot; {group.logical_operator}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(group.conditions ?? []).map((cond, ci) => (
                <span
                  key={ci}
                  className="inline-flex items-center gap-1 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 px-2 py-1 rounded-md text-xs font-mono"
                >
                  <span className="text-purple-600 dark:text-purple-400">
                    {cond.field}
                  </span>
                  <span className="text-gray-400">{cond.operator}</span>
                  <span>
                    {Array.isArray(cond.value)
                      ? cond.value.join(", ")
                      : String(cond.value)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      {segment.estimated_scope && (
        <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400">
          Scope: {segment.estimated_scope}
        </div>
      )}
    </div>
  );
}
