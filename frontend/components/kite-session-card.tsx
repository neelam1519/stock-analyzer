"use client";

import Link from "next/link";

import { formatDateTime } from "@/lib/format";
import { useKiteStatus } from "@/lib/queries";

export function KiteSessionCard() {
  const { data, isPending, error } = useKiteStatus();
  const connected = data?.connected;
  return (
    <Link href="/settings" className="rounded-lg border border-line bg-surface p-4 hover:border-muted">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className={`h-2 w-2 rounded-full ${connected ? "bg-positive" : isPending ? "bg-muted" : "bg-negative"}`} />
        Kite session
      </div>
      <p className="mt-2 truncate font-mono text-xs text-muted">
        {isPending
          ? "Checking…"
          : error
            ? error.message
            : connected
              ? `${data?.user_id} · until ${formatDateTime(data?.expires_at ?? null)}`
              : "Not connected. Log in from Settings."}
      </p>
    </Link>
  );
}
