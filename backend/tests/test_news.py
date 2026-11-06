from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.clock import utc_now
from app.core.db import get_db
from app.ingest.universe import Constituent, sync_instruments
from app.llm.client import parse_json
from app.llm.sentiment import analyze_news
from app.main import create_app
from app.models import LLMCall, NewsArticle, NewsSentiment, NewsSymbolMap
from app.news.collector import RawArticle, normalize_url, parse_feed, parse_nse, store_articles
from app.news.matcher import build_matcher, clean_name, seed_aliases
from tests.fakes import FakeKite, instrument_rows

UNIVERSE = [
    Constituent("RELIANCE", "Reliance Industries Ltd.", "Oil Gas & Consumable Fuels"),
    Constituent("TINYCO", "Tiny Co Ltd.", "Chemicals"),
]

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>RIL shares jump after Jio tariff hike</title><link>https://ex.com/a?utm_source=x</link>
<description>&lt;p&gt;Reliance Industries rallied 4%&lt;/p&gt;</description><pubDate>Thu, 05 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Sensex ends flat; BSE midcap gains</title><link>https://ex.com/b</link></item>
</channel></rss>"""


def setup(db):
    sync_instruments(db, FakeKite(instrument_rows()), UNIVERSE)
    seed_aliases(db)
    return build_matcher(db)


def test_clean_name_and_url_normalization():
    assert clean_name("Reliance Industries Ltd.") == "Reliance Industries"
    assert clean_name("Bharat Electronics Limited") == "Bharat Electronics"
    assert normalize_url("HTTPS://Ex.com/a?utm_source=x&id=2#top") == "https://ex.com/a?id=2"


def test_matcher_uses_symbols_names_and_aliases(db):
    matcher = setup(db)
    found = matcher.match("RIL and Reliance Industries rise; reliance retail; TINYCO flat")
    assert len(found) == 2
    assert matcher.match("RIL hikes tariffs") != {}
    assert matcher.match("Tinyco is lowercase so the symbol is not matched") == {}
    assert matcher.match("BSE Sensex ends higher") == {}


def test_parse_feed_and_nse_rows():
    articles = parse_feed("livemint", RSS)
    assert articles[0].title == "RIL shares jump after Jio tariff hike"
    assert articles[0].summary == "Reliance Industries rallied 4%"
    assert articles[0].published_at == datetime(2026, 11, 5, 10, 0)

    rows = [
        {
            "symbol": "RELIANCE",
            "desc": "Press Release",
            "sm_name": "Reliance Industries Limited",
            "attchmntFile": "https://nse/x.pdf",
            "attchmntText": "Q2 results",
            "an_dt": "05-Nov-2026 22:45:08",
        },
        {"symbol": "RELIANCE", "desc": "Trading Window", "an_dt": "05-Nov-2026 10:00:00"},
        {"symbol": "OTHERCO", "desc": "Press Release", "an_dt": "05-Nov-2026 10:00:00"},
    ]
    parsed = parse_nse(rows, {"RELIANCE"})
    assert len(parsed) == 1 and parsed[0].symbols == ["RELIANCE"]
    assert parsed[0].published_at == datetime(2026, 11, 5, 17, 15, 8)


def test_store_articles_dedups_and_tags(db):
    matcher = setup(db)
    articles = parse_feed("livemint", RSS) + [
        RawArticle("https://ex.com/a", "dup", "dup", None, None),
        RawArticle("https://nse/x.pdf", "nse", "Filing", None, utc_now(), ["TINYCO"]),
    ]
    inserted, mapped = store_articles(db, articles, matcher)
    assert (inserted, mapped) == (3, 2)
    assert store_articles(db, articles, matcher) == (0, 0)
    types = set(db.scalars(select(NewsSymbolMap.match_type)))
    assert types == {"name", "nse"}


class FakeLLM:
    model = "fake/model"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, purpose):
        import json

        self.calls += 1
        items = json.loads(user)["items"]
        return {
            "results": [
                {
                    "id": item["id"],
                    "market": {"sentiment": 0.1, "relevance": 0.2},
                    "stocks": [
                        {"symbol": s, "sentiment": 1.7, "relevance": 0.9, "impact": "HIGH", "rationale": "Tariff hike"}
                        for s in item["candidates"]
                    ]
                    + [{"symbol": "HALLUCINATED", "sentiment": -1, "relevance": 1}],
                }
                for item in items
            ]
        }


def test_analyze_news_scores_once_and_ignores_unknown_symbols(db, settings):
    matcher = setup(db)
    store_articles(db, parse_feed("livemint", RSS), matcher)
    for article in db.scalars(select(NewsArticle)):
        article.published_at = utc_now() - timedelta(hours=1)
    db.commit()

    llm = FakeLLM()
    result = analyze_news(db, llm)
    assert result.articles == 2 and result.calls == 1 and result.scored == 3
    stock_scores = [s for s in db.scalars(select(NewsSentiment)) if s.impact]
    assert len(stock_scores) == 1
    assert float(stock_scores[0].sentiment) == 1.0 and stock_scores[0].impact == "high"

    again = analyze_news(db, llm)
    assert again.articles == 0 and llm.calls == 1


def test_parse_json_extracts_wrapped_payload():
    assert parse_json('```json\n{"results": []}\n```') == {"results": []}


def test_news_and_usage_endpoints(db, settings):
    matcher = setup(db)
    store_articles(db, parse_feed("livemint", RSS), matcher)
    for article in db.scalars(select(NewsArticle)):
        article.published_at = utc_now()
    db.add(
        LLMCall(model="gemini/x", purpose="news_sentiment", prompt_tokens=100, completion_tokens=20, cost_usd=0.0012)
    )
    db.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    headers = {"X-API-Key": "test-key"}

    tagged = client.get("/api/news?tagged_only=true", headers=headers).json()["items"]
    assert len(tagged) == 1 and tagged[0]["symbols"][0]["symbol"] == "RELIANCE"
    assert len(client.get("/api/news?symbol=RELIANCE", headers=headers).json()["items"]) == 1
    usage = client.get("/api/llm/usage", headers=headers).json()
    assert usage["last_24h"]["calls"] == 1 and usage["last_24h"]["tokens"] == 120
    assert db.scalar(select(func.count()).select_from(NewsArticle)) == 2


class FlakyLLM(FakeLLM):
    def complete_json(self, system, user, purpose):
        if self.calls == 0:
            self.calls += 1
            raise ValueError("Expecting property name enclosed in double quotes")
        return super().complete_json(system, user, purpose)


def test_analyze_news_retries_malformed_json_once(db, settings):
    matcher = setup(db)
    store_articles(db, parse_feed("livemint", RSS), matcher)
    for article in db.scalars(select(NewsArticle)):
        article.published_at = utc_now()
    db.commit()
    result = analyze_news(db, FlakyLLM())
    assert result.failed_batches == 0 and result.calls == 2 and result.scored == 3
