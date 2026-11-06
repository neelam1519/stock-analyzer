import { NewsFeed } from "@/components/news/news-feed";
import { PageHeader } from "@/components/page-header";

export default function NewsPage() {
  return (
    <>
      <PageHeader
        title="News"
        description="NSE filings and market news, tagged to stocks and scored by the LLM for 1–4 week impact."
      />
      <NewsFeed />
    </>
  );
}
