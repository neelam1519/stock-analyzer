"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

type DbHealth = { status: string; server: string };

export function BackendStatus() {
  const { data, error, isPending } = useQuery({
    queryKey: ["health", "db"],
    queryFn: () => api<DbHealth>("health/db"),
  });

  const state = isPending ? "checking" : error ? "down" : "up";
  const tone = { checking: "bg-muted", down: "bg-negative", up: "bg-positive" }[state];

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className={`h-2 w-2 rounded-full ${tone}`} />
        Backend + SQL Server
      </div>
      <p className="mt-2 truncate font-mono text-xs text-muted">
        {isPending ? "Checking…" : error ? error.message : data?.server}
      </p>
    </div>
  );
}
