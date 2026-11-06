"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useJobs, useKiteStatus } from "@/lib/queries";
import type { JobRun } from "@/lib/types";

const ACTIONS = [
  { label: "1 · Sync instruments + NIFTY 500", path: "ingest/instruments", job: "ingest_instruments" },
  { label: "2 · Daily candles", path: "ingest/candles?interval=day", job: "ingest_candles_day" },
  { label: "3 · 60-minute candles", path: "ingest/candles?interval=60m", job: "ingest_candles_60m" },
];

const STATUS_TONE: Record<JobRun["status"], string> = {
  running: "text-accent",
  success: "text-positive",
  failed: "text-negative",
};

export function DataCard() {
  const queryClient = useQueryClient();
  const { data: kite } = useKiteStatus();
  const { data: jobs } = useJobs();
  const trigger = useMutation({
    mutationFn: (path: string) => api<JobRun>(path, { method: "POST" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });
  const running = new Set(jobs?.items.filter((j) => j.status === "running").map((j) => j.job_name));

  return (
    <Card title="Market data & jobs">
      <p className="mb-3 text-sm text-muted">
        Downloads are incremental. Each run fetches only the dates missing from SQL Server.
      </p>
      <div className="flex flex-wrap gap-2">
        {ACTIONS.map((action) => (
          <Button
            key={action.path}
            disabled={!kite?.connected || running.has(action.job) || trigger.isPending}
            onClick={() => trigger.mutate(action.path)}
          >
            {running.has(action.job) ? "Running…" : action.label}
          </Button>
        ))}
      </div>
      {trigger.error ? <p className="mt-3 text-sm text-negative">{trigger.error.message}</p> : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr>
              <th className="py-2 font-normal">Job</th>
              <th className="py-2 font-normal">Status</th>
              <th className="py-2 font-normal">Started</th>
              <th className="py-2 text-right font-normal">Rows</th>
              <th className="py-2 pl-4 font-normal">Details</th>
            </tr>
          </thead>
          <tbody>
            {jobs?.items.map((job) => (
              <tr key={job.id} className="border-t border-line align-top">
                <td className="py-2 font-mono text-xs">{job.job_name}</td>
                <td className={`py-2 ${STATUS_TONE[job.status]}`}>{job.status}</td>
                <td className="py-2 text-muted">{formatDateTime(job.started_at)}</td>
                <td className="py-2 text-right tabular-nums">{job.rows_affected ?? "—"}</td>
                <td className="max-w-xs py-2 pl-4 font-mono text-xs text-muted">{job.error ?? job.details ?? ""}</td>
              </tr>
            ))}
            {jobs && jobs.items.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-3 text-muted">
                  No jobs yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
