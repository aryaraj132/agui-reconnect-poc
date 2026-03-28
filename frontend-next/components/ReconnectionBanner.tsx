"use client";

interface ActivityContent {
  title: string;
  progress: number;
  details: string;
}

interface ReconnectionBannerProps {
  isRestoring: boolean;
  isStreamActive: boolean;
  isCatchingUp: boolean;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
}

export function ReconnectionBanner({
  isRestoring,
  isStreamActive,
  isCatchingUp,
  currentActivity,
  currentReasoning,
}: ReconnectionBannerProps) {
  if (!isRestoring && !isStreamActive) return null;

  const percentage = currentActivity
    ? Math.round(currentActivity.progress * 100)
    : 0;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-gradient-to-r from-orange-500 to-amber-500 text-white shadow-lg">
      <div className="max-w-4xl mx-auto px-4 py-2">
        <div className="flex items-center gap-3">
          {/* Spinner */}
          <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin shrink-0" />

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium truncate">
                {isStreamActive
                  ? isCatchingUp
                    ? "Catching up..."
                    : currentActivity?.title || "Following live stream..."
                  : "Restoring session..."}
              </span>
              {currentActivity && (
                <span className="text-xs opacity-80 shrink-0">
                  {percentage}%
                </span>
              )}
            </div>

            {currentActivity && (
              <div className="mt-1">
                <div className="w-full bg-white/20 rounded-full h-1">
                  <div
                    className="bg-white h-1 rounded-full transition-all duration-300"
                    style={{ width: `${percentage}%` }}
                  />
                </div>
                <p className="text-xs opacity-70 mt-0.5 truncate">
                  {currentActivity.details}
                </p>
              </div>
            )}

            {currentReasoning && (
              <p className="text-xs opacity-60 mt-1 truncate font-mono">
                {currentReasoning.slice(-80)}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
