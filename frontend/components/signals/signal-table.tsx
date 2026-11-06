"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Fragment, useState } from "react";

import { ActionBadge, ScoreBar, VerdictBadge } from "@/components/signals/badges";
import { api } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import type { SignalItem, SignalList } from "@/lib/types";

const TABS: SignalItem["action"][] = ["BUY", "HOLD", "SELL"];

export function SignalTable({ limit = 150, compact = false }: { limit?: number; compact?: boolean }) {
  const [action, setAction] = useState<SignalItem["action"]>("BUY");
  const [open, setOpen] = useState<string | null>(null);
  const { data, isPending, error } = useQuery({
    queryKey: ["signals", action, limit],
    queryFn: () => api<SignalList>(`signals?action=${action}&limit=${limit}`),
  });

  if (error) return <p className="text-sm text-negative">{error.message}</p>;

  return (
    <section className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        {compact ? (
          <h2 className="text-sm font-medium">Top BUY candidates</h2>
        ) : (
          <div className="flex gap-1 rounded-md border border-line p-0.5">
            {TABS.map((tab) => (
              <button
                key={tab}
                onClick={() => setAction(tab)}
                className={`rounded px-2.5 py-1 text-xs ${action === tab ? "bg-surface-strong text-foreground" : "text-muted"}`}
              >
                {tab} <span className="text-muted">{data?.counts[tab] ?? ""}</span>
              </button>
            ))}
          </div>
        )}
        <span className="ml-auto text-xs text-muted">{data?.as_of ? `Signals for ${data.as_of}` : ""}</span>
      </div>
      {isPending ? <p className="p-4 text-sm text-muted">Loading…</p> : null}
      {data && data.items.length === 0 ? (
        <p className="p-6 text-sm text-muted">No signals yet. Run “Run analysis” on the Settings page.</p>
      ) : null}
      {data && data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="px-4 py-2 font-normal">Stock</th>
                <th className="px-4 py-2 font-normal">Signal</th>
                <th className="px-4 py-2 font-normal">Score</th>
                <th className="px-4 py-2 text-right font-normal">Tech / News</th>
                <th className="px-4 py-2 text-right font-normal">Entry</th>
                <th className="px-4 py-2 text-right font-normal">Stop</th>
                <th className="px-4 py-2 text-right font-normal">Target</th>
                <th className="px-4 py-2 font-normal">Research</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <Fragment key={item.symbol}>
                  <tr
                    className="cursor-pointer border-t border-line hover:bg-surface-strong/40"
                    onClick={() => setOpen(open === item.symbol ? null : item.symbol)}
                  >
                    <td className="px-4 py-2">
                      <Link
                        href={`/stocks/${encodeURIComponent(item.symbol)}`}
                        onClick={(e) => e.stopPropagation()}
                        className="font-medium hover:text-accent"
                      >
                        {item.symbol}
                      </Link>
                      <div className="max-w-[14rem] truncate text-xs text-muted">{item.sector ?? item.name}</div>
                    </td>
                    <td className="px-4 py-2">
                      <ActionBadge action={item.action} />
                    </td>
                    <td className="px-4 py-2">
                      <ScoreBar score={item.score} />
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs tabular-nums text-muted">
                      {item.technical_score?.toFixed(0)} / {item.news_score ? (item.news_score > 0 ? "+" : "") + item.news_score.toFixed(1) : "0"}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatPrice(item.entry)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-negative">{formatPrice(item.stop)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-positive">{formatPrice(item.target)}</td>
                    <td className="px-4 py-2">
                      <VerdictBadge verdict={item.research_verdict} />
                    </td>
                  </tr>
                  {open === item.symbol ? (
                    <tr className="bg-surface-strong/30">
                      <td colSpan={8} className="px-4 py-2 text-xs text-muted">
                        {item.rationale}
                        {item.reward_risk ? ` · reward/risk ${item.reward_risk}` : ""}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
