from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def now_ist() -> datetime:
    return datetime.now(IST)


def is_weekday(day: date) -> bool:
    return day.weekday() < 5


def is_market_hours(moment: datetime | None = None) -> bool:
    moment = (moment or now_ist()).astimezone(IST)
    return is_weekday(moment.date()) and MARKET_OPEN <= moment.time() <= MARKET_CLOSE


KITE_TOKEN_RESET = time(6, 0)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_naive(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=IST)
    return moment.astimezone(UTC).replace(tzinfo=None)


def kite_token_expiry(login_time: datetime) -> datetime:
    login_ist = login_time.astimezone(IST) if login_time.tzinfo else login_time.replace(tzinfo=IST)
    reset = datetime.combine(login_ist.date(), KITE_TOKEN_RESET, IST)
    if login_ist >= reset:
        reset += timedelta(days=1)
    return to_utc_naive(reset)


def last_completed_session(moment: datetime | None = None) -> date:
    moment = (moment or now_ist()).astimezone(IST)
    day = moment.date()
    if not is_weekday(day) or moment.time() < time(15, 45):
        day -= timedelta(days=1)
    while not is_weekday(day):
        day -= timedelta(days=1)
    return day
