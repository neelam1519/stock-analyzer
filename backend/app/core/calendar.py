import json
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.clock import now_ist, utc_now
from app.models import AppSetting

HOLIDAY_PAGE = "https://www.nseindia.com/resources/exchange-communication-holidays"
HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
SETTING_KEY = "nse.holidays"
REFRESH_AFTER = timedelta(days=7)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def parse_holidays(payload: dict) -> list[str]:
    days = []
    for row in payload.get("CM", []):
        try:
            days.append(datetime.strptime(row["tradingDate"], "%d-%b-%Y").date().isoformat())
        except (KeyError, ValueError):
            continue
    return sorted(set(days))


def fetch_holidays() -> list[str]:
    with httpx.Client(headers={"User-Agent": BROWSER_UA}, timeout=20, follow_redirects=True) as client:
        client.get(HOLIDAY_PAGE)
        response = client.get(HOLIDAY_API, headers={"Accept": "application/json", "Referer": HOLIDAY_PAGE})
        response.raise_for_status()
        return parse_holidays(response.json())


def refresh_holidays(db: Session, force: bool = False) -> set[date]:
    setting = db.get(AppSetting, SETTING_KEY)
    if setting and not force and setting.updated_at and utc_now() - setting.updated_at < REFRESH_AFTER:
        return {date.fromisoformat(d) for d in json.loads(setting.value)}
    try:
        days = fetch_holidays()
    except (httpx.HTTPError, ValueError):
        return {date.fromisoformat(d) for d in json.loads(setting.value)} if setting else set()
    known = set(json.loads(setting.value)) if setting else set()
    merged = sorted(known | set(days))
    setting = setting or AppSetting(key=SETTING_KEY)
    setting.value = json.dumps(merged)
    setting.updated_at = utc_now()
    db.add(setting)
    db.commit()
    return {date.fromisoformat(d) for d in merged}


def cached_holidays(db: Session) -> set[date]:
    setting = db.get(AppSetting, SETTING_KEY)
    return {date.fromisoformat(d) for d in json.loads(setting.value)} if setting else set()


def is_trading_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def today_is_trading_day(db: Session) -> bool:
    return is_trading_day(now_ist().date(), cached_holidays(db))


def next_trading_day(day: date, holidays: set[date]) -> date:
    cursor = day + timedelta(days=1)
    while not is_trading_day(cursor, holidays):
        cursor += timedelta(days=1)
    return cursor
