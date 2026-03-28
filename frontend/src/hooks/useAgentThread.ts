import { useState, useRef, useEffect, useCallback } from "react";

export function useAgentThread() {
  // Read the initial thread ID from the URL query string
  const [threadFromUrl, setThreadFromUrl] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("thread");
  });

  const generatedId = useRef(crypto.randomUUID());
  const newThreadIds = useRef(new Set<string>([generatedId.current]));
  const threadId = threadFromUrl || generatedId.current;

  // A thread is "existing" only if it came from the URL and we didn't generate it
  const isExistingThread = !!threadFromUrl && !newThreadIds.current.has(threadFromUrl);

  // Brief unmount gap when switching threads to let components clean up
  const [mountedThreadId, setMountedThreadId] = useState(threadId);
  const [ready, setReady] = useState(true);

  useEffect(() => {
    if (threadId !== mountedThreadId) {
      setReady(false);
      const timer = setTimeout(() => {
        setMountedThreadId(threadId);
        setReady(true);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [threadId, mountedThreadId]);

  // Update URL to include thread param if missing (on mount)
  useEffect(() => {
    if (!threadFromUrl) {
      const pathname = window.location.pathname;
      window.history.replaceState(
        null,
        "",
        `${pathname}?thread=${generatedId.current}`
      );
      setThreadFromUrl(generatedId.current);
    }
  }, [threadFromUrl]);

  // Listen for browser back/forward navigation
  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      setThreadFromUrl(params.get("thread"));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const startNewThread = useCallback(() => {
    const newId = crypto.randomUUID();
    newThreadIds.current.add(newId);
    const pathname = window.location.pathname;
    window.history.pushState(null, "", `${pathname}?thread=${newId}`);
    setThreadFromUrl(newId);
  }, []);

  const switchToThread = useCallback((id: string) => {
    const pathname = window.location.pathname;
    window.history.pushState(null, "", `${pathname}?thread=${id}`);
    setThreadFromUrl(id);
  }, []);

  return {
    threadId: mountedThreadId,
    isExistingThread,
    ready,
    startNewThread,
    switchToThread,
  };
}
