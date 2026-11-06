import { PageHeader } from "@/components/page-header";
import { PortfolioView } from "@/components/portfolio/portfolio-view";

export default function PortfolioPage() {
  return (
    <>
      <PageHeader
        title="Paper portfolio"
        description="Simulated trading with live Kite prices. Orders fill at the next open, stops and targets are checked every 2 minutes, and trailing stops update at the close."
      />
      <PortfolioView />
    </>
  );
}
