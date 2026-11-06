"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "@/components/card";
import { EquityChart } from "@/components/backtests/equity-chart";
import { api } from "@/lib/api";
import { formatPrice, toneFor } from "@/lib/format";
import { useJobs } from "@/lib/queries";
import type { ActiveParams, BacktestDetail, BacktestMetrics, BacktestSummary, JobRun, StrategyParamsShape } from "@/lib/types";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);

function entryRule(p: StrategyParamsShape) {
  if (p.model === "momentum") {
    return `momentum top ${p.top_n}, exit below rank ${p.exit_rank}${p.market_filter ? " · NIFTY above 200d" : ""}`;
  }
  return `score ≥ ${p.buy_threshold} · enter in ${p.entry_regimes.length === 4 ? "all regimes" : p.entry_regimes.join("/")}`;
}

function paramsLine(p: StrategyParamsShape) {
  return `${entryRule(p)} · stop ${p.stop_atr}×ATR · target ${p.target_atr}×ATR · max ${p.max_hold_days}d · trail ${p.trail_atr}×ATR`;
}

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-md border border-line p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-mono text-lg tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function Verdict({ m }: { m: BacktestMetrics }) {
  const beats = m.cagr_pct > m.benchmark_cagr_pct;
  const shallower = m.max_drawdown_pct > m.benchmark_max_drawdown_pct;
  const text =
    m.trades < 30
      ? "Too few trades to judge."
      : beats && m.sharpe >= 0.8
        ? "Beat NIFTY with a reasonable risk-adjusted return over this period."
        : beats
          ? "Beat NIFTY, but the risk-adjusted return is weak."
          : shallower
            ? "Lagged NIFTY but with a shallower drawdown."
            : "Did not beat simply holding NIFTY over this period.";
  return <p className={`text-sm ${beats && m.sharpe >= 0.8 ? "text-positive" : beats ? "text-accent" : "text-negative"}`}>{text}</p>;
}

