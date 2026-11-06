from datetime import date, datetime, timedelta

from app.core.clock import IST


def weekdays(start: date, end: date) -> list[date]:
    days, cursor = [], start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


class FakeKite:
    def __init__(self, instruments=None, closes=None):
        self._instruments = instruments or []
        self.closes = closes or {}
        self.calls: list[tuple] = []

    def instruments(self, exchange=None):
        return self._instruments

    def historical_data(self, instrument_token, from_date, to_date, interval):
        self.calls.append((instrument_token, from_date, to_date, interval))
        start = from_date.date() if isinstance(from_date, datetime) else from_date
        stop = to_date.date() if isinstance(to_date, datetime) else to_date
        candles = []
        for day in weekdays(start, stop):
            close = self.closes.get((instrument_token, day), 100.0)
            stamps = (
                [datetime.combine(day, datetime.min.time(), IST)]
                if interval == "day"
                else [datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(hours=h) for h in range(7)]
            )
            for stamp in stamps:
                candles.append(
                    {"date": stamp, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000}
                )
        return candles


def instrument_rows():
    return [
        {
            "instrument_token": 1,
            "exchange_token": 11,
            "tradingsymbol": "RELIANCE",
            "name": "RELIANCE INDUSTRIES",
            "segment": "NSE",
            "instrument_type": "EQ",
            "exchange": "NSE",
            "lot_size": 1,
            "tick_size": 0.05,
        },
        {
            "instrument_token": 2,
            "exchange_token": 22,
            "tradingsymbol": "TINYCO",
            "name": "TINY CO",
            "segment": "NSE",
            "instrument_type": "EQ",
            "exchange": "NSE",
            "lot_size": 1,
            "tick_size": 0.05,
        },
        {
            "instrument_token": 256265,
            "exchange_token": 1,
            "tradingsymbol": "NIFTY 50",
            "name": "NIFTY 50",
            "segment": "INDICES",
            "instrument_type": "EQ",
            "exchange": "NSE",
            "lot_size": 0,
            "tick_size": 0,
        },
        {
            "instrument_token": 9,
            "exchange_token": 99,
            "tradingsymbol": "RELIANCE-BE",
            "name": "X",
            "segment": "NSE",
            "instrument_type": "BE",
            "exchange": "NSE",
            "lot_size": 1,
            "tick_size": 0.05,
        },
    ]
