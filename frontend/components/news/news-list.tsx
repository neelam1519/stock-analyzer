"use client";

import Link from "next/link";

import { formatDateTime } from "@/lib/format";
import type { NewsItem, NewsTag } from "@/lib/types";

const SOURCE_LABEL: Record<string, string> = {
  nse: "NSE filing",
  et_markets: "ET Markets",
  et_stocks: "ET Stocks",
  business_standard: "Business Standard",
  livemint: "Mint",
  moneycontrol: "Moneycontrol",
  google_news: "Google News",
};

function sentimentTone(value?: number | null) {
  if (value == null) return "border-line text-muted";
  if (value >= 0.2) return "border-positive/40 bg-positive/10 text-positive";
  if (value <= -0.2) return "border-negative/40 bg-negative/10 text-negative";
  return "border-line text-foreground";
}

function TagChip({ tag }: { tag: NewsTag }) {
  const score = tag.sentiment == null ? "" : ` ${tag.sentiment > 0 ? "+" : ""}${tag.sentiment.toFixed(1)}`;
  return (
    <Link
      href={`/stocks/${encodeURIComponent(tag.symbol)}`}
      title={tag.rationale ?? `Matched by ${tag.match_type}`}
      className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${sentimentTone(tag.sentiment)}`}
    >
      {tag.symbol}
      {score}
    </Link>
  );
}

export function NewsList({ items, emptyText }: { items: NewsItem[]; emptyText: string }) {
  if (items.length === 0) return <p className="py-6 text-center text-sm text-muted">{emptyText}</p>;
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <li key={item.id} className="py-3">
          <div className="mb-1 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            <span>{SOURCE_LABEL[item.source] ?? item.source}</span>
            <span>·</span>
            <span>{formatDateTime(item.published_at)}</span>
            {item.market_sentiment != null ? (
              <span className={`rounded border px-1.5 font-mono ${sentimentTone(item.market_sentiment)}`}>
                market {item.market_sentiment > 0 ? "+" : ""}
                {item.market_sentiment.toFixed(1)}
              </span>
            ) : null}
          </div>
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium hover:text-accent">
            {item.title}
          </a>
          {item.symbols.some((t) => t.rationale) ? (
            <p className="mt-1 text-xs text-muted">{item.symbols.find((t) => t.rationale)?.rationale}</p>
          ) : null}
          {item.symbols.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {item.symbols.slice(0, 8).map((tag) => (
                <TagChip key={tag.symbol} tag={tag} />
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
