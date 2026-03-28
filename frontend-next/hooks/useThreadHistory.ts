"use client";

import { useState, useEffect, useCallback } from "react";
import type { ThreadSummary } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export function useThreadHistory(agentType?: string) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchThreads = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const url = agentType
        ? `${BACKEND_URL}/api/v1/threads?agent_type=${agentType}`
        : `${BACKEND_URL}/api/v1/threads`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Failed to fetch threads: ${res.status}`);
      const data = await res.json();
      setThreads(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [agentType]);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads]);

  return { threads, loading, error, refetch: fetchThreads };
}
