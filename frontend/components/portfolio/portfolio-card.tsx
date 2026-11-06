"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api";
import { formatPct, formatPrice, toneFor } from "@/lib/format";
import type { Portfolio } from "@/lib/types";

export function PortfolioCard() {
  const { data } = useQuery({ queryKey: ["portfolio"], queryFn: () => api<Portfolio>("portfolio"), refetchInterval: 60_000 });
  const pending = data?.orders.filter((o) => o.status === "pending").length ?? 0;
  return (
    <Link href="/portfolio" className="rounded-lg border border-line bg-surface p-4 hover:border-muted">
      <div className="flex items-center justify-between text-sm font-medium">
        Paper portfolio
        {data?.kill_switch ? <span className="font-mono text-[11px] text-negative">KILL SWITCH</span> : null}
      </div>
      {data ? (
        <p className="mt-2 font-mono text-xs text-muted">
          {formatPrice(data.equity)} <span className={toneFor(data.total_return_pct)}>{formatPct(data.total_return_pct)}</span> ·{" "}
          {data.positions.length} open · {pending} pending
        </p>
      ) : (
        <p className="mt-2 font-mono text-xs text-muted">Loading…</p>
      )}
    </Link>
  );
}
