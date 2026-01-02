from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from config import OUTPUT_DIR, BOX_RAW_DIR, GAMELOG_RAW_DIR, DEFAULT_GENDER
from utils import game_id_from_boxscore_url

from scrape_boxscores import main as scrape_boxscores_main
from scrape_gamelogs import main as scrape_gamelogs_main


def expected_boxscore_files(row: pd.Series) -> list[Path]:
    url = str(row.get("boxscore_url", "")).strip()
    if not url:
        return []
    gid = game_id_from_boxscore_url(url)
    if not gid:
        return []
    gender = str(row.get("gender", DEFAULT_GENDER)).strip().lower()
    suffix = "_w" if gender.startswith("w") else ""

    files = []
    for sid in [row.get("winner_sid", ""), row.get("loser_sid", "")]:
        sid = str(sid).strip()
        if not sid:
            continue
        files.append(BOX_RAW_DIR / f"{gid}_{sid}_basic.csv")
        files.append(BOX_RAW_DIR / f"{gid}_{sid}_advanced.csv")
    return files


def missing_boxscores(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_rows = []
    for _, row in df.iterrows():
        expected = expected_boxscore_files(row)
        if not expected:
            continue
        if any(not p.exists() for p in expected):
            missing_rows.append(row)
    return pd.DataFrame(missing_rows)


def missing_gamelogs(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "sid" not in df.columns:
        return pd.DataFrame()
    missing_rows = []
    for _, row in df.iterrows():
        sid = str(row.get("sid", "")).strip()
        if not sid:
            continue
        out_path = GAMELOG_RAW_DIR / f"{sid}.csv"
        if not out_path.exists():
            missing_rows.append(row)
    return pd.DataFrame(missing_rows)


def run_with_retries(
    box_list: Path,
    gamelog_list: Path,
    max_rounds: int,
    sleep_between: int,
    headless: bool,
):
    for round_num in range(1, max_rounds + 1):
        box_missing = missing_boxscores(box_list) if box_list.exists() else pd.DataFrame()
        gamelog_missing = missing_gamelogs(gamelog_list) if gamelog_list.exists() else pd.DataFrame()

        if box_missing.empty and gamelog_missing.empty:
            print("All expected files present. Done.")
            return

        if not box_missing.empty:
            tmp_box = OUTPUT_DIR / "_boxscore_scrape_list_retry.csv"
            box_missing.to_csv(tmp_box, index=False)
            print(f"[Round {round_num}] Missing boxscores: {len(box_missing)}. Retrying...")
            scrape_boxscores_main(["--input", str(tmp_box)] + ([] if headless else ["--show-browser"]))

        if not gamelog_missing.empty:
            tmp_gl = OUTPUT_DIR / "_gamelog_scrape_list_retry.csv"
            gamelog_missing.to_csv(tmp_gl, index=False)
            print(f"[Round {round_num}] Missing gamelogs: {len(gamelog_missing)}. Retrying...")
            scrape_gamelogs_main(["--input", str(tmp_gl)] + ([] if headless else ["--show-browser"]))

        if round_num < max_rounds:
            time.sleep(sleep_between)

    print(f"Reached max rounds ({max_rounds}). Some items may still be missing.")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Retry scrapes until all expected files exist.")
    parser.add_argument("--box-list", default=str(OUTPUT_DIR / "boxscore_scrape_list.csv"))
    parser.add_argument("--gamelog-list", default=str(OUTPUT_DIR / "gamelog_scrape_list.csv"))
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--sleep-between", type=int, default=10)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--show-browser", dest="headless", action="store_false")
    args = parser.parse_args(argv)

    run_with_retries(
        Path(args.box_list),
        Path(args.gamelog_list),
        max_rounds=max(args.max_rounds, 1),
        sleep_between=max(args.sleep_between, 0),
        headless=args.headless,
    )


if __name__ == "__main__":
    main()
