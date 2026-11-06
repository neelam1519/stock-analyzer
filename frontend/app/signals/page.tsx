import { PageHeader } from "@/components/page-header";
import { RegimeBanner } from "@/components/signals/regime-banner";
import { SignalTable } from "@/components/signals/signal-table";

export default function SignalsPage() {
  return (
    <>
      <PageHeader
        title="Signals"
        description="Swing setups scored on trend, momentum, strength, volume, 52-week-high proximity and news. Click a row for the reasoning."
      />
      <div className="grid grid-cols-1 gap-4">
        <RegimeBanner />
        <SignalTable />
      </div>
    </>
  );
}
