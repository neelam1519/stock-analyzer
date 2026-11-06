import re
from pathlib import Path

from sqlalchemy import false, select, true
from sqlalchemy.dialects import mssql

from app.models.trading import LiveOrder

APP_DIR = Path(__file__).resolve().parents[1] / "app"
BOOLEAN_IS = re.compile(r"\.is_\((True|False)\)|\.is_not\((True|False)\)")


def test_no_boolean_is_comparisons_in_app():
    offenders = [
        f"{path.relative_to(APP_DIR.parent)}:{number}"
        for path in APP_DIR.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if BOOLEAN_IS.search(line)
    ]
    assert offenders == []


def test_boolean_filters_compile_to_equality_on_mssql():
    for value, expected in ((false(), "= 0"), (true(), "= 1")):
        sql = str(
            select(LiveOrder.id)
            .where(LiveOrder.dry_run == value)
            .compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True})
        )
        assert expected in sql
        assert " IS " not in sql
