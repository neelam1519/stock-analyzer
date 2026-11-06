import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import get_settings
from app.models import AppSetting

SETTING_KEY = "trading.live"
MODES = ("paper", "approve")


@dataclass
class LiveSettings:
    mode: str = "paper"
    dry_run: bool = True
    live_capital: float = 100_000.0
    max_order_value: float = 25_000.0
    entry_buffer_pct: float = 0.5
    max_price_drift_pct: float = 2.0


def load_live_settings(db: Session) -> LiveSettings:
    setting = db.get(AppSetting, SETTING_KEY)
    if setting is None:
        mode = get_settings().trading_mode if get_settings().trading_mode in MODES else "paper"
        return LiveSettings(mode=mode)
    data = json.loads(setting.value)
    allowed = set(LiveSettings.__dataclass_fields__)
    return LiveSettings(**{k: v for k, v in data.items() if k in allowed})


def save_live_settings(db: Session, settings: LiveSettings) -> LiveSettings:
    setting = db.get(AppSetting, SETTING_KEY) or AppSetting(key=SETTING_KEY)
    setting.value = json.dumps(asdict(settings))
    setting.updated_at = utc_now()
    db.add(setting)
    db.commit()
    return settings
