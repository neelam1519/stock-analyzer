"use client";

import { Card } from "@/components/card";
import { JobsList, useSchedulerClock } from "@/components/timers/timers-card";

export function SchedulerCard() {
  const { data, error, now } = useSchedulerClock();

  return (
    <Card title="Automation (IST, NSE trading days)">
      {error ? <p className="text-sm text-negative">{error.message}</p> : null}
      {data && now != null ? <JobsList data={data} now={now} /> : null}
      <p className="mt-2 text-xs text-muted">
        Jobs that need market data stop with a clear error if today&apos;s Kite login is missing. Log in each morning before 09:15.
      </p>
    </Card>
  );
}
