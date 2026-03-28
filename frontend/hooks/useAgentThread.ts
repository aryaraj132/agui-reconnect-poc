"use client";

import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useState, useRef, useEffect, useCallback } from "react";

export function useAgentThread() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const threadFromUrl = searchParams.get("thread");
  const generatedId = useRef(crypto.randomUUID());
  const newThreadIds = useRef(new Set<string>([generatedId.current]));
  const threadId = threadFromUrl || generatedId.current;

  // A thread is "existing" only if it came from the URL and we didn't generate it
  const isExistingThread = !!threadFromUrl && !newThreadIds.current.has(threadFromUrl);

  // Brief unmount gap when switching threads to let CopilotKit clean up
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

  // Update URL to include thread param if missing
  useEffect(() => {
    if (!threadFromUrl) {
      router.replace(`${pathname}?thread=${generatedId.current}`, {
        scroll: false,
      });
    }
  }, [threadFromUrl, pathname, router]);

  const startNewThread = useCallback(() => {
    const newId = crypto.randomUUID();
    newThreadIds.current.add(newId);
    router.push(`${pathname}?thread=${newId}`);
  }, [pathname, router]);

  const switchToThread = useCallback(
    (id: string) => {
      router.push(`${pathname}?thread=${id}`);
    },
    [pathname, router],
  );

  return { threadId: mountedThreadId, isExistingThread, ready, startNewThread, switchToThread };
}
