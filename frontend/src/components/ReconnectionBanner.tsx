import { useState, useEffect } from "react";
import type { ReconnectPhase } from "@/hooks/useRestoreThread";

interface ActivityContent {
  title: string;
  progress: number;
  details: string;
}

interface ReconnectionBannerProps {
  reconnectPhase: ReconnectPhase;
  currentActivity: ActivityContent | null;
  currentReasoning: string;
}

export function ReconnectionBanner({
  reconnectPhase,
  currentActivity,
  currentReasoning,
}: ReconnectionBannerProps) {
  const [liveDismissed, setLiveDismissed] = useState(false);

  useEffect(() => {
    if (reconnectPhase === "live") {
      const timer = setTimeout(() => setLiveDismissed(true), 2000);
      return () => clearTimeout(timer);
    }
    setLiveDismissed(false);
  }, [reconnectPhase]);

  if (
    reconnectPhase === "idle" ||
    reconnectPhase === "done" ||
    (reconnectPhase === "live" && liveDismissed)
  )
    return null;

  const progress = currentActivity?.progress
    ? Math.round(currentActivity.progress * 100)
    : null;

  const phaseConfig: Record<
    string,
    { bg: string; icon: string; text: string }
  > = {
    connecting: {
      bg: "from-orange-600 to-amber-600",
      icon: "animate-spin",
      text: "Reconnecting to session...",
    },
    catching_up: {
      bg: "from-orange-600 to-amber-600",
      icon: "animate-spin",
      text: currentActivity?.title
        ? `Catching up... ${currentActivity.title}${progress !== null ? ` (${progress}%)` : ""}`
        : "Catching up...",
    },
    live: {
      bg: "from-green-600 to-emerald-600",
      icon: "",
      text: "Caught up! Following live stream...",
    },
    stale_recovery: {
      bg: "from-amber-600 to-yellow-600",
      icon: "animate-pulse",
      text: "Generation was interrupted — restarting automatically...",
    },
    error: {
      bg: "from-red-600 to-rose-600",
      icon: "",
      text: "Could not reconnect",
    },
  };

  const config = phaseConfig[reconnectPhase] || phaseConfig.connecting;

  return (
    <div
      className={`fixed top-0 left-0 right-0 z-50 bg-gradient-to-r ${config.bg} text-white px-4 py-2 shadow-lg`}
    >
      <div className="max-w-4xl mx-auto flex items-center gap-3">
        {config.icon && (
          <div
            className={`w-4 h-4 border-2 border-white/30 border-t-white rounded-full ${config.icon}`}
          />
        )}
        <span className="text-sm font-medium flex-1">{config.text}</span>
        {reconnectPhase === "catching_up" &&
          progress !== null && (
            <div className="w-32 h-1.5 bg-white/20 rounded-full overflow-hidden">
              <div
                className="h-full bg-white rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
      </div>
      {reconnectPhase === "catching_up" && currentActivity?.details && (
        <div className="max-w-4xl mx-auto mt-1">
          <span className="text-xs text-white/70 truncate block">
            {currentActivity.details}
          </span>
        </div>
      )}
      {reconnectPhase === "catching_up" && currentReasoning && (
        <div className="max-w-4xl mx-auto mt-1">
          <span className="text-xs text-white/60 font-mono truncate block">
            {currentReasoning.slice(-80)}
          </span>
        </div>
      )}
    </div>
  );
}
