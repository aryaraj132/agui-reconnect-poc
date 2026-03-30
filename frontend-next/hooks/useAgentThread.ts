import { useState, useRef, useEffect, useCallback } from "react";

export function useAgentThread() {
  const [threadFromUrl, setThreadFromUrl] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const params = new URLSearchParams(window.location.search);
    return params.get("thread");
  });

  const generatedId = useRef(crypto.randomUUID());
  const threadId = threadFromUrl || generatedId.current;

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

  useEffect(() => {
    if (!threadFromUrl) {
      const pathname = window.location.pathname;
      window.history.replaceState(null, "", `${pathname}?thread=${generatedId.current}`);
      setThreadFromUrl(generatedId.current);
    }
  }, [threadFromUrl]);

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
    const pathname = window.location.pathname;
    window.history.pushState(null, "", `${pathname}?thread=${newId}`);
    setThreadFromUrl(newId);
  }, []);

  const switchToThread = useCallback((id: string) => {
    const pathname = window.location.pathname;
    window.history.pushState(null, "", `${pathname}?thread=${id}`);
    setThreadFromUrl(id);
  }, []);

  return { threadId: mountedThreadId, ready, startNewThread, switchToThread };
}
