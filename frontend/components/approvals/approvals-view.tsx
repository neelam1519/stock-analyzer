"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button, Card } from "@/components/card";
import { VerdictBadge } from "@/components/signals/badges";
import { api } from "@/lib/api";
import { formatDateTime, formatPrice, toneFor } from "@/lib/format";
import type { Approval, ApprovalList, LiveOrderRecord, PaperPosition } from "@/lib/types";

function ModeBanner({ data }: { data: ApprovalList }) {
  const { mode, dry_run } = data.settings;
  if (mode !== "approve") {
    return (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-sm text-muted">
        Trading mode is <b className="text-foreground">paper</b>. No approval requests are created. Switch to approve mode in Settings when
        you are ready.
      </p>
    );
  }
  return (
    <p
      className={`rounded-lg border px-4 py-3 text-sm ${
        dry_run ? "border-accent/40 bg-accent/10 text-accent" : "border-negative/50 bg-negative/10 text-negative"
      }`}
    >
      {dry_run
        ? "DRY RUN: approving logs the exact Kite order but sends nothing. Turn dry run off in Settings to trade for real."
        : "LIVE: approving sends a real CNC order to your Zerodha account."}
      {!data.kite_connected ? " Kite is not connected, so price and funds checks are skipped." : ""}
    </p>
  );
}

