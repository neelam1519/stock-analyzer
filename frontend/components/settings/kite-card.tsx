"use client";

import { useSearchParams } from "next/navigation";

import { Card } from "@/components/card";
import { formatDateTime } from "@/lib/format";
import { useKiteStatus } from "@/lib/queries";

export function KiteCard() {
  const params = useSearchParams();
  const { data, isPending, error } = useKiteStatus();
  const result = params.get("kite");

  return (
    <Card title="Zerodha Kite">
      {result === "connected" ? (
        <p className="mb-3 rounded-md bg-positive/10 px-3 py-2 text-sm text-positive">Connected as {params.get("user")}.</p>
      ) : null}
      {result === "error" ? (
        <p className="mb-3 rounded-md bg-negative/10 px-3 py-2 text-sm text-negative">{params.get("reason") ?? "Login failed."}</p>
      ) : null}
      {isPending ? <p className="text-sm text-muted">Checking session…</p> : null}
      {error ? <p className="text-sm text-negative">{error.message}</p> : null}
      {data ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm">
            {!data.configured ? (
              <span className="text-negative">Add KITE_API_KEY and KITE_API_SECRET to .env</span>
            ) : data.connected ? (
              <span>
                <span className="text-positive">● Connected</span> · {data.user_id} · expires {formatDateTime(data.expires_at)}
              </span>
            ) : (
              <span className="text-muted">Not connected. The token resets every day at 6:00 IST.</span>
            )}
          </div>
          {data.login_url ? (
            <a
              href={data.login_url}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              {data.connected ? "Reconnect" : "Log in with Kite"}
            </a>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