function Detail({ id, onApplied }: { id: number; onApplied: () => void }) {
  const { data } = useQuery({ queryKey: ["backtest", id], queryFn: () => api<BacktestDetail>(`backtests/${id}`) });
  const apply = useMutation({ mutationFn: () => api<ActiveParams>(`backtests/${id}/apply`, { method: "POST" }), onSuccess: onApplied });
  if (!data) return <div className="h-64 animate-pulse rounded-lg bg-surface" />;
  const m = data.metrics;

  return (
    <div className="grid grid-cols-1 gap-4">
      <Card
        title={`#${data.id} · ${data.kind === "walk_forward" ? "Walk-forward (out-of-sample)" : "Single run"} · ${data.start} → ${data.end}`}
        action={
          <Button variant="primary" disabled={apply.isPending} onClick={() => apply.mutate()}>
            {apply.isSuccess ? "Applied to live signals" : "Use these settings"}
          </Button>
        }
      >
        <Verdict m={m} />
        <p className="mt-1 font-mono text-xs text-muted">{paramsLine(data.params)}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          <Stat label="CAGR" value={pct(m.cagr_pct)} tone={toneFor(m.cagr_pct)} />
          <Stat label="NIFTY CAGR" value={pct(m.benchmark_cagr_pct)} tone="text-muted" />
          <Stat label="Max drawdown" value={pct(m.max_drawdown_pct)} tone="text-negative" />
          <Stat label="NIFTY drawdown" value={pct(m.benchmark_max_drawdown_pct)} tone="text-muted" />
          <Stat label="Sharpe" value={m.sharpe.toFixed(2)} />
          <Stat label="Trades" value={String(m.trades)} />
          <Stat label="Win rate" value={pct(m.win_rate_pct)} />
          <Stat label="Profit factor" value={m.profit_factor?.toFixed(2) ?? "—"} />
          <Stat label="Avg R" value={m.avg_r.toFixed(2)} />
          <Stat label="Avg hold" value={`${m.avg_hold_days}d`} />
          <Stat label="Total return" value={pct(m.total_return_pct)} tone={toneFor(m.total_return_pct)} />
          <Stat
            label="Exits S/T/Tr/Sig"
            value={`${m.exit_reasons.stop}/${m.exit_reasons.target}/${m.exit_reasons.time}/${m.exit_reasons.signal}`}
          />
        </div>
        <div className="mt-4">
          <EquityChart points={data.equity} />
          <p className="mt-1 text-xs text-muted">Both lines are indexed to 100 at the start. The dashed line is NIFTY 50.</p>
        </div>
      </Card>

      {m.folds ? (
        <Card title={`Walk-forward folds · ${m.combos_tested} parameter combinations tested per fold`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="py-2 font-normal">Test window (unseen)</th>
                  <th className="py-2 font-normal">Chosen on prior 24 months</th>
                  <th className="py-2 text-right font-normal">Train Sharpe</th>
                  <th className="py-2 text-right font-normal">Test CAGR</th>
                  <th className="py-2 text-right font-normal">NIFTY</th>
                  <th className="py-2 text-right font-normal">Test DD</th>
                  <th className="py-2 text-right font-normal">Trades</th>
                </tr>
              </thead>
              <tbody>
                {m.folds.map((f) => (
                  <tr key={f.test_start} className="border-t border-line">
                    <td className="py-2 font-mono text-xs">
                      {f.test_start} → {f.test_end}
                    </td>
                    <td className="py-2 font-mono text-xs text-muted">
                      {entryRule(f.params)} · {f.params.stop_atr}/{f.params.target_atr} ATR · {f.params.max_hold_days}d
                    </td>
                    <td className="py-2 text-right font-mono text-xs">{f.train_metrics.sharpe?.toFixed(2)}</td>
                    <td className={`py-2 text-right font-mono text-xs ${toneFor(f.test_metrics.cagr_pct)}`}>{pct(f.test_metrics.cagr_pct)}</td>
                    <td className="py-2 text-right font-mono text-xs text-muted">{pct(f.test_metrics.benchmark_cagr_pct)}</td>
                    <td className="py-2 text-right font-mono text-xs text-negative">{pct(f.test_metrics.max_drawdown_pct)}</td>
                    <td className="py-2 text-right font-mono text-xs">{f.test_metrics.trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">
            Train Sharpe much higher than test results means the parameters are being fitted to the past. Treat in-sample results as optimistic.
          </p>
        </Card>
      ) : null}

      <Card title={`Trades · latest ${data.trades.length}`}>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr>
                <th className="py-2 font-normal">Stock</th>
                <th className="py-2 font-normal">Entry</th>
                <th className="py-2 font-normal">Exit</th>
                <th className="py-2 text-right font-normal">Qty</th>
                <th className="py-2 text-right font-normal">P&amp;L</th>
                <th className="py-2 pl-4 font-normal">Reason</th>
              </tr>
            </thead>
            <tbody>
              {data.trades.map((t) => (
                <tr key={`${t.symbol}-${t.entry_date}`} className="border-t border-line">
                  <td className="py-1.5 font-medium">{t.symbol}</td>
                  <td className="py-1.5 font-mono text-xs">
                    {t.entry_date} @ {formatPrice(t.entry_price)}
                  </td>
                  <td className="py-1.5 font-mono text-xs">
                    {t.exit_date} @ {formatPrice(t.exit_price)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{t.qty}</td>
                  <td className={`py-1.5 text-right tabular-nums ${toneFor(t.pnl)}`}>{formatPrice(t.pnl)}</td>
                  <td className="py-1.5 pl-4 text-xs text-muted">{t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export function BacktestsView() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const { data: jobs } = useJobs();
  const running = jobs?.items.some((j) => j.status === "running" && j.job_name.startsWith("backtest_"));
  const runs = useQuery({
    queryKey: ["backtests"],
    queryFn: () => api<{ items: BacktestSummary[] }>("backtests"),
    refetchInterval: running ? 3000 : false,
  });
  const active = useQuery({ queryKey: ["strategy-params"], queryFn: () => api<ActiveParams>("strategy/params") });
  const trigger = useMutation({
    mutationFn: (mode: string) => api<JobRun>(`backtests/run?mode=${mode}`, { method: "POST" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });
  const reset = useMutation({
    mutationFn: () => api<ActiveParams>("strategy/params/reset", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["strategy-params"] }),
  });
  const current = selected ?? runs.data?.items[0]?.id ?? null;

  return (
    <div className="grid grid-cols-1 gap-4">
      <Card
        title="Live strategy settings"
        action={
          active.data?.source !== "defaults" ? (
            <Button onClick={() => reset.mutate()} disabled={reset.isPending}>
              Reset to defaults
            </Button>
          ) : null
        }
      >
        {active.data ? (
          <>
            <p className="font-mono text-xs">{paramsLine(active.data.active)}</p>
            <p className="mt-1 text-xs text-muted">Source: {active.data.source}. Signals use these settings the next time analysis runs.</p>
          </>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={running || trigger.isPending} onClick={() => trigger.mutate("single")}>
            Backtest current settings
          </Button>
          <Button variant="primary" disabled={running || trigger.isPending} onClick={() => trigger.mutate("walk_forward")}>
            {running ? "Running…" : "Walk-forward tune"}
          </Button>
        </div>
        {trigger.error ? <p className="mt-2 text-sm text-negative">{trigger.error.message}</p> : null}
        <p className="mt-3 text-xs text-muted">
          Caveats: the universe is today&apos;s NIFTY 500, so stocks that dropped out are missing, which flatters results. News sentiment is not
          in the backtest because past news isn&apos;t stored. Costs include STT, exchange and stamp charges, DP fees and 0.05% slippage.
        </p>
      </Card>

      {runs.data && runs.data.items.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {runs.data.items.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelected(r.id)}
              className={`rounded-md border px-3 py-1.5 text-left text-xs ${
                current === r.id ? "border-accent bg-surface-strong" : "border-line bg-surface text-muted"
              }`}
            >
              #{r.id} {r.kind === "walk_forward" ? "walk-forward" : "single"} ·{" "}
              <span className={toneFor(r.cagr_pct)}>{pct(r.cagr_pct)}</span> vs NIFTY {pct(r.benchmark_cagr_pct)}
            </button>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted">No backtests yet.</p>
      )}

      {current ? <Detail key={current} id={current} onApplied={() => queryClient.invalidateQueries({ queryKey: ["strategy-params"] })} /> : null}
    </div>
  );
}
