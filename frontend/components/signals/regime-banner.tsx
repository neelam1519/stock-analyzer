"use client";

import { useQuery } from "@tanstack/react-query";

import { regimeTone } from "@/components/signals/badges";
import { api } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import type { Regime } from "@/lib/types";

export function RegimeBanner() {
  const { data } = useQuery({ queryKey: ["regime"], queryFn: () => api<Regime>("market/regime") });
  if (!data) return <div className="h-[74px] rounded-lg border border-line bg-surface" />;
  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-xs text-muted">Market regime</span>
        <span className={`font-mono text-sm font-semibold uppercase ${regimeTone(data.name)}`}>{data.name}</span>
        <span className="font-mono text-xs text-muted">
          NIFTY {formatPrice(data.nifty_close)} · EMA50 {formatPrice(data.nifty_ema50)} · EMA200 {formatPrice(data.nifty_ema200)} · RSI{" "}
          {data.nifty_rsi?.toFixed(0) ?? "—"} · VIX {data.vix?.toFixed(1) ?? "—"}
        </span>
        <span className="ml-auto text-xs text-muted">as of {data.as_of ?? "—"}</span>
      </div>
      <p className="mt-1 text-sm text-muted">{data.summary}</p>
    </section>
  );
}
