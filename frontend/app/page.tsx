import { BackendStatus } from "@/components/backend-status";
import { KiteSessionCard } from "@/components/kite-session-card";
import { PageHeader } from "@/components/page-header";
import { PortfolioCard } from "@/components/portfolio/portfolio-card";
import { RegimeBanner } from "@/components/signals/regime-banner";
import { SignalTable } from "@/components/signals/signal-table";

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Dashboard" description="Market regime, today's picks and system health." />
      <div className="grid grid-cols-1 gap-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <BackendStatus />
          <KiteSessionCard />
          <PortfolioCard />
        </div>
        <RegimeBanner />
        <SignalTable limit={10} compact />
      </div>
    </>
  );
}
