"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import { useJobs } from "@/lib/queries";
import type { JobRun, LlmUsage } from "@/lib/types";

export function NewsCard() {
  const queryClient = useQueryClient();
  const { data: jobs } = useJobs();
  const usage = useQuery({ queryKey: ["llm", "usage"], queryFn: () => api<LlmUsage>("llm/usage") });
  const trigger = useMutation({
    mutationFn: (path: string) => api<JobRun>(path, { method: "POST" }),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["llm"] });
      queryClient.invalidateQueries({ queryKey: ["signals"] });
      queryClient.invalidateQueries({ queryKey: ["regime"] });
    },
  });
  const running = new Set(jobs?.items.filter((j) => j.status === "running").map((j) => j.job_name));
  const u = usage.data;

  return (
    <Card title="Analysis, news & AI research">
      <div className="mb-3 grid gap-1 text-sm">
        <div>
          Model <span className="font-mono text-xs">{u?.model ?? "…"}</span>{" "}
          {u && !u.configured ? <span className="text-negative">· API key missing in .env</span> : null}
        </div>
        {u ? (
          <div className="font-mono text-xs text-muted">
            24h: {u.last_24h.calls} calls · ${u.last_24h.cost_usd.toFixed(4)} · 30d: {u.last_30d.calls} calls · $
            {u.last_30d.cost_usd.toFixed(4)}
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={running.has("ingest_news") || trigger.isPending} onClick={() => trigger.mutate("ingest/news")}>
          {running.has("ingest_news") ? "Collecting…" : "Collect news"}
        </Button>
        <Button
          disabled={!u?.configured || running.has("analyze_news") || trigger.isPending}
          onClick={() => trigger.mutate("analyze/news")}
        >
          {running.has("analyze_news") ? "Analyzing…" : "Analyze sentiment"}
        </Button>
        <Button disabled={running.has("run_analysis") || trigger.isPending} onClick={() => trigger.mutate("analysis/run")}>
          {running.has("run_analysis") ? "Analyzing…" : "Run analysis (indicators + signals)"}
        </Button>
        <Button
          disabled={!u?.configured || running.has("research_top") || trigger.isPending}
          onClick={() => trigger.mutate("research/run?limit=10")}
        >
          {running.has("research_top") ? "Researching…" : "Research top 10 picks"}
        </Button>
      </div>
      {trigger.error ? <p className="mt-3 text-sm text-negative">{trigger.error.message}</p> : null}
    </Card>
  );
}
