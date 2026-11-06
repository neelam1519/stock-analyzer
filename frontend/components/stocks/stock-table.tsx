"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { formatPct, formatPrice, toneFor } from "@/lib/format";
import type { InstrumentSummary } from "@/lib/types";

type SortKey = "symbol" | "sector" | "change_pct";

export function StockTable() {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("symbol");
  const deferred = useDeferredValue(query.trim().toLowerCase());
  const { data, isPending, error } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api<{ items: InstrumentSummary[] }>("instruments"),
  });

  const rows = useMemo(() => {
    const items = (data?.items ?? []).filter(
      (item) =>
        !deferred ||
        item.symbol.toLowerCase().includes(deferred) ||
        item.name?.toLowerCase().includes(deferred) ||
        item.sector?.toLowerCase().includes(deferred),
    );
    return [...items].sort((a, b) =>
      sort === "change_pct"
        ? (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity)
        : (a[sort] ?? "").localeCompare(b[sort] ?? ""),
    );
  }, [data, deferred, sort]);

  if (error) return <p className="text-sm text-negative">{error.message}</p>;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search symbol, company or sector"
          className="w-full max-w-sm rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <span className="text-xs text-muted">{isPending ? "Loading…" : `${rows.length} instruments`}</span>
      </div>
      {!isPending && data?.items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-6 text-sm text-muted">
          No instruments yet. Log in with Kite on the Settings page and run “Sync instruments + NIFTY 500”.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                {(
                  [
                    ["symbol", "Symbol"],
                    ["sector", "Sector"],
                  ] as const
                ).map(([key, label]) => (
                  <th key={key} className="px-4 py-2 font-normal">
                    <button onClick={() => setSort(key)} className={sort === key ? "text-foreground" : ""}>
                      {label}
                    </button>
                  </th>
                ))}
                <th className="px-4 py-2 text-right font-normal">Last close</th>
                <th className="px-4 py-2 text-right font-normal">
                  <button onClick={() => setSort("change_pct")} className={sort === "change_pct" ? "text-foreground" : ""}>
                    Change
                  </button>
                </th>
                <th className="px-4 py-2 text-right font-normal">As of</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.id} className="border-t border-line hover:bg-surface-strong/50">
                  <td className="px-4 py-2">
                    <Link href={`/stocks/${encodeURIComponent(item.symbol)}`} className="font-medium hover:text-accent">
                      {item.symbol}
                    </Link>
                    <div className="max-w-[16rem] truncate text-xs text-muted">{item.name}</div>
                  </td>
                  <td className="px-4 py-2 text-muted">{item.sector ?? (item.segment === "INDICES" ? "Index" : "—")}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatPrice(item.last_close)}</td>
                  <td className={`px-4 py-2 text-right tabular-nums ${toneFor(item.change_pct)}`}>
                    {formatPct(item.change_pct)}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-muted">{item.last_date ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
