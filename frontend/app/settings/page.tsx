import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { DataCard } from "@/components/settings/data-card";
import { KiteCard } from "@/components/settings/kite-card";
import { NewsCard } from "@/components/settings/news-card";
import { RiskCard } from "@/components/settings/risk-card";
import { SchedulerCard } from "@/components/settings/scheduler-card";
import { TradingModeCard } from "@/components/settings/trading-mode-card";

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Kite login, risk limits, automation and data jobs." />
      <div className="grid grid-cols-1 gap-4">
        <Suspense fallback={<div className="h-24 rounded-lg border border-line bg-surface" />}>
          <KiteCard />
        </Suspense>
        <TradingModeCard />
        <RiskCard />
        <SchedulerCard />
        <NewsCard />
        <DataCard />
      </div>
    </>
  );
}
