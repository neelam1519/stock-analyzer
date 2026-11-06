from datetime import date, datetime

from app.core.clock import IST
from app.models import JobRun
from app.scheduler import runner, timers

SPECS = {spec.id: spec for spec in runner.JOBS}
HOLIDAY = {date(2026, 11, 9)}


def ist(*parts):
    return datetime(*parts, tzinfo=IST)


def fires(job_id: str, now: datetime, holidays: set[date] | None = None) -> datetime:
    return timers.next_fire(SPECS[job_id], now, holidays or set()).astimezone(IST)


def test_next_fire_skips_weekends_holidays_and_off_market_minutes():
    assert fires("monitor", ist(2026, 11, 6, 9, 51, 30)) == ist(2026, 11, 6, 9, 52)
    assert fires("monitor", ist(2026, 11, 6, 8, 0)) == ist(2026, 11, 6, 9, 16)
    assert fires("monitor", ist(2026, 11, 6, 15, 31), HOLIDAY) == ist(2026, 11, 10, 9, 16)
    assert fires("open_fill", ist(2026, 11, 6, 9, 30)) == ist(2026, 11, 6, 9, 40)
    assert fires("end_of_day", ist(2026, 11, 6, 16, 0), HOLIDAY) == ist(2026, 11, 10, 15, 50)
    assert fires("news", ist(2026, 11, 8, 23, 0), HOLIDAY) == ist(2026, 11, 9, 7, 5)
    assert fires("weekly", ist(2026, 11, 6, 12, 0)) == ist(2026, 11, 8, 10, 0)


def test_market_window_open_closed_and_holiday():
    open_now = timers.market_window(ist(2026, 11, 6, 10, 0), HOLIDAY)
    assert open_now["open"] and open_now["closes_at"] == "2026-11-06T10:00:00Z"
    early = timers.market_window(ist(2026, 11, 6, 8, 0), HOLIDAY)
    assert not early["open"] and early["opens_at"] == "2026-11-06T03:45:00Z"
    friday_evening = timers.market_window(ist(2026, 11, 6, 16, 0), HOLIDAY)
    assert friday_evening["opens_at"] == "2026-11-10T03:45:00Z"


def test_timers_payload_reports_last_runs_and_freshness(db, settings):
    db.add(JobRun(job_name="ingest_news", started_at=datetime(2026, 11, 6, 3, 35), status="success", details="new=4"))
    db.commit()
    payload = timers.timers(db, ist(2026, 11, 6, 10, 0))
    jobs = {job["id"]: job for job in payload["jobs"]}
    assert payload["market"]["open"] and payload["now"] == "2026-11-06T04:30:00Z"
    assert jobs["news"]["last_run"]["started_at"] == "2026-11-06T03:35:00Z"
    assert jobs["news"]["last_run"]["details"] == "new=4"
    assert jobs["monitor"]["last_run"] is None and not jobs["monitor"]["enabled"]
    assert {item["key"] for item in payload["data"]} >= {"prices", "news", "candles", "signals", "research"}
    assert payload["kite"] == {"login_at": None, "expires_at": None}
