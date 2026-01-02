from __future__ import annotations

import argparse
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup, Comment

from config import (
    SCHEDULE_DIR,
    GAME_LINKS_CSV,
    SEASON_START,
)
from utils import parse_any_date

BASE_URL = "https://www.sports-reference.com/cbb/boxscores/index.cgi?month={m}&day={d}&year={y}"
BASE = "https://www.sports-reference.com"

SID_RE = re.compile(r"/cbb/schools/([^/]+)/")


def date_range(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def extract_sid(a_tag):
    if not a_tag:
        return None
    href = a_tag.get("href")
    if not href:
        return None
    m = SID_RE.search(href)
    return m.group(1) if m else None


def infer_gender(game_div):
    classes = set(game_div.get("class", []))
    if "gender-f" in classes:
        return "women"
    if "gender-m" in classes:
        return "men"
    desc = game_div.select_one("td.desc")
    if desc:
        t = desc.get_text(" ", strip=True).lower()
        if "women" in t:
            return "women"
        if "men" in t:
            return "men"
    return None


def extract_game_summary_divs(html: str):
    soup = BeautifulSoup(html, "lxml")
    divs = list(soup.select("div.game_summary"))
    if divs:
        return divs
    # Some pages include summaries in HTML comments; parse those too.
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if "game_summary" not in c:
            continue
        csoup = BeautifulSoup(c, "lxml")
        divs.extend(csoup.select("div.game_summary"))
    return divs


def parse_game_div(game_div, game_date: date):
    gender = infer_gender(game_div)

    w_tr = game_div.select_one("tr.winner")
    l_tr = game_div.select_one("tr.loser")

    winner_sid = extract_sid(w_tr.select_one("a") if w_tr else None)
    loser_sid = extract_sid(l_tr.select_one("a") if l_tr else None)

    box_a = game_div.select_one("td.gamelink a")
    box_href = box_a.get("href") if box_a else None
    box_url = (BASE + box_href) if box_href else None

    return {
        "game_date": game_date.isoformat(),
        "gender": gender,
        "winner_sid": winner_sid,
        "loser_sid": loser_sid,
        "boxscore_href": box_href,
        "boxscore_url": box_url,
    }


def load_existing_game_links(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "game_date",
                "gender",
                "winner_sid",
                "loser_sid",
                "boxscore_href",
                "boxscore_url",
            ]
        )
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return df


def find_start_date(existing: pd.DataFrame) -> date:
    if existing.empty or "game_date" not in existing.columns:
        return SEASON_START
    parsed = existing["game_date"].apply(parse_any_date)
    parsed = parsed[parsed.notna()]
    if parsed.empty:
        return SEASON_START
    return max(parsed) + timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="Update schedule links and game_links.csv.")
    parser.add_argument("--start-date", help="YYYY-MM-DD override for first date to fetch.")
    parser.add_argument("--end-date", help="YYYY-MM-DD override for last date to fetch.")
    parser.add_argument("--requests-per-min", type=int, default=6)
    parser.add_argument("--refetch", action="store_true", help="Re-download even if file exists.")
    args = parser.parse_args()

    existing = load_existing_game_links(GAME_LINKS_CSV)

    if args.start_date:
        start_date = parse_any_date(args.start_date)
        if not start_date:
            raise ValueError(f"Could not parse start date: {args.start_date}")
    else:
        start_date = find_start_date(existing)

    if args.end_date:
        end_date = parse_any_date(args.end_date)
        if not end_date:
            raise ValueError(f"Could not parse end date: {args.end_date}")
    else:
        end_date = date.today() - timedelta(days=1)

    if end_date < start_date:
        print(f"No new dates to fetch ({start_date} > {end_date}).")
        return

    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    delay = 60 / max(args.requests_per_min, 1)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        }
    )

    for d in date_range(start_date, end_date):
        out_path = SCHEDULE_DIR / f"{d.isoformat()}.txt"
        if out_path.exists() and not args.refetch:
            html = out_path.read_text(encoding="utf-8", errors="ignore")
        else:
            url = BASE_URL.format(m=d.month, d=d.day, y=d.year)
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            html = resp.text
            out_path.write_text(html, encoding="utf-8")
            time.sleep(delay)

        game_divs = extract_game_summary_divs(html)
        if not game_divs:
            continue
        for div in game_divs:
            row = parse_game_div(div, d)
            if row["boxscore_url"]:
                rows.append(row)

    if not rows:
        print("No new game links found.")
        return

    new_df = pd.DataFrame(rows)
    combined = pd.concat([existing, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=["boxscore_url"]).reset_index(drop=True)
    combined.to_csv(GAME_LINKS_CSV, index=False)
    print(f"Updated {GAME_LINKS_CSV} with {len(new_df)} new rows.")


if __name__ == "__main__":
    main()
