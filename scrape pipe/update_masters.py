from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from config import BOX_RAW_DIR, MASTER_BOXSCORE_CSV, MASTER_GAMELOG_CSV
from generate_gamelogs_from_boxscores import append_gamelogs_from_boxscores

FNAME_RE = re.compile(r"^(?P<game_id>.+)_(?P<sid>[^_]+)_(?P<typ>basic|advanced)\.csv$", re.IGNORECASE)
DATE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})")

DROP_PLAYER_ROWS = {"Starters", "Reserves"}


def make_unique(cols: list[str]) -> list[str]:
    out, seen = [], {}
    for c in cols:
        c = str(c).strip()
        if c not in seen:
            seen[c] = 0
            out.append(c)
        else:
            seen[c] += 1
            out.append(f"{c}.{seen[c]}")
    return out


def parse_boxscore_meta(fname: str):
    m = FNAME_RE.match(fname)
    if not m:
        return None
    gid = m.group("game_id")
    sid = m.group("sid")
    typ = m.group("typ").lower()
    dm = DATE_RE.match(gid)
    gdate = dm.group("date") if dm else ""
    return gid, gdate, sid, typ


def read_boxscore_csv(path: Path) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, header=1, dtype=str, keep_default_na=False)
        if "MP" in df.columns:
            return df
    except Exception:
        pass
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def clean_boxscore_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = make_unique(df.columns)
    if len(df.columns) == 0:
        return df.iloc[0:0]
    df.rename(columns={df.columns[0]: "player"}, inplace=True)
    df["player"] = df["player"].astype(str).str.strip()
    df = df[~df["player"].isin(DROP_PLAYER_ROWS)]
    df.replace("", pd.NA, inplace=True)
    df.dropna(how="all", inplace=True)
    return df


def update_master_boxscore() -> int:
    if not BOX_RAW_DIR.exists():
        print(f"[boxscore] Missing raw folder: {BOX_RAW_DIR}")
        return 0

    master_ids = set()
    master_cols = []
    master_exists = MASTER_BOXSCORE_CSV.exists() and MASTER_BOXSCORE_CSV.stat().st_size > 0
    if master_exists:
        master_cols = list(pd.read_csv(MASTER_BOXSCORE_CSV, nrows=0).columns)
        if master_cols:
            df_ids = pd.read_csv(MASTER_BOXSCORE_CSV, usecols=["game_id"], dtype=str)
            master_ids = set(df_ids["game_id"].dropna().unique())

    paths = []
    for root, _, files in os.walk(BOX_RAW_DIR):
        for f in files:
            if f.lower().endswith(".csv"):
                meta = parse_boxscore_meta(f)
                if not meta:
                    continue
                gid, _, _, _ = meta
                if gid in master_ids:
                    continue
                paths.append(Path(root) / f)

    if not paths:
        print("[boxscore] No new raw files to append.")
        return 0

    paths.sort()

    gid_to_sids = defaultdict(set)
    union_cols = set()
    for p in paths:
        meta = parse_boxscore_meta(p.name)
        if not meta:
            continue
        gid, _, sid, _ = meta
        gid_to_sids[gid].add(sid)
        try:
            hdr = pd.read_csv(p, header=1, nrows=0).columns
            hdr = list(hdr)
            if hdr:
                hdr[0] = "player"
            for c in make_unique(hdr):
                union_cols.add(c)
        except Exception:
            try:
                hdr = list(pd.read_csv(p, nrows=0).columns)
                if hdr:
                    hdr[0] = "player"
                for c in make_unique(hdr):
                    union_cols.add(c)
            except Exception:
                pass

    if master_cols:
        new_cols = [c for c in sorted(union_cols) if c not in master_cols]
        final_cols = master_cols + new_cols
        if new_cols:
            master_df = pd.read_csv(MASTER_BOXSCORE_CSV, dtype=str, keep_default_na=False)
            for c in new_cols:
                master_df[c] = pd.NA
            master_df = master_df[final_cols]
            master_df.to_csv(MASTER_BOXSCORE_CSV, index=False)
    else:
        meta_cols = ["game_id", "game_date", "team", "opponent", "table_type"]
        data_cols = ["player"] + sorted(c for c in union_cols if c != "player")
        final_cols = meta_cols + data_cols

    rows_written = 0
    for p in paths:
        meta = parse_boxscore_meta(p.name)
        if not meta:
            continue
        gid, gdate, sid, typ = meta
        sids_in_game = sorted(gid_to_sids.get(gid, []))
        opp = ""
        if len(sids_in_game) == 2:
            opp = sids_in_game[1] if sids_in_game[0] == sid else sids_in_game[0]

        try:
            df = read_boxscore_csv(p)
        except Exception:
            continue

        df = clean_boxscore_df(df)
        if df.empty:
            continue

        df.insert(0, "table_type", typ)
        df.insert(0, "opponent", opp)
        df.insert(0, "team", sid)
        df.insert(0, "game_date", gdate)
        df.insert(0, "game_id", gid)

        for c in final_cols:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[final_cols]

        df.to_csv(MASTER_BOXSCORE_CSV, mode="a", index=False, header=not master_exists and rows_written == 0)
        rows_written += len(df)

    print(f"[boxscore] Appended {rows_written} rows to {MASTER_BOXSCORE_CSV}")
    return rows_written


def update_master_gamelog() -> int:
    return append_gamelogs_from_boxscores(
        boxscore_csv=MASTER_BOXSCORE_CSV,
        master_gamelog_csv=MASTER_GAMELOG_CSV,
    )


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Append raw boxscore and gamelog CSVs to master files.")
    parser.add_argument("--boxscore-only", action="store_true")
    parser.add_argument("--gamelog-only", action="store_true")
    args = parser.parse_args(argv)

    run_boxscore = args.boxscore_only or not args.gamelog_only
    run_gamelog = args.gamelog_only or not args.boxscore_only

    if run_boxscore:
        update_master_boxscore()
    if run_gamelog:
        update_master_gamelog()


if __name__ == "__main__":
    main()
