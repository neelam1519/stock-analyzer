import { Suspense } from "react";

import { StockView } from "@/components/stocks/stock-view";

async function StockPageContent({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  return <StockView symbol={decodeURIComponent(symbol)} />;
}

export default function StockPage(props: PageProps<"/stocks/[symbol]">) {
  return (
    <Suspense fallback={<div className="h-[520px] animate-pulse rounded-lg bg-surface" />}>
      <StockPageContent params={props.params} />
    </Suspense>
  );
}
