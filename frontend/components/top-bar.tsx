"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { regimeTone } from "@/components/signals/badges";
import { api } from "@/lib/api";
import { formatInrCompact, formatSignedInr, toneFor } from "@/lib/format";
import type { AccountSummary } from "@/lib/types";

const time = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
const day = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });

function Item({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="flex flex-col leading-tight" title={title}>
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span className="font-mono text-[13px] tabular-nums">{children}</span>
    </div>
  );
}

function Group({ children, href, label }: { children: React.ReactNode; href?: string; label: string }) {
  const body = (
    <>
      <span className="hidden text-[10px] font-semibold uppercase tracking-wider text-muted lg:inline">{label}</span>
      {children}
    </>
  );
  const className = "flex shrink-0 items-center gap-4 border-l border-line pl-4 first:border-l-0 first:pl-0";
  return href ? (
    <Link href={href} className={`${className} hover:opacity-80`}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

function pct(value: number | null | undefined) {
  return value == null ? "" : ` (${value > 0 ? "+" : ""}${value.toFixed(2)}%)`;
}

function ModeBadge({ mode }: { mode: AccountSummary["mode"] }) {
  if (mode.kill_switch) {
    return <span className="rounded border border-negative/50 bg-negative/15 px-2 py-0.5 font-mono text-[11px] font-semibold text-negative">KILL SWITCH</span>;
  }
  if (mode.mode === "paper") {
    return <span className="rounded border border-line bg-surface-strong px-2 py-0.5 font-mono text-[11px] text-muted">PAPER</span>;
  }
  return mode.dry_run ? (
    <span className="rounded border border-accent/40 bg-accent/10 px-2 py-0.5 font-mono text-[11px] text-accent">APPROVE · DRY RUN</span>
  ) : (
    <span className="rounded border border-negative/50 bg-negative/15 px-2 py-0.5 font-mono text-[11px] font-semibold text-negative">LIVE</span>
  );
}

export function TopBar() {
  const { data, error } = useQuery({
    queryKey: ["account-summary"],
    queryFn: () => api<AccountSummary>("account/summary"),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-surface/95 backdrop-blur">
      <div className="flex items-center gap-4 overflow-x-auto px-4 py-2 md:px-8 [scrollbar-width:none]">
        {error ? <span className="text-xs text-negative">{error.message}</span> : null}
        {!data && !error ? <span className="h-8 text-xs text-muted">Loading account…</span> : null}
        {data ? (
          <>
            <Group label="Market">
              <Item label={day.format(new Date(data.now_ist))}>
                <span className="inline-flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${data.market.open ? "bg-positive" : "bg-muted"}`} />
                  {data.market.open ? "Open" : "Closed"} · {time.format(new Date(data.now_ist))}
                </span>
              </Item>
              <Item label="NIFTY 50" title={`India VIX ${data.regime.vix?.toFixed(2) ?? "—"}`}>
                {data.regime.nifty?.toLocaleString("en-IN", { maximumFractionDigits: 0 }) ?? "—"}{" "}
                <span className={`text-[11px] uppercase ${regimeTone(data.regime.name)}`}>{data.regime.name}</span>
              </Item>
            </Group>

            {data.kite.connected && !data.kite.error ? (
              <Group label="Zerodha" href="/approvals">
                <Item label="Zerodha cash" title={`Opening ${formatInrCompact(data.kite.opening_balance)} · used ${formatInrCompact(data.kite.used_margin)}`}>
                  {formatInrCompact(data.kite.available_cash)}
                </Item>
                <Item label="Zerodha today">
                  <span className={toneFor(data.kite.today_pnl ?? 0)}>
                    {formatSignedInr(data.kite.today_pnl)}
                    <span className="text-[11px]">{pct(data.kite.today_pnl_pct)}</span>
                  </span>
                </Item>
                <Item label={`Holdings · ${data.kite.holdings_count ?? 0}`} title={`Overall P&L ${formatSignedInr(data.kite.holdings_pnl)}`}>
                  {formatInrCompact(data.kite.holdings_value)}
                  {data.kite.holdings_count ? (
                    <span className={`ml-1 text-[11px] ${toneFor(data.kite.holdings_pnl ?? 0)}`}>{formatSignedInr(data.kite.holdings_pnl)}</span>
                  ) : null}
                </Item>
              </Group>
            ) : (
              <Group label="Zerodha" href="/settings">
                <Item label="Kite">
                  <span className="text-negative">{data.kite.error ? "Error · retry" : "Not connected · log in"}</span>
                </Item>
              </Group>
            )}

            <Group label="Paper" href="/portfolio">
              <Item label="Paper equity" title={`Cash ${formatInrCompact(data.paper.cash)} · total ${data.paper.total_return_pct.toFixed(2)}%`}>
                {formatInrCompact(data.paper.equity)}
              </Item>
              <Item label="Paper today">
                <span className={toneFor(data.paper.today_pnl)}>
                  {formatSignedInr(data.paper.today_pnl)}
                  <span className="text-[11px]">{pct(data.paper.today_pnl_pct)}</span>
                </span>
              </Item>
              <Item label="Open · pending">
                {data.paper.open_positions} · {data.paper.pending_orders}
              </Item>
            </Group>

            <div className="order-first flex shrink-0 items-center gap-2 lg:order-none lg:ml-auto lg:pl-4">
              <ModeBadge mode={data.mode} />
            </div>
          </>
        ) : null}
      </div>
    </header>
  );
}
