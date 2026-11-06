import { PageHeader } from "@/components/page-header";
import { StockTable } from "@/components/stocks/stock-table";

export default function StocksPage() {
  return (
    <>
      <PageHeader title="Stocks" description="NIFTY 500 universe plus benchmark indices, from SQL Server." />
      <StockTable />
    </>
  );
}
