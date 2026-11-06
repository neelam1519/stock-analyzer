import json

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.models import AppSetting
from app.signals.scoring import DEFAULT_PARAMS, StrategyParams

SETTING_KEY = "strategy.active"


def _from_dict(data: dict) -> StrategyParams:
    allowed = set(StrategyParams.__dataclass_fields__)
    clean = {k: v for k, v in data.items() if k in allowed}
    if "entry_regimes" in clean:
        clean["entry_regimes"] = tuple(clean["entry_regimes"])
    return StrategyParams(**clean)


def to_dict(params: StrategyParams) -> dict:
    data = dict(params.__dict__)
    data["entry_regimes"] = list(params.entry_regimes)
    data["regime_adjustment"] = dict(params.regime_adjustment)
    return data


def load_active_params(db: Session) -> tuple[StrategyParams, str | None]:
    setting = db.get(AppSetting, SETTING_KEY)
    if setting is None:
        return DEFAULT_PARAMS, None
    payload = json.loads(setting.value)
    return _from_dict(payload["params"]), payload.get("source")


def save_active_params(db: Session, params: StrategyParams, source: str) -> None:
    setting = db.get(AppSetting, SETTING_KEY) or AppSetting(key=SETTING_KEY)
    setting.value = json.dumps({"params": to_dict(params), "source": source})
    setting.updated_at = utc_now()
    db.add(setting)
    db.commit()


def reset_active_params(db: Session) -> None:
    setting = db.get(AppSetting, SETTING_KEY)
    if setting is not None:
        db.delete(setting)
        db.commit()
