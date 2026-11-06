"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import type { LiveSettings } from "@/lib/types";

function Form({ current }: { current: LiveSettings }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(current);
  const [confirm, setConfirm] = useState("");
  const goingLive = current.dry_run && !draft.dry_run;
  const save = useMutation({
    mutationFn: () => api<LiveSettings>("trading/settings", { method: "PUT", body: JSON.stringify({ ...draft, confirm }) }),
    onSuccess: () => {
      setConfirm("");
      queryClient.invalidateQueries({ queryKey: ["trading-settings"] });
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  const field = (key: keyof LiveSettings, label: string, step: string) => (
    <label className="grid gap-1 text-xs text-muted">
      {label}
      <input
        type="number"
        step={step}
        value={String(draft[key])}
        onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
        className="w-full min-w-0 rounded-md border border-line bg-background px-2 py-1.5 font-mono text-sm text-foreground outline-none focus:border-accent"
      />
    </label>
  );

  return (
    <Card title="Trading mode">
      <div className="flex flex-wrap gap-2">
        {(["paper", "approve"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => setDraft({ ...draft, mode })}
            className={`rounded-md border px-3 py-1.5 text-sm ${draft.mode === mode ? "border-accent bg-surface-strong" : "border-line text-muted"}`}
          >
            {mode === "paper" ? "Paper only" : "Approve real orders"}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-sm">
          <input type="checkbox" checked={draft.dry_run} onChange={(e) => setDraft({ ...draft, dry_run: e.target.checked })} />
          Dry run (send nothing to Kite)
        </label>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {field("live_capital", "Live capital to deploy (₹)", "5000")}
        {field("max_order_value", "Max value per order (₹)", "1000")}
        {field("entry_buffer_pct", "Limit above signal %", "0.1")}
        {field("max_price_drift_pct", "Refuse if price moved %", "0.5")}
      </div>
      {goingLive ? (
        <label className="mt-3 grid gap-1 text-xs text-negative">
          Turning dry run off lets approvals send real orders. Type LIVE to confirm.
          <input
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className="w-40 rounded-md border border-negative/50 bg-background px-2 py-1.5 font-mono text-sm text-foreground outline-none"
          />
        </label>
      ) : null}
      <div className="mt-3 flex items-center gap-3">
        <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending || (goingLive && confirm !== "LIVE")}>
          Save trading mode
        </Button>
        <span className="text-xs text-muted">
          Live quantities scale the paper plan by live capital ÷ paper capital and are capped per order.
        </span>
      </div>
      {save.error ? <p className="mt-2 text-sm text-negative">{save.error.message}</p> : null}
    </Card>
  );
}

export function TradingModeCard() {
  const { data } = useQuery({ queryKey: ["trading-settings"], queryFn: () => api<LiveSettings>("trading/settings") });
  if (!data) return <div className="h-40 rounded-lg border border-line bg-surface" />;
  return <Form key={JSON.stringify(data)} current={data} />;
}
