#!/usr/bin/env python3
"""
Fetch today's NCAAW Kalshi markets and recent candlesticks.

Based on kalshi/api.ipynb patterns:
- Series: KXNCAAWBGAME
- Resolve markets via GET /markets
- Fetch candlesticks via GET /markets/candlesticks

Outputs a CSV with one row per market including the latest available
1-minute candle near "now". The script adaptively expands the lookback
window until it finds at least one candle (up to a configurable maximum),
then picks the most recent candle to reflect current market prices.

Note: This script does not require auth for public endpoints. If you get
401/403, pass an Authorization header via --auth or KALSHI_AUTH env var.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import re
import os
import sys
import time
from typing import Dict, Iterable, List, Optional

import requests
from zoneinfo import ZoneInfo


BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES_TICKER_DEFAULT = "KXNCAAWBGAME"


def parse_iso_z(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def unix_ts(d: dt.datetime) -> int:
    return int(d.astimezone(dt.timezone.utc).timestamp())


def dollars_close_or_prev(obj: Optional[dict]) -> Optional[float]:
    if not obj:
        return None
    if obj.get("close_dollars") is not None:
        return obj.get("close_dollars")
    return obj.get("previous_dollars")


def pick_latest_candle(candles: List[dict]) -> Optional[dict]:
    if not candles:
        return None
    return max(candles, key=lambda c: c.get("end_period_ts", 0))


def pick_latest_candle_safe(candles: List[dict]) -> Optional[dict]:
    try:
        return pick_latest_candle(candles)
    except Exception:
        return None


def rate_limited_get(rate_limit_per_min: int):
    min_interval = 60.0 / max(1, rate_limit_per_min)
    last_ts = 0.0

    def _get(*args, **kwargs):
        nonlocal last_ts
        now = time.time()
        wait = min_interval - (now - last_ts)
        if wait > 0:
            time.sleep(wait)
        resp = requests.get(*args, **kwargs)
        last_ts = time.time()
        return resp

    return _get


def iter_markets(
    *,
    series_ticker: str,
    status: Optional[str] = None,
    limit: int = 1000,
    headers: Optional[Dict[str, str]] = None,
    http_get=requests.get,
) -> Iterable[dict]:
    cursor = ""
    while True:
        params = {"series_ticker": series_ticker, "limit": limit}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        r = http_get(f"{BASE}/markets", params=params, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json() or {}
        for m in data.get("markets", []):
            yield m
        cursor = data.get("cursor") or ""
        if not cursor:
            break


def markets_for_local_date(
    markets: Iterable[dict], *, local_tz: ZoneInfo, date_local: dt.date
) -> List[dict]:
    out = []
    for m in markets:
        ct = m.get("close_time")
        if not ct:
            continue
        close_dt_utc = parse_iso_z(ct)
        game_date_local = close_dt_utc.astimezone(local_tz).date()
        if game_date_local == date_local:
            out.append(m)
    return out


_DATE_TOKEN_RE = re.compile(r"^[A-Z]+-([0-9]{2}[A-Z]{3}[0-9]{2})")


def _token_for_date(d: dt.date) -> str:
    mon = calendar.month_abbr[d.month].upper()
    return f"{d.year % 100:02d}{mon}{d.day:02d}"


def _extract_token_from_ticker(ticker: str) -> Optional[str]:
    # Expect leading portion like SERIES-YYMONDD...
    # e.g., KXNCAAWBGAME-25DEC21MERTULN-MER -> 25DEC21
    m = _DATE_TOKEN_RE.match(ticker or "")
    return m.group(1) if m else None


def filter_by_ticker_date(markets: Iterable[dict], *, target: dt.date) -> List[dict]:
    tok = _token_for_date(target)
    out = []
    for m in markets:
        t = m.get("ticker") or ""
        tt = _extract_token_from_ticker(t)
        if tt == tok:
            out.append(m)
    return out


def fetch_candles_for_ticker(
    ticker: str,
    *,
    start_ts: int,
    end_ts: int,
    period_interval: int = 1,
    headers: Optional[Dict[str, str]] = None,
    http_get=requests.get,
) -> List[dict]:
    r = http_get(
        f"{BASE}/markets/candlesticks",
        params={
            "market_tickers": ticker,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "period_interval": period_interval,
        },
        headers=headers,
        timeout=30,
    )
    if r.status_code != 200:
        # Surface a concise error; caller will record it.
        raise requests.HTTPError(f"{r.status_code}: {r.text[:200]}", response=r)
    j = r.json() or {}
    mkts = j.get("markets", [])
    return mkts[0].get("candlesticks", []) if mkts else []


def fetch_latest_candle_for_ticker(
    ticker: str,
    *,
    end_ts: int,
    initial_lookback_min: int,
    max_lookback_min: int,
    period_interval: int = 1,
    headers: Optional[Dict[str, str]] = None,
    http_get=requests.get,
) -> Optional[dict]:
    """Fetch the most recent candle by adaptively expanding lookback.

    Tries increasing windows ending at ``end_ts`` until it finds at least
    one candle or reaches ``max_lookback_min``. Returns the latest candle
    in the window if found, else None.
    """
    lb = max(1, int(initial_lookback_min))
    max_lb = max(lb, int(max_lookback_min))
    while lb <= max_lb:
        start_ts = end_ts - lb * 60
        candles = fetch_candles_for_ticker(
            ticker,
            start_ts=start_ts,
            end_ts=end_ts,
            period_interval=period_interval,
            headers=headers,
            http_get=http_get,
        )
        latest = pick_latest_candle_safe(candles)
        if latest:
            return latest
        # Expand the window (double each iteration) but cap at max_lb
        if lb >= max_lb:
            break
        lb = min(max_lb, lb * 2)
    return None


def build_headers(auth_header: Optional[str]) -> Dict[str, str]:
    if not auth_header:
        # Empty headers is fine for public endpoints; Kalshi may not require auth.
        return {}
    # Accept either full header string like "Bearer abc..." or raw token.
    if " " in auth_header:
        return {"Authorization": auth_header}
    return {"Authorization": f"Bearer {auth_header}"}


def fmt_float(x: Optional[float]) -> str:
    try:
        if x is None:
            return ""
        return f"{float(x):.4f}"
    except Exception:
        return ""


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    # Relative-day selector: t (today), t1 (tomorrow), t2 (in two days).
    # Ignored if --date is provided.
    p.add_argument(
        "when",
        nargs="?",
        default="t",
        choices=["t", "t1", "t2"],
        help="Target day: t (today), t1 (tomorrow), t2 (two days). Default: t",
    )
    p.add_argument("--series", default=SERIES_TICKER_DEFAULT, help="Kalshi series ticker (default: KXNCAAWBGAME)")
    p.add_argument("--status", default=None, help="Optional market status filter (e.g., trading, open)")
    p.add_argument("--date", default=None, help="Target local date YYYY-MM-DD (default: today in local TZ)")
    p.add_argument("--local-tz", default="America/New_York", help="Local timezone (default: America/New_York)")
    p.add_argument("--lookback-min", type=int, default=15, help="Initial lookback minutes ending now (default: 15)")
    p.add_argument("--max-lookback-min", type=int, default=24*60, help="Max lookback minutes for adaptive latest search (default: 1440)")
    p.add_argument("--period-min", type=int, default=1, help="Candlestick period in minutes (default: 1)")
    p.add_argument("--rate-limit", type=int, default=20, help="Max requests per minute (default: 20)")
    p.add_argument("--out", default="kalshi/today_candles.csv", help="Output CSV path")
    p.add_argument("--auth", default=os.getenv("KALSHI_AUTH", ""), help="Authorization header or token; env KALSHI_AUTH also supported")
    # Filtering controls
    p.add_argument("--no-ticker-date-filter", dest="ticker_date_filter", action="store_false",
                   help="Do not filter by YYMONDD date embedded in ticker")
    p.add_argument("--no-only-open", dest="only_open", action="store_false",
                   help="Do not restrict to open/trading markets (default)")
    p.set_defaults(ticker_date_filter=True, only_open=False)
    args = p.parse_args(argv)

    local_tz = ZoneInfo(args.local_tz)
    if args.date:
        try:
            target_date_local = dt.date.fromisoformat(args.date)
        except Exception as e:
            print(f"Invalid --date: {args.date}: {e}", file=sys.stderr)
            return 2
    else:
        # Map when -> offset days
        when_map = {"t": 0, "t1": 1, "t2": 2}
        offset_days = when_map.get(args.when, 0)
        target_date_local = (dt.datetime.now(tz=local_tz) + dt.timedelta(days=offset_days)).date()

    headers = build_headers(args.auth)
    http_get = rate_limited_get(args.rate_limit)

    # 1) Fetch and filter markets for the target local date
    try:
        all_markets = list(
            iter_markets(
                series_ticker=args.series,
                status=args.status,
                headers=headers,
                http_get=http_get,
            )
        )
    except Exception as e:
        print(f"Failed to fetch markets: {e}", file=sys.stderr)
        return 1

    # Primary filter: ticker-embedded date; secondary: local-date from close_time
    filtered = all_markets
    if args.ticker_date_filter:
        by_token = filter_by_ticker_date(filtered, target=target_date_local)
        print(f"Ticker-date match: {len(by_token)} of {len(filtered)}")
        filtered = by_token
    else:
        by_local = markets_for_local_date(filtered, local_tz=local_tz, date_local=target_date_local)
        print(f"Local-date match: {len(by_local)} of {len(filtered)}")
        filtered = by_local

    if args.only_open:
        allowed = {"open", "trading"}
        before = len(filtered)
        filtered = [m for m in filtered if (m.get("status") or "").lower() in allowed]
        print(f"Open/trading filter: {len(filtered)} of {before}")

    if not filtered:
        print("No markets found after filtering.")

    todays = filtered

    # 2) For each market, fetch the latest available candle ending near now
    now_utc = dt.datetime.now(tz=dt.timezone.utc)
    end_ts = unix_ts(now_utc)

    rows = []
    for m in todays:
        ticker = m.get("ticker") or ""
        title = m.get("title") or ""
        close_time = m.get("close_time") or ""
        try:
            latest = fetch_latest_candle_for_ticker(
                ticker,
                end_ts=end_ts,
                initial_lookback_min=args.lookback_min,
                max_lookback_min=args.max_lookback_min,
                period_interval=args.period_min,
                headers=headers,
                http_get=http_get,
            )
            if latest:
                end_period_ts = latest.get("end_period_ts")
                end_period_utc = dt.datetime.fromtimestamp(end_period_ts, tz=dt.timezone.utc).isoformat() if end_period_ts else ""
                price = dollars_close_or_prev(latest.get("price") or {})
                bid = dollars_close_or_prev(latest.get("yes_bid") or {})
                ask = dollars_close_or_prev(latest.get("yes_ask") or {})
                volume = latest.get("volume")
                oi = latest.get("open_interest")
                status = "ok"
                error = ""
            else:
                end_period_utc = ""
                price = bid = ask = None
                volume = oi = None
                status = "no_candle"
                error = "no candle found up to max lookback"
        except Exception as e:
            end_period_utc = ""
            price = bid = ask = None
            volume = oi = None
            status = "error"
            error = str(e)

        rows.append(
            {
                "ticker": ticker,
                "title": title,
                "close_time_utc": close_time,
                "latest_end_period_utc": end_period_utc,
                "price_close_dollars": fmt_float(price),
                "yes_bid_close_dollars": fmt_float(bid),
                "yes_ask_close_dollars": fmt_float(ask),
                "volume": volume if volume is not None else "",
                "open_interest": oi if oi is not None else "",
                "status": status,
                "error": error,
            }
        )

    # 3) Write output CSV
    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fieldnames = [
        "ticker",
        "title",
        "close_time_utc",
        "latest_end_period_utc",
        "price_close_dollars",
        "yes_bid_close_dollars",
        "yes_ask_close_dollars",
        "volume",
        "open_interest",
        "status",
        "error",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {len(rows)} rows -> {out_path}")

    # 4) Console summary: show a few potential buy opportunities by spread
    def to_float(s: str) -> Optional[float]:
        try:
            return float(s)
        except Exception:
            return None

    candidates = []
    for r in rows:
        bid = to_float(r.get("yes_bid_close_dollars") or "")
        ask = to_float(r.get("yes_ask_close_dollars") or "")
        if bid is None and ask is None:
            continue
        spread = (ask - bid) if (bid is not None and ask is not None) else None
        candidates.append((spread if spread is not None else 0.0, r))

    # Show top 10 widest spreads as a quick glance list
    if candidates:
        print("\nTop markets by current yes spread (ask - bid):")
        for _, r in sorted(candidates, key=lambda x: x[0], reverse=True)[:10]:
            bid = r.get("yes_bid_close_dollars") or ""
            ask = r.get("yes_ask_close_dollars") or ""
            print(f"- {r['ticker']} | {r['title']} | bid {bid} / ask {ask}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
