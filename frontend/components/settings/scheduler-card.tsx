"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { SchedulerStatus } from "@/lib/types";

export function SchedulerCard() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["scheduler"], queryFn: () => api<SchedulerStatus>("scheduler"), refetchInterval: 60_000 });
  const run = useMutation({
    mutationFn: (id: string) => api(`scheduler/${id}/run`, { method: "POST" }),
    onSuccess: () => setTimeout(() => queryClient.invalidateQueries({ queryKey: ["jobs"] }), 1500),
  });

  return (
    <Card title="Automation (IST, NSE trading days)">
      <ul className="divide-y divide-line">
        {data?.jobs.map((job) => (
          <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div>
              <div className="text-sm">{job.label}</div>
              <div className="font-mono text-xs text-muted">
                {job.enabled ? `next ${formatDateTime(job.next_run)}` : "scheduler disabled"}
              </div>
            </div>
            <Button disabled={run.isPending} onClick={() => run.mutate(job.id)}>
              Run now
            </Button>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">
        Jobs that need market data stop with a clear error if today&apos;s Kite login is missing. Log in each morning before 09:15.
      </p>
    </Card>
  );
}
