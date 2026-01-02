from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from config import GAMELOG_RAW_DIR, OUTPUT_DIR, SEASON_YEAR, DEFAULT_GENDER

TABLE_ID = "team_game_log"


def init_driver(headless=True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def safe_filename(name: str) -> str:
    keep = "-_.() "
    name = "".join(c for c in name if c.isalnum() or c in keep)
    return name.replace(" ", "_").lower()


def scrape_team_gamelog(driver, team_code: str, gender: str) -> pd.DataFrame | None:
    url = f"https://www.sports-reference.com/cbb/schools/{team_code}/{gender}/{SEASON_YEAR}-gamelogs.html"
    print(f"Fetching {url}")
    driver.get(url)

    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, TABLE_ID)))
    except Exception as e:
        print(f"[WARN] Timed out waiting for table for {team_code}: {e}")
        return None

    html = driver.page_source
    try:
        tables = pd.read_html(html, attrs={"id": TABLE_ID})
        if not tables:
            return None
        return tables[0]
    except ValueError:
        return None


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Scrape team gamelog tables from gamelog_scrape_list.csv.")
    parser.add_argument("--input", default=str(OUTPUT_DIR / "gamelog_scrape_list.csv"))
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--show-browser", dest="headless", action="store_false")
    parser.add_argument("--requests-per-min", type=int, default=6)
    parser.add_argument("--gender", default=DEFAULT_GENDER)
    args = parser.parse_args(argv)

    teams = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    if "sid" not in teams.columns:
        raise ValueError("Input must include a 'sid' column.")

    GAMELOG_RAW_DIR.mkdir(parents=True, exist_ok=True)

    delay_seconds = math.ceil(60 / max(args.requests_per_min, 1))
    driver = init_driver(headless=args.headless)

    try:
        for _, row in teams.iterrows():
            team_code = str(row["sid"]).strip()
            if not team_code:
                continue
            filename = safe_filename(team_code) + ".csv"
            out_path = GAMELOG_RAW_DIR / filename

            df = scrape_team_gamelog(driver, team_code, args.gender)
            if df is not None and not df.empty:
                df.to_csv(out_path, index=False)
                print(f"[OK] Saved {out_path}")
            else:
                print(f"[MISS] No data for {team_code}")

            print(f"Sleeping {delay_seconds}s for rate limit...")
            time.sleep(delay_seconds)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
