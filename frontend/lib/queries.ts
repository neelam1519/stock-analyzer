import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { JobRun, KiteStatus } from "@/lib/types";

export function useKiteStatus() {
  return useQuery({ queryKey: ["kite", "status"], queryFn: () => api<KiteStatus>("kite/status") });
}

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: () => api<{ items: JobRun[] }>("jobs?limit=15"),
    refetchInterval: (query) => (query.state.data?.items.some((job) => job.status === "running") ? 3000 : false),
  });
}
