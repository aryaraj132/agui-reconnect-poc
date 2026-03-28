interface ActivityContent {
  title: string;
  progress: number;
  details: string;
}

export function ActivityIndicator({
  content,
}: {
  activityType: string;
  content: ActivityContent;
}) {
  const percentage = Math.round(content.progress * 100);
  return (
    <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 p-3 my-2 text-sm">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
        <span className="text-xs font-medium text-blue-700 dark:text-blue-300">
          {content.title}
        </span>
        <span className="text-xs text-blue-500 ml-auto">{percentage}%</span>
      </div>
      <div className="w-full bg-blue-200 dark:bg-blue-800 rounded-full h-1.5">
        <div
          className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
          style={{ width: `${percentage}%` }}
        />
      </div>
      <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
        {content.details}
      </p>
    </div>
  );
}
