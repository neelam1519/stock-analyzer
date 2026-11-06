"use client";

import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/card";
import { NewsList } from "@/components/news/news-list";
import { api } from "@/lib/api";
import type { NewsItem } from "@/lib/types";

export function StockNews({ symbol }: { symbol: string }) {
  const { data, isPending } = useQuery({
    queryKey: ["news", "symbol", symbol],
    queryFn: () => api<{ items: NewsItem[] }>(`news?symbol=${encodeURIComponent(symbol)}&days=30&limit=50`),
  });
  const scores = (data?.items ?? [])
    .map((item) => item.symbols.find((t) => t.symbol === symbol)?.sentiment)
    .filter((v): v is number => v != null);
  const average = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;

  return (
    <Card
      title="News · last 30 days"
      action={
        average != null ? (
          <span className={`font-mono text-xs ${average >= 0.2 ? "text-positive" : average <= -0.2 ? "text-negative" : "text-muted"}`}>
            avg sentiment {average > 0 ? "+" : ""}
            {average.toFixed(2)} · {scores.length} scored
          </span>
        ) : null
      }
    >
      {isPending ? <p className="text-sm text-muted">Loading…</p> : null}
      {data ? <NewsList items={data.items} emptyText="No news tagged to this stock yet." /> : null}
    </Card>
  );
}
