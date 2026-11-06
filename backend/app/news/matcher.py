import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Instrument, SymbolAlias

NAME_SUFFIXES = re.compile(r"\s*(\(india\)|\bltd\.?|\blimited\b|\bco\.?\s*$|\bplc\b)\s*", re.IGNORECASE)
SYMBOL_DENYLIST = {"OIL", "IDEA", "BSE", "MCX", "STAR", "FACT", "ATUL", "NAM", "IT", "LT", "GOLD", "SILVER"}

SEED_ALIASES = {
    "RELIANCE": ["RIL", "Reliance Industries"],
    "SBIN": ["SBI", "State Bank of India"],
    "HINDUNILVR": ["HUL", "Hindustan Unilever"],
    "LT": ["L&T", "Larsen & Toubro", "Larsen and Toubro"],
    "M&M": ["M&M", "Mahindra & Mahindra", "Mahindra and Mahindra"],
    "INFY": ["Infosys"],
    "TCS": ["TCS", "Tata Consultancy Services"],
    "HDFCBANK": ["HDFC Bank"],
    "ICICIBANK": ["ICICI Bank"],
    "KOTAKBANK": ["Kotak Mahindra Bank", "Kotak Bank"],
    "AXISBANK": ["Axis Bank"],
    "BHARTIARTL": ["Bharti Airtel", "Airtel"],
    "MARUTI": ["Maruti Suzuki", "Maruti"],
    "TATASTEEL": ["Tata Steel"],
    "BAJFINANCE": ["Bajaj Finance"],
    "BAJAJFINSV": ["Bajaj Finserv"],
    "ASIANPAINT": ["Asian Paints"],
    "SUNPHARMA": ["Sun Pharma", "Sun Pharmaceutical"],
    "ADANIENT": ["Adani Enterprises"],
    "ADANIPORTS": ["Adani Ports"],
    "ADANIGREEN": ["Adani Green"],
    "POWERGRID": ["Power Grid"],
    "COALINDIA": ["Coal India"],
    "HCLTECH": ["HCLTech", "HCL Tech", "HCL Technologies"],
    "ULTRACEMCO": ["UltraTech Cement", "UltraTech"],
    "TITAN": ["Titan Company"],
    "NESTLEIND": ["Nestle India"],
    "ETERNAL": ["Zomato", "Eternal"],
    "JIOFIN": ["Jio Financial"],
    "DMART": ["DMart", "Avenue Supermarts"],
    "PAYTM": ["Paytm", "One 97 Communications"],
    "NYKAA": ["Nykaa"],
    "HAL": ["Hindustan Aeronautics", "HAL"],
    "BEL": ["Bharat Electronics"],
    "INDIGO": ["IndiGo", "InterGlobe Aviation"],
    "TECHM": ["Tech Mahindra"],
    "DRREDDY": ["Dr Reddy's", "Dr. Reddy's"],
    "HEROMOTOCO": ["Hero MotoCorp"],
    "EICHERMOT": ["Eicher Motors", "Royal Enfield"],
    "BAJAJ-AUTO": ["Bajaj Auto"],
    "TATAPOWER": ["Tata Power"],
    "TATACONSUM": ["Tata Consumer"],
    "VEDL": ["Vedanta"],
    "HINDALCO": ["Hindalco"],
    "JSWSTEEL": ["JSW Steel"],
    "GRASIM": ["Grasim"],
    "CIPLA": ["Cipla"],
    "DIVISLAB": ["Divi's Lab", "Divis Lab"],
    "APOLLOHOSP": ["Apollo Hospitals"],
    "IRCTC": ["IRCTC"],
    "LICI": ["LIC", "Life Insurance Corporation"],
}


def clean_name(name: str) -> str:
    cleaned = NAME_SUFFIXES.sub(" ", name or "")
    return re.sub(r"\s+", " ", cleaned).strip(" .,-")


@dataclass(frozen=True)
class Alias:
    instrument_id: int
    text: str
    kind: str


def _pattern(words: list[str], flags: int) -> re.Pattern | None:
    if not words:
        return None
    alternation = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(rf"(?<![\w&]){'(?:' + alternation + ')'}(?![\w&])", flags)


class SymbolMatcher:
    def __init__(self, aliases: list[Alias]):
        self._exact: dict[str, Alias] = {}
        self._folded: dict[str, Alias] = {}
        for alias in aliases:
            if alias.kind == "symbol" or (alias.text.isupper() and len(alias.text) <= 6):
                self._exact.setdefault(alias.text, alias)
            else:
                self._folded.setdefault(alias.text.lower(), alias)
        self._exact_re = _pattern(list(self._exact), 0)
        self._folded_re = _pattern(list(self._folded), re.IGNORECASE)

    def match(self, text: str) -> dict[int, str]:
        found: dict[int, str] = {}
        if self._folded_re:
            for m in self._folded_re.finditer(text):
                alias = self._folded[m.group(0).lower()]
                found.setdefault(alias.instrument_id, alias.kind)
        if self._exact_re:
            for m in self._exact_re.finditer(text):
                alias = self._exact[m.group(0)]
                found.setdefault(alias.instrument_id, alias.kind)
        return found


def seed_aliases(db: Session) -> int:
    symbols = {
        i.tradingsymbol: i.id
        for i in db.scalars(select(Instrument).where(Instrument.in_universe, Instrument.segment == "NSE"))
    }
    existing = set(db.execute(select(SymbolAlias.instrument_id, SymbolAlias.alias)).all())
    added = 0
    for symbol, aliases in SEED_ALIASES.items():
        instrument_id = symbols.get(symbol)
        for alias in aliases if instrument_id else []:
            if (instrument_id, alias) not in existing:
                db.add(SymbolAlias(instrument_id=instrument_id, alias=alias))
                added += 1
    db.commit()
    return added


def build_matcher(db: Session) -> SymbolMatcher:
    aliases: list[Alias] = []
    instruments = db.scalars(select(Instrument).where(Instrument.in_universe, Instrument.segment == "NSE"))
    for instrument in instruments:
        symbol = instrument.tradingsymbol
        if len(symbol) >= 3 and symbol not in SYMBOL_DENYLIST:
            aliases.append(Alias(instrument.id, symbol, "symbol"))
        name = clean_name(instrument.name or "")
        if len(name) >= 5:
            aliases.append(Alias(instrument.id, name, "name"))
    for alias in db.scalars(select(SymbolAlias)):
        aliases.append(Alias(alias.instrument_id, alias.alias, "alias"))
    return SymbolMatcher(aliases)
