from __future__ import annotations

import argparse
import os
import time
from collections import deque
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup, Comment
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from config import BOX_RAW_DIR, OUTPUT_DIR, DEFAULT_GENDER

MAX_RETRIES = 3
PAGELOAD_TIMEOUT_SEC = 90
WAIT_FOR_CONTENT_SEC = 30


def s(x):
    if x is None or (isinstance(x, float) and pd.isna(x)) or pd.isna(x):
        return ""
    return str(x).strip()


def rate_limit(req_times: deque, max_req: int, window_sec: int):
    now = time.time()
    while req_times and (now - req_times[0]) >= window_sec:
        req_times.popleft()
    if len(req_times) >= max_req:
        sleep_for = window_sec - (now - req_times[0]) + 0.05
        time.sleep(max(0, sleep_for))
        now = time.time()
        while req_times and (now - req_times[0]) >= window_sec:
            req_times.popleft()


def game_id_from_url(url: str) -> str:
    p = urlparse(url).path
    base = os.path.basename(p)
    return os.path.splitext(base)[0] or "game"


def init_driver(headless=True):
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.set_page_load_timeout(PAGELOAD_TIMEOUT_SEC)
    return driver


def extract_table_df(html: str, table_id: str):
    soup = BeautifulSoup(html, "lxml")
    tbl = soup.find("table", id=table_id)
    if tbl is not None:
        return pd.read_html(str(tbl))[0]

    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if table_id in c:
            csoup = BeautifulSoup(c, "lxml")
            tbl2 = csoup.find("table", id=table_id)
            if tbl2 is not None:
                return pd.read_html(str(tbl2))[0]
    return None


def fetch_html_with_retries(driver, url: str, gid: str, req_times: deque, max_req: int, window_sec: int):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rate_limit(req_times, max_req, window_sec)
            req_times.append(time.time())
            t0 = time.time()
            driver.get(url)

            try:
                WebDriverWait(driver, WAIT_FOR_CONTENT_SEC).until(
                    EC.presence_of_element_located((By.ID, "content"))
                )
            except Exception:
                pass

            elapsed = time.time() - t0
            if elapsed > 10:
                print(f"[WARN] {gid}: request took {elapsed:.1f}s")
            return driver.page_source

        except TimeoutException as e:
            last_err = e
            print(f"[RETRY] {gid}: page-load timeout (attempt {attempt}/{MAX_RETRIES})")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            time.sleep(min(2**attempt, 8))

        except WebDriverException as e:
            last_err = e
            msg = str(e).lower()
            if ("timeout" in msg) or ("timed out" in msg) or ("read" in msg) or ("disconnected" in msg):
                print(f"[RETRY] {gid}: webdriver error (attempt {attempt}/{MAX_RETRIES})")
                time.sleep(min(2**attempt, 8))
            else:
                print(f"[FAIL] {gid}: non-retryable webdriver error -> {e}")
                return None

    print(f"[SKIP] {gid}: failed after {MAX_RETRIES} retries -> {type(last_err).__name__ if last_err else 'Unknown'}")
    return None


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Scrape boxscore tables from boxscore_scrape_list.csv.")
    parser.add_argument("--input", default=str(OUTPUT_DIR / "boxscore_scrape_list.csv"))
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--show-browser", dest="headless", action="store_false")
    parser.add_argument("--max-requests-per-min", type=int, default=6)
    args = parser.parse_args(argv)

    games = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    required = {"boxscore_url", "winner_sid", "loser_sid"}
    missing_cols = required - set(games.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns in input: {sorted(missing_cols)}")

    if "gender" not in games.columns:
        games["gender"] = DEFAULT_GENDER

    BOX_RAW_DIR.mkdir(parents=True, exist_ok=True)
    req_times = deque()
    driver = init_driver(headless=args.headless)

    try:
        for i, row in games.iterrows():
            url = s(row.get("boxscore_url"))
            if not url:
                continue

            row_game_id = s(row.get("game_id"))
            winner_sid = s(row.get("winner_sid"))
            loser_sid = s(row.get("loser_sid"))
            gender = s(row.get("gender")).lower() or DEFAULT_GENDER

            if not gender.startswith("w"):
                print(f"[SKIP] row {i}: non-women gender '{gender}'")
                continue
            if row_game_id and "_w" not in row_game_id:
                print(f"[SKIP] row {i}: non-women game_id '{row_game_id}'")
                continue

            valid_sids = [sid for sid in [winner_sid, loser_sid] if sid]
            if not valid_sids:
                print(f"[SKIP] row {i}: no valid sids")
                continue

            gid = game_id_from_url(url)
            suffix = "_w"

            table_specs = []
            for sid in valid_sids:
                table_specs.append((f"box-score-basic-{sid}{suffix}", f"{gid}_{sid}_basic.csv"))
                table_specs.append((f"box-score-advanced-{sid}{suffix}", f"{gid}_{sid}_advanced.csv"))

            out_paths = [BOX_RAW_DIR / fn for _, fn in table_specs]
            if out_paths and all(p.exists() for p in out_paths):
                continue

            html = fetch_html_with_retries(
                driver,
                url,
                gid,
                req_times=req_times,
                max_req=max(args.max_requests_per_min, 1),
                window_sec=60,
            )
            if html is None:
                continue

            for table_id, filename in table_specs:
                out_path = BOX_RAW_DIR / filename
                if out_path.exists():
                    continue
                df = extract_table_df(html, table_id)
                if df is None:
                    print(f"[MISS] {gid}: table not found -> #{table_id}")
                    continue
                df.to_csv(out_path, index=False)

            print(f"[OK] {gid} -> wrote {len(table_specs)} tables")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
