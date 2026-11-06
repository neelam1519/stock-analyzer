"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Card } from "@/components/card";
import { StockNews } from "@/components/news/stock-news";
import { StockAnalysisCards } from "@/components/signals/stock-analysis";
import { PriceChart } from "@/components/stocks/price-chart";
import { api } from "@/lib/api";
import { formatPct, formatPrice, toneFor } from "@/lib/format";
import type { Candle, LinePoint, StockDetail } from "@/lib/types";

const INTERVALS = [
  { value: "day", label: "Daily", limit: 750 },
  { value: "60m", label: "60 min", limit: 1200 },
] as const;

export function StockView({ symbol }: { symbol: string }) {
  const [interval, setInterval] = useState<(typeof INTERVALS)[number]>(INTERVALS[0]);
  const detail = useQuery({
    queryKey: ["stock", symbol],
    queryFn: () => api<StockDetail>(`stocks/${encodeURIComponent(symbol)}`),
  });
  const candles = useQuery({
    queryKey: ["candles", symbol, interval.value],
    queryFn: () =>
      api<{ candles: Candle[]; overlays: Record<string, LinePoint[]> }>(
        `stocks/${encodeURIComponent(symbol)}/candles?interval=${interval.value}&limit=${interval.limit}`,
      ),
  });

  if (detail.error) {
    return (
      <p className="text-sm text-negative">
        {detail.error.message}.{" "}
        <Link href="/stocks" className="underline">
          Back to stocks
        </Link>
      </p>
    );
  }

  const d = detail.data;
  return (
    <div className="grid grid-cols-1 gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href="/stocks" className="text-xs text-muted hover:text-foreground">
            ← Stocks
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{symbol}</h1>
          <p className="text-sm text-muted">
            {d?.name ?? "…"}
            {d?.sector ? ` · ${d.sector}` : ""}
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold tabular-nums">{formatPrice(d?.last_close ?? null)}</div>
          <div className={`text-sm tabular-nums ${toneFor(d?.change_pct ?? null)}`}>
            {formatPct(d?.change_pct ?? null)} · {d?.last_date ?? "—"}
          </div>
        </div>
      </header>

      <Card
        title="Price"
        action={
          <div className="flex gap-1 rounded-md border border-line p-0.5">
            {INTERVALS.map((option) => (
              <button
                key={option.value}
                onClick={() => setInterval(option)}
                className={`rounded px-2 py-1 text-xs ${
                  interval.value === option.value ? "bg-surface-strong text-foreground" : "text-muted"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        }
      >
        {candles.isPending ? (
          <div className="h-[420px] animate-pulse rounded bg-surface-strong/40" />
        ) : candles.data && candles.data.candles.length > 0 ? (
          <PriceChart candles={candles.data.candles} overlays={candles.data.overlays} intraday={interval.value === "60m"} />
        ) : (
          <p className="flex h-[200px] items-center justify-center text-sm text-muted">
            No {interval.label.toLowerCase()} candles stored yet. Run the candle download from Settings.
          </p>
        )}
      </Card>

      {d ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {(["day", "60m"] as const).map((key) => (
            <Card key={key} title={key === "day" ? "Daily candles stored" : "60-minute candles stored"}>
              <p className="font-mono text-sm">
                {d.candles[key].count.toLocaleString("en-IN")}{" "}
                <span className="text-muted">
                  {d.candles[key].first ? `${d.candles[key].first?.slice(0, 10)} → ${d.candles[key].last?.slice(0, 10)}` : ""}
                </span>
              </p>
            </Card>
          ))}
        </div>
      ) : null}

      <StockAnalysisCards symbol={symbol} />

      <StockNews symbol={symbol} />
    </div>
  );
}
