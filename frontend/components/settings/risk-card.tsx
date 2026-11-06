"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "@/components/card";
import { api } from "@/lib/api";
import type { RiskLimits } from "@/lib/types";

const FIELDS: { key: keyof RiskLimits; label: string; step: string }[] = [
  { key: "capital", label: "Paper capital (₹)", step: "10000" },
  { key: "risk_per_trade_pct", label: "Risk per trade %", step: "0.1" },
  { key: "max_position_pct", label: "Max position %", step: "1" },
  { key: "max_open_positions", label: "Max open positions", step: "1" },
  { key: "daily_loss_limit_pct", label: "Daily loss limit %", step: "0.5" },
  { key: "weekly_loss_limit_pct", label: "Weekly loss limit %", step: "0.5" },
  { key: "max_sector_pct", label: "Max sector exposure %", step: "5" },
];

function RiskForm({ limits }: { limits: RiskLimits }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(FIELDS.map((f) => [f.key, String(limits[f.key])])),
  );
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["risk"] });
    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  };
  const save = useMutation({
    mutationFn: () =>
      api<RiskLimits>("risk/limits", {
        method: "PUT",
        body: JSON.stringify(Object.fromEntries(FIELDS.map((f) => [f.key, Number(draft[f.key])]))),
      }),
    onSuccess: invalidate,
  });
  const kill = useMutation({
    mutationFn: (on: boolean) => api<RiskLimits>("risk/kill-switch", { method: "POST", body: JSON.stringify({ on }) }),
    onSuccess: invalidate,
  });

  return (
    <Card
      title="Risk limits"
      action={
        <Button
          variant={limits.kill_switch ? "primary" : "secondary"}
          className={limits.kill_switch ? "" : "text-negative"}
          disabled={kill.isPending}
          onClick={() => kill.mutate(!limits.kill_switch)}
        >
          {limits.kill_switch ? "Kill switch ON · turn off" : "Kill switch"}
        </Button>
      }
    >
      <form
        className="grid grid-cols-2 gap-3 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        {FIELDS.map((field) => (
          <label key={field.key} className="grid gap-1 text-xs text-muted">
            {field.label}
            <input
              type="number"
              step={field.step}
              value={draft[field.key]}
              onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}
              className="w-full min-w-0 rounded-md border border-line bg-background px-2 py-1.5 font-mono text-sm text-foreground outline-none focus:border-accent"
            />
          </label>
        ))}
        <div className="flex items-end">
          <Button variant="primary" type="submit" disabled={save.isPending}>
            {save.isSuccess ? "Saved" : "Save limits"}
          </Button>
        </div>
      </form>
      {save.error ? <p className="mt-2 text-sm text-negative">{save.error.message}</p> : null}
      <p className="mt-3 text-xs text-muted">
        The kill switch cancels pending BUY orders and blocks new entries. Existing positions keep their stops and targets.
      </p>
    </Card>
  );
}

export function RiskCard() {
  const { data } = useQuery({ queryKey: ["risk"], queryFn: () => api<RiskLimits>("risk/limits") });
  if (!data) return <div className="h-40 rounded-lg border border-line bg-surface" />;
  return <RiskForm key={data.updated_at ?? "initial"} limits={data} />;
}
