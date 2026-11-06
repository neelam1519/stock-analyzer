"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { NewsList } from "@/components/news/news-list";
import { api } from "@/lib/api";
import type { NewsItem } from "@/lib/types";

const RANGES = [1, 3, 7] as const;

export function NewsFeed() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(3);
  const [taggedOnly, setTaggedOnly] = useState(true);
  const { data, isPending, error } = useQuery({
    queryKey: ["news", days, taggedOnly],
    queryFn: () => api<{ items: NewsItem[] }>(`news?days=${days}&tagged_only=${taggedOnly}&limit=200`),
  });

  return (
    <section className="rounded-lg border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-3 border-b border-line pb-3">
        <div className="flex gap-1 rounded-md border border-line p-0.5">
          {RANGES.map((range) => (
            <button
              key={range}
              onClick={() => setDays(range)}
              className={`rounded px-2 py-1 text-xs ${days === range ? "bg-surface-strong text-foreground" : "text-muted"}`}
            >
              {range}d
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={taggedOnly} onChange={(e) => setTaggedOnly(e.target.checked)} />
          Only stock-tagged
        </label>
        <span className="ml-auto text-xs text-muted">{data ? `${data.items.length} articles` : ""}</span>
      </div>
      {isPending ? <p className="py-6 text-sm text-muted">Loading…</p> : null}
      {error ? <p className="py-6 text-sm text-negative">{error.message}</p> : null}
      {data ? <NewsList items={data.items} emptyText="No news yet. Run “Collect news” on the Settings page." /> : null}
    </section>
  );
}
