from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config import MASTER_BOXSCORE_CSV, MASTER_GAMELOG_CSV
from utils import parse_any_date

ROOT = Path(__file__).resolve().parents[1]
SCHOOL_ID_CSV = ROOT / "school_id.csv"


STAT_MAP = {
    "FG": "fg",
    "FGA": "fga",
    "FG%": "fg_rate",
    "3P": "x3p",
    "3PA": "x3pa",
    "3P%": "x3p_rate",
    "2P": "x2p",
    "2PA": "x2pa",
    "2P%": "x2p_rate",
    "eFG%": "eff_fg",
    "FT": "ft",
    "FTA": "fta",
    "FT%": "ft_rate",
    "ORB": "orb",
    "DRB": "drb",
    "TRB": "trb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TOV": "tov",
    "PF": "pf",
}

DEFAULT_MASTER_COLS = [
    "sid",
    "g_seq",
    "date",
    "loc",
    "opp",
    "type",
    "res",
    "tm_score",
    "opp_score",
    "ot",
    "fg",
    "fga",
    "fg_rate",
    "x3p",
    "x3pa",
    "x3p_rate",
    "x2p",
    "x2pa",
    "x2p_rate",
    "eff_fg",
    "ft",
    "fta",
    "ft_rate",
    "orb",
    "drb",
    "trb",
    "ast",
    "stl",
    "blk",
    "tov",
    "pf",
    "fg_o",
    "fga_o",
    "fg_rate_o",
    "x3p_o",
    "x3pa_o",
    "x3p_rate_o",
    "x2p_o",
    "x2pa_o",
    "x2p_rate_o",
    "eff_fg_o",
    "ft_o",
    "fta_o",
    "ft_rate_o",
    "orb_o",
    "drb_o",
    "trb_o",
    "ast_o",
    "stl_o",
    "blk_o",
    "tov_o",
    "pf_o",
    "opp_sid",
]


