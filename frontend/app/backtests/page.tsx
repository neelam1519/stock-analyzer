import { BacktestsView } from "@/components/backtests/backtests-view";
import { PageHeader } from "@/components/page-header";

export default function BacktestsPage() {
  return (
    <>
      <PageHeader
        title="Backtests"
        description="Replays the exact live scoring rules over stored history, with next-day-open entries, real costs and portfolio limits."
      />
      <BacktestsView />
    </>
  );
}
