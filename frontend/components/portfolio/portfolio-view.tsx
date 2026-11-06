"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import { formatDateTime, formatPct, formatPrice, toneFor } from "@/lib/format";
import type { Portfolio, PortfolioHistory } from "@/lib/types";

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 font-mono text-lg tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function StopTargetBar({ stop, entry, price, target }: { stop: number | null; entry: number; price: number; target: number | null }) {
  if (stop == null || target == null || target <= stop) return null;
  const at = (v: number) => `${Math.max(0, Math.min(100, ((v - stop) / (target - stop)) * 100))}%`;
  return (
    <div className="relative mt-1 h-1.5 w-28 rounded bg-surface-strong" title={`stop ${stop} · entry ${entry} · target ${target}`}>
      <div className="absolute top-0 h-full w-px bg-muted" style={{ left: at(entry) }} />
      <div className={`absolute -top-0.5 h-2.5 w-1.5 rounded-sm ${price >= entry ? "bg-positive" : "bg-negative"}`} style={{ left: at(price) }} />
    </div>
  );
}

export function PortfolioView() {
  const queryClient = useQueryClient();
  const portfolio = useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api<Portfolio>("portfolio"),
    refetchInterval: 60_000,
  });
  const history = useQuery({ queryKey: ["portfolio", "history"], queryFn: () => api<PortfolioHistory>("portfolio/history") });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  const closePosition = useMutation({
    mutationFn: (id: number) => api(`portfolio/positions/${id}/close`, { method: "POST" }),
    onSuccess: refresh,
  });
  const cancelOrder = useMutation({ mutationFn: (id: number) => api(`portfolio/orders/${id}/cancel`, { method: "POST" }), onSuccess: refresh });
  const monitor = useMutation({ mutationFn: () => api<{ summary: string }>("paper/monitor", { method: "POST" }), onSuccess: refresh });

  const p = portfolio.data;
  if (portfolio.error) return <p className="text-sm text-negative">{portfolio.error.message}</p>;
  if (!p) return <div className="h-40 animate-pulse rounded-lg bg-surface" />;
  const pending = p.orders.filter((o) => o.status === "pending");
  const decided = p.orders.filter((o) => o.status !== "pending");

  return (
    <div className="grid grid-cols-1 gap-4">
      {p.kill_switch ? (
        <p className="rounded-lg border border-negative/40 bg-negative/10 px-4 py-2 text-sm text-negative">
          Kill switch is ON. No new entries are planned. Turn it off in Settings.
        </p>
      ) : null}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Equity" value={formatPrice(p.equity)} />
        <Stat label="Return" value={formatPct(p.total_return_pct)} tone={toneFor(p.total_return_pct)} />
        <Stat label="Cash" value={formatPrice(p.cash)} />
        <Stat label="Invested" value={formatPrice(p.invested)} />
        <Stat label="Unrealized" value={formatPrice(p.unrealized_pnl)} tone={toneFor(p.unrealized_pnl)} />
        <Stat label="Realized" value={formatPrice(p.realized_pnl)} tone={toneFor(p.realized_pnl)} />
      </div>

      <Card
        title={`Open positions · ${p.positions.length}`}
        action={
          <Button onClick={() => monitor.mutate()} disabled={monitor.isPending || p.positions.length === 0}>
            {monitor.isPending ? "Checking…" : "Check prices now"}
          </Button>
        }
      >
        {monitor.error ? <p className="mb-2 text-sm text-negative">{monitor.error.message}</p> : null}
        {p.positions.length === 0 ? (
          <p className="text-sm text-muted">No open positions. Pending orders fill at the next session&apos;s open ({p.next_session}).</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="px-2 py-2 font-normal">Stock</th>
                  <th className="px-2 py-2 text-right font-normal">Qty</th>
                  <th className="px-2 py-2 text-right font-normal">Entry</th>
                  <th className="px-2 py-2 text-right font-normal">Price</th>
                  <th className="px-2 py-2 pl-4 font-normal">Stop · target</th>
                  <th className="px-2 py-2 text-right font-normal">P&amp;L</th>
                  <th className="px-2 py-2 text-right font-normal">R</th>
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody>
                {p.positions.map((pos) => (
                  <tr key={pos.id} className="border-t border-line">
                    <td className="px-2 py-2">
                      <Link href={`/stocks/${encodeURIComponent(pos.symbol)}`} className="font-medium hover:text-accent">
                        {pos.symbol}
                      </Link>
                      <div className="text-xs text-muted">since {formatDateTime(pos.opened_at)}</div>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{pos.qty}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{formatPrice(pos.entry)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">
                      {formatPrice(pos.price)}
                      <div className="text-[11px] text-muted">{formatDateTime(pos.price_at)}</div>
                    </td>
                    <td className="px-2 py-2 pl-4 font-mono text-xs">
                      <span className="text-negative">{formatPrice(pos.stop)}</span> · <span className="text-positive">{formatPrice(pos.target)}</span>
                      <StopTargetBar stop={pos.stop} entry={pos.entry} price={pos.price} target={pos.target} />
                    </td>
                    <td className={`py-2 text-right tabular-nums ${toneFor(pos.pnl)}`}>
                      {formatPrice(pos.pnl)}
                      <div className="text-[11px]">{formatPct(pos.pnl_pct)}</div>
                    </td>
                    <td className={`py-2 text-right font-mono text-xs ${toneFor(pos.r_multiple)}`}>{pos.r_multiple?.toFixed(2) ?? "—"}</td>
                    <td className="px-2 py-2 text-right">
                      <Button onClick={() => closePosition.mutate(pos.id)} disabled={closePosition.isPending}>
                        Close
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Orders for ${p.next_session} open · ${pending.length} pending`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="px-2 py-2 font-normal">Stock</th>
                <th className="px-2 py-2 font-normal">Side</th>
                <th className="px-2 py-2 font-normal">Status</th>
                <th className="px-2 py-2 text-right font-normal">Qty</th>
                <th className="px-2 py-2 text-right font-normal">Ref · stop · target</th>
                <th className="px-2 py-2 pl-4 font-normal">Why</th>
                <th className="px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {[...pending, ...decided].map((o) => (
                <tr key={o.id} className="border-t border-line align-top">
                  <td className="px-2 py-2 font-medium">{o.symbol}</td>
                  <td className={`py-2 font-mono text-xs ${o.side === "BUY" ? "text-positive" : "text-negative"}`}>{o.side}</td>
                  <td
                    className={`py-2 text-xs ${
                      o.status === "pending" ? "text-accent" : o.status === "filled" ? "text-positive" : "text-muted"
                    }`}
                  >
                    {o.status}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{o.qty || "—"}</td>
                  <td className="px-2 py-2 text-right font-mono text-xs">
                    {formatPrice(o.filled_price ?? o.reference)} · {formatPrice(o.stop)} · {formatPrice(o.target)}
                  </td>
                  <td className="max-w-xs py-2 pl-4 text-xs text-muted">{o.reason}</td>
                  <td className="px-2 py-2 text-right">
                    {o.status === "pending" ? (
                      <Button onClick={() => cancelOrder.mutate(o.id)} disabled={cancelOrder.isPending}>
                        Cancel
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {p.orders.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-3 text-sm text-muted">
                    No orders. They are planned automatically at 15:50 on trading days from the day&apos;s BUY signals.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Closed trades"
        action={
          history.data?.stats.trades ? (
            <span className="font-mono text-xs text-muted">
              {history.data.stats.trades} trades · win {history.data.stats.win_rate_pct}% ·{" "}
              <span className={toneFor(history.data.stats.realized_pnl)}>{formatPrice(history.data.stats.realized_pnl)}</span>
            </span>
          ) : null
        }
      >
        {history.data && history.data.closed.length > 0 ? (
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="sticky top-0 bg-surface text-xs text-muted">
                <tr>
                  <th className="px-2 py-2 font-normal">Stock</th>
                  <th className="px-2 py-2 font-normal">Held</th>
                  <th className="px-2 py-2 text-right font-normal">Entry → exit</th>
                  <th className="px-2 py-2 text-right font-normal">P&amp;L</th>
                  <th className="px-2 py-2 text-right font-normal">R</th>
                  <th className="px-2 py-2 pl-4 font-normal">Exit</th>
                </tr>
              </thead>
              <tbody>
                {history.data.closed.map((t) => (
                  <tr key={t.id} className="border-t border-line">
                    <td className="px-2 py-1.5 font-medium">{t.symbol}</td>
                    <td className="px-2 py-1.5 text-xs text-muted">
                      {formatDateTime(t.opened_at)} → {formatDateTime(t.closed_at)}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-xs">
                      {formatPrice(t.entry)} → {formatPrice(t.exit_price)}
                    </td>
                    <td className={`py-1.5 text-right tabular-nums ${toneFor(t.pnl)}`}>{formatPrice(t.pnl)}</td>
                    <td className={`py-1.5 text-right font-mono text-xs ${toneFor(t.r_multiple)}`}>{t.r_multiple?.toFixed(2) ?? "—"}</td>
                    <td className="px-2 py-1.5 pl-4 text-xs text-muted">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-muted">No closed trades yet.</p>
        )}
      </Card>
    </div>
  );
}
