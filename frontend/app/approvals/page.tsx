import { ApprovalsView } from "@/components/approvals/approvals-view";
import { PageHeader } from "@/components/page-header";

export default function ApprovalsPage() {
  return (
    <>
      <PageHeader
        title="Approvals"
        description="Real orders only go to Zerodha after you approve them here. Entries are CNC limit orders, protected by a GTT stop-loss and target once filled."
      />
      <ApprovalsView />
    </>
  );
}
