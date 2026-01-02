from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd

from config import (
    GAME_LINKS_CSV,
    MASTER_BOXSCORE_CSV,
    GAMELOG_CLEAN_CSV,
    OUTPUT_DIR,
)
from utils import parse_any_date, game_id_from_boxscore_url


def load_game_links() -> pd.DataFrame:
    if not GAME_LINKS_CSV.exists():
        raise FileNotFoundError(f"Missing {GAME_LINKS_CSV}")
    df = pd.read_csv(GAME_LINKS_CSV, dtype=str, keep_default_na=False)
    if "game_date" not in df.columns:
        raise ValueError("game_links.csv missing game_date column.")
    df["game_date_parsed"] = df["game_date"].apply(parse_any_date)
    df = df[df["game_date_parsed"].notna()].copy()
    return df


def load_master_boxscore_ids() -> set[str]:
    if not MASTER_BOXSCORE_CSV.exists():
        return set()
    df = pd.read_csv(MASTER_BOXSCORE_CSV, usecols=["game_id"], dtype=str)
    return set(df["game_id"].dropna().unique())


def load_gamelog_pairs() -> set[tuple[str, date]]:
    if not GAMELOG_CLEAN_CSV.exists():
        return set()
    df = pd.read_csv(GAMELOG_CLEAN_CSV, dtype=str, keep_default_na=False)
    if "sid" not in df.columns or "date" not in df.columns:
        return set()
    df["date_parsed"] = df["date"].apply(parse_any_date)
    df = df[df["date_parsed"].notna()].copy()
    return set(zip(df["sid"], df["date_parsed"]))


def build_boxscore_scrape_list(games: pd.DataFrame, cutoff: date) -> pd.DataFrame:
    master_ids = load_master_boxscore_ids()
    rows = []
    for _, row in games.iterrows():
        gdate = row["game_date_parsed"]
        if gdate > cutoff:
            continue
        gid = game_id_from_boxscore_url(row.get("boxscore_url", ""))
        if not gid:
            continue
        if gid in master_ids:
            continue
        rows.append(
            {
                "game_id": gid,
                "game_date": gdate.isoformat(),
                "gender": row.get("gender", ""),
                "winner_sid": row.get("winner_sid", ""),
                "loser_sid": row.get("loser_sid", ""),
                "boxscore_url": row.get("boxscore_url", ""),
            }
        )
    return pd.DataFrame(rows)


def build_gamelog_scrape_list(games: pd.DataFrame, cutoff: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    existing_pairs = load_gamelog_pairs()
    missing_rows = []
    for _, row in games.iterrows():
        gdate = row["game_date_parsed"]
        if gdate > cutoff:
            continue
        for sid_col in ["winner_sid", "loser_sid"]:
            sid = (row.get(sid_col) or "").strip()
            if not sid:
                continue
            if (sid, gdate) not in existing_pairs:
                missing_rows.append({"sid": sid, "game_date": gdate.isoformat()})

    if not missing_rows:
        return pd.DataFrame(), pd.DataFrame()

    missing_df = pd.DataFrame(missing_rows).drop_duplicates()

    if GAMELOG_CLEAN_CSV.exists():
        gamelog_df = pd.read_csv(GAMELOG_CLEAN_CSV, dtype=str, keep_default_na=False)
        gamelog_df["date_parsed"] = gamelog_df["date"].apply(parse_any_date)
        last_dates = (
            gamelog_df[gamelog_df["date_parsed"].notna()]
            .groupby("sid")["date_parsed"]
            .max()
            .rename("last_gamelog_date")
        )
    else:
        last_dates = pd.Series(dtype=object)

    summary = (
        missing_df.groupby("sid")["game_date"]
        .agg(["min", "max", "count"])
        .rename(columns={"min": "min_missing_date", "max": "max_missing_date", "count": "missing_games"})
        .reset_index()
    )
    summary["last_gamelog_date"] = summary["sid"].map(last_dates)
    summary = summary[
        ["sid", "last_gamelog_date", "min_missing_date", "max_missing_date", "missing_games"]
    ]

    return summary, missing_df


def main():
    parser = argparse.ArgumentParser(description="Build scrape lists for boxscores and gamelogs.")
    parser.add_argument("--through", help="YYYY-MM-DD override for cutoff date (defaults to yesterday).")
    args = parser.parse_args()

    cutoff = parse_any_date(args.through) if args.through else (date.today() - timedelta(days=1))
    if not cutoff:
        raise ValueError(f"Could not parse --through date: {args.through}")

    games = load_game_links()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    box_list = build_boxscore_scrape_list(games, cutoff)
    box_path = OUTPUT_DIR / "boxscore_scrape_list.csv"
    box_list.to_csv(box_path, index=False)

    gamelog_summary, gamelog_missing = build_gamelog_scrape_list(games, cutoff)
    gamelog_summary_path = OUTPUT_DIR / "gamelog_scrape_list.csv"
    gamelog_summary.to_csv(gamelog_summary_path, index=False)

    gamelog_missing_path = OUTPUT_DIR / "gamelog_missing_games.csv"
    gamelog_missing.to_csv(gamelog_missing_path, index=False)

    print(f"Boxscore scrape list: {box_path} ({len(box_list)} rows)")
    print(f"Gamelog scrape list: {gamelog_summary_path} ({len(gamelog_summary)} teams)")
    print(f"Gamelog missing games: {gamelog_missing_path} ({len(gamelog_missing)} rows)")


if __name__ == "__main__":
    main()
