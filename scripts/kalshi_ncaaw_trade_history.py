#!/usr/bin/env python3
"""
Fetch authenticated Kalshi fills and export NCAAW trade history to Excel.

Uses GET /portfolio/fills (authenticated) and filters by ticker prefix
to isolate NCAAW markets. Writes an .xlsx with fills + summary.

Auth: RSA-PSS signature of "{timestamp}{method}{path}" where path is the
API path without query params (see Kalshi quick start authenticated requests).
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import os
import subprocess
import sys
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlencode

import requests
from openpyxl import Workbook


BASE = "https://api.elections.kalshi.com/trade-api/v2"
FILLS_PATH = "/trade-api/v2/portfolio/fills"


def _unix_ms_now() -> int:
    return int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000)


def _date_to_ts(date_str: str, *, end: bool = False) -> int:
    d = dt.date.fromisoformat(date_str)
    if end:
        dt_utc = dt.datetime.combine(d, dt.time(23, 59, 59), tzinfo=dt.timezone.utc)
    else:
        dt_utc = dt.datetime.combine(d, dt.time(0, 0, 0), tzinfo=dt.timezone.utc)
    return int(dt_utc.timestamp())


def _build_message(timestamp_ms: int, method: str, path: str) -> bytes:
    path_without_query = path.split("?", 1)[0]
    msg = f"{timestamp_ms}{method.upper()}{path_without_query}"
    return msg.encode("utf-8")


def _openssl_sign_pss_sha256(message: bytes, private_key_path: str) -> str:
    try:
        proc = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                private_key_path,
                "-sigopt",
                "rsa_padding_mode:pss",
                "-sigopt",
                "rsa_pss_saltlen:-1",
                "-binary",
            ],
            input=message,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("openssl is required to sign requests but was not found") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"openssl signing failed: {exc.stderr.decode('utf-8', 'ignore')[:200]}") from exc
    return base64.b64encode(proc.stdout).decode("utf-8")


def _auth_headers(
    *,
    key_id: str,
    private_key_path: str,
    method: str,
    path: str,
) -> Dict[str, str]:
    timestamp_ms = _unix_ms_now()
    signature = _openssl_sign_pss_sha256(
        _build_message(timestamp_ms, method, path),
        private_key_path,
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def _fetch_fills_page(
    *,
    key_id: str,
    private_key_path: str,
    params: Dict[str, str],
    session: requests.Session,
) -> Dict[str, object]:
    path = FILLS_PATH
    if params:
        path = f"{path}?{urlencode(params)}"
    headers = _auth_headers(
        key_id=key_id,
        private_key_path=private_key_path,
        method="GET",
        path=path,
    )
    resp = session.get(f"{BASE}/portfolio/fills", params=params, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
    return resp.json() or {}


def iter_fills(
    *,
    key_id: str,
    private_key_path: str,
    ticker: Optional[str],
    min_ts: Optional[int],
    max_ts: Optional[int],
    limit: int,
) -> Iterable[dict]:
    cursor = ""
    session = requests.Session()
    while True:
        params: Dict[str, str] = {"limit": str(limit)}
        if ticker:
            params["ticker"] = ticker
        if min_ts is not None:
            params["min_ts"] = str(min_ts)
        if max_ts is not None:
            params["max_ts"] = str(max_ts)
        if cursor:
            params["cursor"] = cursor
        data = _fetch_fills_page(
            key_id=key_id,
            private_key_path=private_key_path,
            params=params,
            session=session,
        )
        fills = data.get("fills") or []
        for f in fills:
            yield f
        cursor = data.get("cursor") or ""
        if not cursor:
            break


def _price_cents(fill: dict) -> Optional[int]:
    side = (fill.get("side") or "").lower()
    if side == "yes":
        val = fill.get("yes_price")
    elif side == "no":
        val = fill.get("no_price")
    else:
        val = None
    if val is None:
        val = fill.get("price")
    return int(val) if val is not None else None


def _cash_flow_cents(fill: dict) -> Optional[int]:
    count = fill.get("count")
    price = _price_cents(fill)
    if count is None or price is None:
        return None
    action = (fill.get("action") or "").lower()
    sign = -1 if action == "buy" else 1
    return sign * int(count) * int(price)


def _write_xlsx(rows: List[dict], out_path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "fills"

    headers = [
        "fill_id",
        "order_id",
        "client_order_id",
        "ticker",
        "side",
        "action",
        "count",
        "price_cents",
        "price_dollars",
        "cash_flow_dollars",
        "is_taker",
        "created_time",
        "ts",
    ]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])

    summary = wb.create_sheet("summary")
    summary.append(["metric", "value"])
    summary.append(["fills", len(rows)])
    summary.append(["contracts_traded", sum(abs(r.get("count", 0) or 0) for r in rows)])
    summary.append(["net_cash_flow_dollars", round(sum(r.get("cash_flow_dollars", 0.0) or 0.0 for r in rows), 4)])
    summary.append(["buy_fills", sum(1 for r in rows if (r.get("action") or "").lower() == "buy")])
    summary.append(["sell_fills", sum(1 for r in rows if (r.get("action") or "").lower() == "sell")])

    summary.append([])
    summary.append(["ticker", "fills", "contracts", "net_cash_flow_dollars"])
    by_ticker: Dict[str, Dict[str, float]] = {}
    for r in rows:
        t = r.get("ticker") or ""
        if t not in by_ticker:
            by_ticker[t] = {"fills": 0, "contracts": 0, "net": 0.0}
        by_ticker[t]["fills"] += 1
        by_ticker[t]["contracts"] += abs(r.get("count", 0) or 0)
        by_ticker[t]["net"] += r.get("cash_flow_dollars", 0.0) or 0.0
    for t, stats in sorted(by_ticker.items()):
        summary.append([t, stats["fills"], stats["contracts"], round(stats["net"], 4)])

    wb.save(out_path)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--key-id", default=os.getenv("KALSHI_ACCESS_KEY", ""), help="Kalshi API key ID (env KALSHI_ACCESS_KEY)")
    p.add_argument(
        "--private-key",
        default=os.getenv("KALSHI_PRIVATE_KEY", ""),
        help="Path to RSA private key PEM (env KALSHI_PRIVATE_KEY)",
    )
    p.add_argument("--min-ts", type=int, default=None, help="Minimum Unix timestamp (seconds)")
    p.add_argument("--max-ts", type=int, default=None, help="Maximum Unix timestamp (seconds)")
    p.add_argument("--min-date", default=None, help="Minimum date YYYY-MM-DD (UTC)")
    p.add_argument("--max-date", default=None, help="Maximum date YYYY-MM-DD (UTC)")
    p.add_argument("--limit", type=int, default=200, help="Page size (1-200, default 200)")
    p.add_argument("--ticker", default=None, help="Exact market ticker filter (optional)")
    p.add_argument("--ticker-prefix", default="KXNCAAWB", help="Ticker prefix filter (default KXNCAAWB)")
    p.add_argument("--out", default="kalshi/ncaaw_fills.xlsx", help="Output XLSX path")
    p.add_argument("--csv-out", default=None, help="Optional CSV output path")
    args = p.parse_args(argv)

    if not args.key_id or not args.private_key:
        print("Missing --key-id or --private-key (or env KALSHI_ACCESS_KEY / KALSHI_PRIVATE_KEY).", file=sys.stderr)
        return 2

    min_ts = args.min_ts
    max_ts = args.max_ts
    if args.min_date:
        min_ts = _date_to_ts(args.min_date, end=False)
    if args.max_date:
        max_ts = _date_to_ts(args.max_date, end=True)

    fills = list(
        iter_fills(
            key_id=args.key_id,
            private_key_path=args.private_key,
            ticker=args.ticker,
            min_ts=min_ts,
            max_ts=max_ts,
            limit=args.limit,
        )
    )

    prefix = (args.ticker_prefix or "").upper()
    if prefix:
        fills = [f for f in fills if (f.get("ticker") or "").upper().startswith(prefix)]

    rows: List[dict] = []
    for f in fills:
        price_cents = _price_cents(f)
        cash_flow_cents = _cash_flow_cents(f)
        rows.append(
            {
                "fill_id": f.get("fill_id") or f.get("trade_id") or "",
                "order_id": f.get("order_id") or "",
                "client_order_id": f.get("client_order_id") or "",
                "ticker": f.get("ticker") or f.get("market_ticker") or "",
                "side": f.get("side") or "",
                "action": f.get("action") or "",
                "count": f.get("count") or 0,
                "price_cents": price_cents if price_cents is not None else "",
                "price_dollars": round((price_cents or 0) / 100.0, 4) if price_cents is not None else "",
                "cash_flow_dollars": round((cash_flow_cents or 0) / 100.0, 4) if cash_flow_cents is not None else "",
                "is_taker": f.get("is_taker") if f.get("is_taker") is not None else "",
                "created_time": f.get("created_time") or "",
                "ts": f.get("ts") or "",
            }
        )

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    _write_xlsx(rows, args.out)
    print(f"Wrote {len(rows)} fills -> {args.out}")

    if args.csv_out:
        out_dir = os.path.dirname(args.csv_out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
            if rows:
                w.writeheader()
                for r in rows:
                    w.writerow(r)
        print(f"Wrote CSV -> {args.csv_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
