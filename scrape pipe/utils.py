from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlparse

import pandas as pd


def parse_any_date(val: str | int | float) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s:
        return None
    dt = pd.to_datetime(s, errors="coerce", infer_datetime_format=True)
    if pd.isna(dt):
        return None
    if isinstance(dt, pd.Timestamp):
        return dt.date()
    if isinstance(dt, datetime):
        return dt.date()
    return None


def game_id_from_boxscore_url(url: str) -> str | None:
    if not url:
        return None
    path = urlparse(url).path
    base = path.rsplit("/", 1)[-1]
    if not base.endswith(".html"):
        return None
    return base[:-5]
