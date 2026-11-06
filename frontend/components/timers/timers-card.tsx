"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import { JOB_NAMES, ago, countdown, istClock, istDate, istTime, useNow, useScheduler } from "@/lib/timers";
import type { DataFreshness, JobLastRun, SchedulerJob, SchedulerStatus } from "@/lib/types";

const PRICE_STALE_MS = 6 * 60_000;
const KITE_WARN_MS = 60 * 60_000;

function useRefetchWhenDue(data: SchedulerStatus | undefined, now: number | null) {
  const queryClient = useQueryClient();
  const due = now != null && (data?.jobs.some((job) => job.next_run && Date.parse(job.next_run) + 3000 <= now) ?? false);
  useEffect(() => {
    if (due) queryClient.invalidateQueries({ queryKey: ["scheduler"] });
  }, [due, queryClient]);
}

function Tile({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: string }) {
  return (
    <div className="rounded-md border border-line bg-surface-strong/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`font-mono text-sm tabular-nums ${tone ?? ""}`}>{value}</div>
      {detail ? <div className="truncate text-xs text-muted">{detail}</div> : null}
    </div>
  );
}

function StatusDot({ run }: { run: JobLastRun | null }) {
  const tone = !run ? "bg-muted" : run.status === "failed" ? "bg-negative" : run.status === "running" ? "bg-accent" : "bg-positive";
  return <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${tone}`} />;
}

export function nextJob(jobs: SchedulerJob[]) {
  return jobs
    .filter((job) => job.next_run)
    .sort((a, b) => Date.parse(a.next_run as string) - Date.parse(b.next_run as string))[0];
}

function TopTiles({ data, now }: { data: SchedulerStatus; now: number }) {
  const upcoming = nextJob(data.jobs);
  const kiteLeft = data.kite.expires_at ? Date.parse(data.kite.expires_at) - now : -1;
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      <Tile
        label="Market"
        value={data.market.open ? `Closes ${countdown(data.market.closes_at, now)}` : `Opens ${countdown(data.market.opens_at, now)}`}
        detail={data.market.open ? `Open until ${istTime(data.market.closes_at, now)}` : `Next open ${istTime(data.market.opens_at, now)}`}
        tone={data.market.open ? "text-positive" : undefined}
      />
      <Tile
        label="Kite login"
        value={kiteLeft > 0 ? `Expires ${countdown(data.kite.expires_at, now)}` : "Expired · log in"}
        detail={data.kite.login_at ? `Logged in ${ago(data.kite.login_at, now)}` : "Never logged in"}
        tone={kiteLeft <= 0 ? "text-negative" : kiteLeft < KITE_WARN_MS ? "text-accent" : undefined}
      />
      <Tile
        label="Next job"
        value={upcoming ? `${JOB_NAMES[upcoming.id] ?? upcoming.id} ${countdown(upcoming.next_run, now)}` : "Scheduler off"}
        detail={upcoming ? `at ${istTime(upcoming.next_run, now)}` : "Start the backend to run jobs"}
        tone={upcoming ? undefined : "text-negative"}
      />
      <Tile label="Server time (IST)" value={istClock(now)} detail={data.market.trading_day ? "Trading day" : "No trading today"} />
    </div>
  );
}

function LastRun({ run, now }: { run: JobLastRun | null; now: number }) {
  if (!run) return <span className="text-muted">No run yet</span>;
  const duration = run.started_at && run.finished_at ? (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000 : null;
  return (
    <div className="min-w-0">
      <div className={run.status === "failed" ? "text-negative" : undefined}>
        {run.status === "running" ? "Running · started " : run.status === "failed" ? "Failed " : ""}
        {ago(run.started_at, now)}
        <span className="text-muted">
          {" "}
          · {istTime(run.started_at, now)}
          {duration != null && duration >= 1 ? ` · took ${Math.round(duration)}s` : ""}
        </span>
      </div>
      {run.error || run.details ? (
        <div className={`truncate text-xs ${run.error ? "text-negative" : "text-muted"}`} title={run.error ?? run.details ?? undefined}>
          {run.error ?? run.details}
        </div>
      ) : null}
    </div>
  );
}

export function JobsList({ data, now, showRun = true }: { data: SchedulerStatus; now: number; showRun?: boolean }) {
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: (id: string) => api(`scheduler/${id}/run`, { method: "POST" }),
    onSuccess: () =>
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["scheduler"] });
        queryClient.invalidateQueries({ queryKey: ["jobs"] });
      }, 1500),
  });
  return (
    <ul className="divide-y divide-line">
      {data.jobs.map((job) => (
        <li key={job.id} className="grid gap-x-4 gap-y-1 py-2.5 text-sm md:grid-cols-[minmax(0,1.3fr)_minmax(0,1.5fr)_minmax(0,0.8fr)_auto] md:items-center">
          <div className="flex min-w-0 gap-2">
            <StatusDot run={job.last_run} />
            <div className="min-w-0">
              <div className="truncate" title={job.title}>
                <span className="font-medium">{JOB_NAMES[job.id] ?? job.id}</span>
                <span className="text-muted"> · {job.title}</span>
              </div>
              <div className="font-mono text-xs text-muted">{job.schedule}</div>
            </div>
          </div>
          <div className="pl-4 font-mono text-xs md:pl-0">
            <span className="block text-[10px] uppercase tracking-wide text-muted md:hidden">Last run</span>
            <LastRun run={job.last_run} now={now} />
          </div>
          <div className="pl-4 font-mono text-xs md:pl-0">
            <span className="block text-[10px] uppercase tracking-wide text-muted md:hidden">Next run</span>
            {job.enabled ? (
              <>
                <span className="tabular-nums">{countdown(job.next_run, now)}</span>
                <span className="text-muted"> · {istTime(job.next_run, now)}</span>
              </>
            ) : (
              <span className="text-negative">scheduler off</span>
            )}
          </div>
          {showRun ? (
            <div className="pl-4 md:pl-0">
              <Button disabled={run.isPending} onClick={() => run.mutate(job.id)}>
                Run now
              </Button>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function freshnessTone(item: DataFreshness, data: SchedulerStatus, now: number) {
  if (!item.at && !item.as_of) return "text-negative";
  if (item.key === "prices" && data.market.open && item.at && now - Date.parse(item.at) > PRICE_STALE_MS) return "text-negative";
  return undefined;
}

function Freshness({ data, now }: { data: SchedulerStatus; now: number }) {
  const jobs = Object.fromEntries(data.jobs.map((job) => [job.id, job]));
  return (
    <ul className="divide-y divide-line">
      {data.data.map((item) => {
        const job = item.job ? jobs[item.job] : undefined;
        return (
          <li key={item.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-0.5 py-2 text-sm sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)]">
            <div className="truncate">{item.label}</div>
            <div className={`text-right font-mono text-xs sm:text-left ${freshnessTone(item, data, now) ?? ""}`}>
              {item.at ? ago(item.at, now) : item.as_of ? "" : "never"}
              {item.as_of ? <span className={item.at ? "text-muted" : undefined}>{item.at ? " · " : ""}as of {istDate(item.as_of)}</span> : null}
            </div>
            <div className="col-span-2 font-mono text-xs text-muted sm:col-span-1">
              {job?.next_run ? (
                <>
                  next {countdown(job.next_run, now)} · {JOB_NAMES[job.id] ?? job.id}
                </>
              ) : (
                "—"
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function TimersCard() {
  const { data, error, offset } = useScheduler();
  const now = useNow(offset);
  useRefetchWhenDue(data, now);

  return (
    <Card title="Timers">
      {error ? <p className="text-sm text-negative">{error.message}</p> : null}
      {(!data || now == null) && !error ? <div className="h-40 animate-pulse rounded-md bg-surface-strong/40" /> : null}
      {data && now != null ? (
        <div className="grid gap-4">
          <TopTiles data={data} now={now} />
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Scheduled jobs</h3>
            <JobsList data={data} now={now} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Latest data</h3>
            <Freshness data={data} now={now} />
          </div>
        </div>
      ) : null}
    </Card>
  );
}

export function useSchedulerClock() {
  const scheduler = useScheduler();
  const now = useNow(scheduler.offset);
  useRefetchWhenDue(scheduler.data, now);
  return { ...scheduler, now };
}
