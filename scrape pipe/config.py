from __future__ import annotations

from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "2025"

SEASON_YEAR = 2025
SEASON_START = date(2025, 11, 1)
DEFAULT_GENDER = "women"

SCHEDULE_DIR = DATA_DIR / "schedule_links"
GAME_LINKS_CSV = DATA_DIR / "game_links.csv"

MASTER_BOXSCORE_CSV = DATA_DIR / "master_boxscore.csv"
BOX_RAW_DIR = DATA_DIR / "box scores raw"

GAMELOG_CLEAN_CSV = DATA_DIR / "gamelog_clean.csv"
GAMELOG_RAW_DIR = DATA_DIR / "gamelogs raw"

OUTPUT_DIR = ROOT / "scrape pipe" / "output"
