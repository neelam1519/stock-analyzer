import hashlib
import html
import re
from calendar import timegm
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import IST, to_utc_naive
from app.models import Instrument, NewsArticle, NewsSymbolMap
from app.news.matcher import SymbolMatcher

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
RSS_FEEDS = {
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
    "livemint": "https://www.livemint.com/rss/markets",
    "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
}
NSE_HOME = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_ANNOUNCEMENTS = "https://www.nseindia.com/api/corporate-announcements?index=equities"
NSE_NOISE = (
    "trading window",
    "depositories and participants",
    "newspaper publication",
    "loss of share certificate",
    "duplicate share",
    "registrar",
    "esop",
    "esos",
    "allotment of securities",
    "analysts/institutional investor meet",
)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class RawArticle:
    url: str
    source: str
    title: str
    summary: str | None
    published_at: datetime | None
    symbols: list[str] = field(default_factory=list)


@dataclass
class CollectResult:
    fetched: int = 0
    inserted: int = 0
    mapped: int = 0
    errors: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def clean_text(value: str | None, limit: int = 2000) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", value))).strip()
    return text[:limit] or None


def _entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(timegm(parsed), UTC).replace(tzinfo=None) if parsed else None


def parse_feed(source: str, content: bytes | str) -> list[RawArticle]:
    feed = feedparser.parse(content)
    articles = []
    for entry in feed.entries:
        link, title = entry.get("link"), clean_text(entry.get("title"), 1000)
        if link and title:
            articles.append(RawArticle(link, source, title, clean_text(entry.get("summary")), _entry_time(entry)))
    return articles


def fetch_rss(client: httpx.Client, source: str, url: str) -> list[RawArticle]:
    response = client.get(url)
    response.raise_for_status()
    return parse_feed(source, response.content)


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}+when:7d&hl=en-IN&gl=IN&ceid=IN:en"


def parse_nse(rows: list[dict], universe: set[str]) -> list[RawArticle]:
    articles = []
    for row in rows:
        symbol = (row.get("symbol") or "").strip()
        desc = (row.get("desc") or "").strip()
        if symbol not in universe or any(noise in desc.lower() for noise in NSE_NOISE):
            continue
        url = row.get("attchmntFile") or f"https://www.nseindia.com/announcement/{row.get('seq_id')}"
        try:
            published = to_utc_naive(datetime.strptime(row["an_dt"], "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST))
        except (KeyError, ValueError):
            published = None
        title = f"{row.get('sm_name') or symbol}: {desc}"
        articles.append(RawArticle(url, "nse", title[:1000], clean_text(row.get("attchmntText")), published, [symbol]))
    return articles


def fetch_nse(client: httpx.Client, universe: set[str]) -> list[RawArticle]:
    client.get(NSE_HOME)
    response = client.get(NSE_ANNOUNCEMENTS, headers={"Accept": "application/json", "Referer": NSE_HOME})
    response.raise_for_status()
    return parse_nse(response.json(), universe)


def store_articles(db: Session, articles: list[RawArticle], matcher: SymbolMatcher) -> tuple[int, int]:
    by_hash: dict[str, RawArticle] = {}
    for article in articles:
        by_hash.setdefault(url_hash(article.url), article)
    hashes = list(by_hash)
    existing: set[str] = set()
    for start in range(0, len(hashes), 500):
        existing.update(
            db.scalars(select(NewsArticle.url_hash).where(NewsArticle.url_hash.in_(hashes[start : start + 500])))
        )

    symbol_ids = dict(db.execute(select(Instrument.tradingsymbol, Instrument.id).where(Instrument.in_universe)).all())
    inserted = mapped = 0
    for digest, raw in by_hash.items():
        if digest in existing:
            continue
        article = NewsArticle(
            url_hash=digest,
            url=raw.url[:2048],
            source=raw.source,
            title=raw.title,
            summary=raw.summary,
            published_at=raw.published_at,
        )
        db.add(article)
        db.flush()
        matches = {symbol_ids[s]: "nse" for s in raw.symbols if s in symbol_ids}
        for instrument_id, kind in matcher.match(f"{raw.title} {raw.summary or ''}").items():
            matches.setdefault(instrument_id, kind)
        for instrument_id, kind in matches.items():
            db.add(NewsSymbolMap(article_id=article.id, instrument_id=instrument_id, match_type=kind))
        inserted += 1
        mapped += int(bool(matches))
    db.commit()
    return inserted, mapped


def collect_news(db: Session, matcher: SymbolMatcher, symbols: list[str] | None = None) -> CollectResult:
    result = CollectResult()
    universe = set(db.scalars(select(Instrument.tradingsymbol).where(Instrument.in_universe)))
    articles: list[RawArticle] = []
    with httpx.Client(headers={"User-Agent": BROWSER_UA}, timeout=20, follow_redirects=True) as client:
        sources = [(name, lambda url=url, name=name: fetch_rss(client, name, url)) for name, url in RSS_FEEDS.items()]
        sources.append(("nse", lambda: fetch_nse(client, universe)))
        names = dict(
            db.execute(
                select(Instrument.tradingsymbol, Instrument.name).where(Instrument.tradingsymbol.in_(symbols or []))
            ).all()
        )
        for symbol in symbols or []:
            query = f'"{names.get(symbol) or symbol}" share'
            sources.append((f"google:{symbol}", lambda q=query: fetch_rss(client, "google_news", google_news_url(q))))
        for name, fetch in sources:
            try:
                batch = fetch()
                result.fetched += len(batch)
                articles.extend(batch)
            except (httpx.HTTPError, ValueError) as exc:
                result.errors.append(f"{name}: {type(exc).__name__}")
    result.inserted, result.mapped = store_articles(db, articles, matcher)
    return result