def col_or_blank(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series([""] * len(df))


def load_sid_to_school() -> dict[str, str]:
    if not SCHOOL_ID_CSV.exists():
        return {}
    df = pd.read_csv(SCHOOL_ID_CSV, dtype=str, keep_default_na=False)
    if "sid" not in df.columns or "School" not in df.columns:
        return {}
    sid_to_school = {}
    for _, row in df.iterrows():
        sid = str(row.get("sid", "")).strip()
        school = str(row.get("School", "")).strip()
        if sid and school:
            sid_to_school[sid] = school
    return sid_to_school


def parse_score(val: str | int | float | None) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def build_gamelog_from_boxscores(df: pd.DataFrame, sid_to_school: dict[str, str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    for col in ["game_id", "team", "player", "table_type"]:
        if col not in df.columns:
            return pd.DataFrame()

    totals = df[
        (df["player"].astype(str).str.strip() == "School Totals")
        & (df["table_type"].astype(str).str.lower() == "basic")
    ].copy()
    if totals.empty:
        return pd.DataFrame()

    totals["team"] = totals["team"].astype(str).str.strip()
    if "opponent" not in totals.columns:
        totals["opponent"] = ""
    totals["opponent"] = totals["opponent"].astype(str).str.strip()

    game_teams = (
        totals.groupby("game_id")["team"]
        .apply(lambda s: sorted({t for t in s if t}))
        .to_dict()
    )

    def infer_opponent(row: pd.Series) -> str:
        opp = str(row.get("opponent", "")).strip()
        if opp:
            return opp
        teams = game_teams.get(row.get("game_id"), [])
        if len(teams) == 2:
            return teams[1] if teams[0] == row.get("team") else teams[0]
        return ""

    totals["opp_sid"] = totals.apply(infer_opponent, axis=1)
    totals["opp_sid"] = totals["opp_sid"].fillna("").astype(str).str.strip()
    totals.loc[totals["opp_sid"] == "", "opp_sid"] = "no_sid"

    date_source = col_or_blank(totals, "game_date")
    date_source = date_source.where(date_source.astype(str).str.strip() != "", totals["game_id"])
    parsed_dates = date_source.apply(parse_any_date)
    totals = totals[parsed_dates.notna()].copy()
    totals["date"] = parsed_dates[parsed_dates.notna()].apply(lambda d: d.isoformat())

    if totals.empty:
        return pd.DataFrame()

    opp_names = totals["opp_sid"].map(sid_to_school)
    opp_names = opp_names.where(opp_names.notna(), totals["opp_sid"])

    out = pd.DataFrame(
        {
            "game_id": totals["game_id"],
            "sid": totals["team"],
            "g_seq": "",
            "date": totals["date"],
            "loc": "",
            "opp": opp_names,
            "type": "",
            "res": "",
            "tm_score": col_or_blank(totals, "PTS"),
            "ot": "",
            "opp_sid": totals["opp_sid"],
        }
    )

    for box_col, gl_col in STAT_MAP.items():
        out[gl_col] = col_or_blank(totals, box_col)

    opp_stats = totals[["game_id", "team", "PTS"] + list(STAT_MAP.keys())].copy()
    opp_stats.rename(columns={"team": "opp_sid", "PTS": "opp_score"}, inplace=True)
    for box_col, gl_col in STAT_MAP.items():
        opp_stats.rename(columns={box_col: f"{gl_col}_o"}, inplace=True)

    out = out.merge(opp_stats, on=["game_id", "opp_sid"], how="left")

    tm_scores = out["tm_score"].apply(parse_score)
    opp_scores = out["opp_score"].apply(parse_score)
    res_vals = []
    for tm, opp in zip(tm_scores, opp_scores):
        if tm is None or opp is None:
            res_vals.append("")
        elif tm > opp:
            res_vals.append("W")
        elif tm < opp:
            res_vals.append("L")
        else:
            res_vals.append("T")
    out["res"] = res_vals

    return out.drop(columns=["game_id"])


def append_gamelogs_from_boxscores(
    boxscore_csv: Path = MASTER_BOXSCORE_CSV,
    master_gamelog_csv: Path = MASTER_GAMELOG_CSV,
) -> int:
    if not boxscore_csv.exists():
        print(f"[gamelog] Missing master boxscore: {boxscore_csv}")
        return 0

    box_df = pd.read_csv(boxscore_csv, dtype=str, keep_default_na=False)
    sid_to_school = load_sid_to_school()
    out = build_gamelog_from_boxscores(box_df, sid_to_school)
    if out.empty:
        print("[gamelog] No gamelog rows generated from boxscores.")
        return 0

    master_exists = master_gamelog_csv.exists() and master_gamelog_csv.stat().st_size > 0
    master_cols = []
    existing_pairs: set[tuple[str, str]] = set()
    if master_exists:
        master_cols = list(pd.read_csv(master_gamelog_csv, nrows=0).columns)
        if master_cols and "sid" in master_cols and "date" in master_cols:
            df_existing = pd.read_csv(
                master_gamelog_csv, usecols=["sid", "date"], dtype=str, keep_default_na=False
            )
            for _, row in df_existing.iterrows():
                d = parse_any_date(row.get("date", ""))
                if d:
                    existing_pairs.add((row.get("sid", "").strip(), d.isoformat()))

    if not master_cols:
        master_cols = DEFAULT_MASTER_COLS

    out["sid"] = out["sid"].astype(str).str.strip()
    out["date"] = out["date"].astype(str).str.strip()
    keys = list(zip(out["sid"], out["date"]))
    mask = [k not in existing_pairs for k in keys]
    out = out[mask]

    if out.empty:
        print("[gamelog] No new gamelog rows to append.")
        return 0

    for c in master_cols:
        if c not in out.columns:
            out[c] = pd.NA
    out = out[master_cols]

    out.to_csv(master_gamelog_csv, mode="a", index=False, header=not master_exists)
    print(f"[gamelog] Appended {len(out)} rows to {master_gamelog_csv}")
    return len(out)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Generate team gamelogs from master_boxscore and append to master_gamelog."
    )
    parser.add_argument("--boxscore-csv", default=str(MASTER_BOXSCORE_CSV))
    parser.add_argument("--master-gamelog-csv", default=str(MASTER_GAMELOG_CSV))
    args = parser.parse_args(argv)

    append_gamelogs_from_boxscores(
        boxscore_csv=Path(args.boxscore_csv),
        master_gamelog_csv=Path(args.master_gamelog_csv),
    )


if __name__ == "__main__":
    main()