function ConfirmDialog({ item, live, onCancel, onConfirm, busy }: { item: Approval; live: boolean; onCancel: () => void; onConfirm: () => void; busy: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md rounded-lg border border-line bg-surface p-5 shadow-xl">
        <h2 className="text-lg font-semibold">{live ? "Place a LIVE order?" : "Dry run this order?"}</h2>
        <dl className="mt-4 grid grid-cols-2 gap-y-2 font-mono text-sm">
          <dt className="text-muted">Order</dt>
          <dd className={item.side === "BUY" ? "text-positive" : "text-negative"}>
            {item.side} {item.qty} {item.symbol}
          </dd>
          <dt className="text-muted">Type</dt>
          <dd>CNC · LIMIT{item.kind === "exit" ? " (near market)" : ""}</dd>
          <dt className="text-muted">{item.kind === "exit" ? "Reference" : "Limit"}</dt>
          <dd>{formatPrice(item.limit_price)}</dd>
          <dt className="text-muted">Value</dt>
          <dd>{formatPrice(item.value)}</dd>
          {item.kind === "entry" ? (
            <>
              <dt className="text-muted">GTT stop / target</dt>
              <dd>
                <span className="text-negative">{formatPrice(item.stop)}</span> / <span className="text-positive">{formatPrice(item.target)}</span>
              </dd>
              <dt className="text-muted">Money at risk</dt>
              <dd>{formatPrice(item.risk_amount)}</dd>
            </>
          ) : null}
        </dl>
        <p className="mt-4 text-xs text-muted">
          {live
            ? "This sends a real order to Zerodha. After it fills, a GTT OCO stop-loss and target is placed automatically."
            : "Nothing is sent to Zerodha. The exact payload is saved so you can check it."}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm} disabled={busy} className={live ? "bg-negative" : ""}>
            {busy ? "Sending…" : live ? `Place live ${item.side}` : "Dry run"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function OrdersTable({ orders }: { orders: LiveOrderRecord[] }) {
  if (orders.length === 0) return <p className="text-sm text-muted">No live order activity yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="text-xs text-muted">
          <tr>
            <th className="px-2 py-2 font-normal">When</th>
            <th className="px-2 py-2 font-normal">Stock</th>
            <th className="px-2 py-2 font-normal">Kind</th>
            <th className="px-2 py-2 font-normal">Status</th>
            <th className="px-2 py-2 font-normal">Kite ids</th>
            <th className="px-2 py-2 font-normal">Payload / message</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-t border-line align-top">
              <td className="px-2 py-2 text-xs text-muted">{formatDateTime(o.created_at)}</td>
              <td className="px-2 py-2 font-medium">{o.symbol}</td>
              <td className="px-2 py-2 font-mono text-xs">{o.kind}</td>
              <td className={`px-2 py-2 text-xs ${o.status === "failed" ? "text-negative" : o.status === "dry_run" ? "text-accent" : ""}`}>
                {o.status}
              </td>
              <td className="px-2 py-2 font-mono text-[11px] text-muted">
                {o.kite_order_id ?? ""}
                {o.gtt_id ? ` gtt ${o.gtt_id}` : ""}
              </td>
              <td className="max-w-md px-2 py-2">
                <code className="block truncate text-[11px] text-muted" title={JSON.stringify(o.payload)}>
                  {JSON.stringify(o.payload)}
                </code>
                {o.status_message ? <div className="text-xs">{o.status_message}</div> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApprovalsView() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const approvals = useQuery({ queryKey: ["approvals"], queryFn: () => api<ApprovalList>("approvals?status=all&limit=60"), refetchInterval: 30_000 });
  const orders = useQuery({ queryKey: ["live-orders"], queryFn: () => api<{ items: LiveOrderRecord[] }>("live/orders?limit=50") });
  const positions = useQuery({ queryKey: ["live-positions"], queryFn: () => api<{ items: PaperPosition[] }>("live/positions") });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["approvals"] });
    queryClient.invalidateQueries({ queryKey: ["live-orders"] });
    queryClient.invalidateQueries({ queryKey: ["live-positions"] });
  };
  const approve = useMutation({
    mutationFn: (id: number) => api<Approval>(`approvals/${id}/approve`, { method: "POST" }),
    onSuccess: () => {
      setConfirming(null);
      setError(null);
      refresh();
    },
    onError: (e) => {
      setConfirming(null);
      setError(e.message);
      refresh();
    },
  });
  const reject = useMutation({ mutationFn: (id: number) => api(`approvals/${id}/reject`, { method: "POST" }), onSuccess: refresh });
  const sync = useMutation({ mutationFn: () => api<{ summary: string }>("live/sync", { method: "POST" }), onSuccess: refresh });

  const data = approvals.data;
  if (approvals.error) return <p className="text-sm text-negative">{approvals.error.message}</p>;
  if (!data) return <div className="h-40 animate-pulse rounded-lg bg-surface" />;
  const pending = data.items.filter((i) => i.status === "pending");
  const decided = data.items.filter((i) => i.status !== "pending");
  const live = data.settings.mode === "approve" && !data.settings.dry_run;
  const openPositions = (positions.data?.items ?? []).filter((p) => p.status === "open");

  return (
    <div className="grid grid-cols-1 gap-4">
      <ModeBanner data={data} />
      {error ? <p className="rounded-lg border border-negative/40 bg-negative/10 px-4 py-2 text-sm text-negative">{error}</p> : null}

      <Card title={`Waiting for you · ${pending.length}`}>
        {pending.length === 0 ? (
          <p className="text-sm text-muted">
            Nothing to approve. Requests are created at 15:50 on trading days from the paper plan and expire at 09:30 the next session.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {pending.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`font-mono text-xs font-semibold ${item.side === "BUY" ? "text-positive" : "text-negative"}`}>{item.side}</span>
                    <Link href={`/stocks/${encodeURIComponent(item.symbol)}`} className="font-medium hover:text-accent">
                      {item.symbol}
                    </Link>
                    <span className="text-xs text-muted">{item.sector}</span>
                    <VerdictBadge verdict={item.research_verdict} />
                  </div>
                  <div className="mt-1 font-mono text-xs text-muted">
                    {item.qty} × {formatPrice(item.limit_price)} = {formatPrice(item.value)}
                    {item.kind === "entry" ? ` · stop ${formatPrice(item.stop)} · target ${formatPrice(item.target)} · risk ${formatPrice(item.risk_amount)}` : ""}
                  </div>
                  <div className="text-xs text-muted">
                    {item.reason} · expires {formatDateTime(item.expires_at)}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button onClick={() => reject.mutate(item.id)} disabled={reject.isPending}>
                    Reject
                  </Button>
                  <Button variant="primary" onClick={() => setConfirming(item)} disabled={data.settings.mode !== "approve"}>
                    {live ? "Approve" : "Approve (dry run)"}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title={`Live positions · ${openPositions.length} open`}
        action={
          <Button onClick={() => sync.mutate()} disabled={sync.isPending || !data.kite_connected}>
            {sync.isPending ? "Syncing…" : "Sync with Kite"}
          </Button>
        }
      >
        {sync.error ? <p className="mb-2 text-sm text-negative">{sync.error.message}</p> : null}
        {(positions.data?.items ?? []).length === 0 ? (
          <p className="text-sm text-muted">No live positions.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="px-2 py-2 font-normal">Stock</th>
                  <th className="px-2 py-2 text-right font-normal">Qty</th>
                  <th className="px-2 py-2 text-right font-normal">Entry</th>
                  <th className="px-2 py-2 text-right font-normal">Price / exit</th>
                  <th className="px-2 py-2 text-right font-normal">Stop · target</th>
                  <th className="px-2 py-2 text-right font-normal">P&amp;L</th>
                  <th className="px-2 py-2 font-normal">Status</th>
                </tr>
              </thead>
              <tbody>
                {positions.data?.items.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="px-2 py-2 font-medium">{p.symbol}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{p.qty}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{formatPrice(p.entry)}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{formatPrice(p.exit_price ?? p.price)}</td>
                    <td className="px-2 py-2 text-right font-mono text-xs">
                      {formatPrice(p.stop)} · {formatPrice(p.target)}
                    </td>
                    <td className={`px-2 py-2 text-right tabular-nums ${toneFor(p.pnl)}`}>{formatPrice(p.pnl)}</td>
                    <td className="px-2 py-2 text-xs text-muted">{p.status === "open" ? "open · GTT" : p.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Order log (every Kite request is recorded)">
        <OrdersTable orders={orders.data?.items ?? []} />
      </Card>

      {decided.length > 0 ? (
        <Card title="Past approvals">
          <ul className="grid gap-1 text-xs">
            {decided.slice(0, 30).map((item) => (
              <li key={item.id} className="flex flex-wrap gap-2 font-mono text-muted">
                <span className="text-foreground">{item.symbol}</span>
                <span>
                  {item.side} {item.qty} @ {formatPrice(item.limit_price)}
                </span>
                <span>{item.status}</span>
                <span>{formatDateTime(item.decided_at ?? item.expires_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {confirming ? (
        <ConfirmDialog
          item={confirming}
          live={live}
          busy={approve.isPending}
          onCancel={() => setConfirming(null)}
          onConfirm={() => approve.mutate(confirming.id)}
        />
      ) : null}
    </div>
  );
}
