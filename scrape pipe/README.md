# Scrape Pipe (Daily)

Daily, manual scrape pipeline for new game links, boxscores, and team gamelogs.

## Quick Start (typical daily run)

```bash
python3 "scrape pipe/update_game_links.py"
python3 "scrape pipe/build_scrape_lists.py"
python3 "scrape pipe/scrape_boxscores.py"
python3 "scrape pipe/scrape_gamelogs.py"
```

If timeouts happen, use the retry utility to loop until everything is scraped:

```bash
python3 "scrape pipe/run_until_complete.py"
```

## What Each Step Does

1) `update_game_links.py`
- Fetches new schedule pages (by date) and appends to `2025/game_links.csv`.
- Writes raw schedule HTML into `2025/schedule_links/`.

2) `build_scrape_lists.py`
- Looks at `2025/master_boxscore.csv` and `2025/gamelog_clean.csv`.
- Creates scrape lists for missing games that have already happened.
- Outputs:
  - `scrape pipe/output/boxscore_scrape_list.csv`
  - `scrape pipe/output/gamelog_scrape_list.csv`
  - `scrape pipe/output/gamelog_missing_games.csv`

3) `scrape_boxscores.py`
- Scrapes missing boxscore tables into `2025/box scores raw/`.

4) `scrape_gamelogs.py`
- Scrapes full team gamelog tables into `2025/gamelogs raw/`.

## Useful Options

```bash
python3 "scrape pipe/update_game_links.py" --start-date 2025-11-01 --end-date 2025-11-15
python3 "scrape pipe/build_scrape_lists.py" --through 2025-11-30
python3 "scrape pipe/scrape_boxscores.py" --show-browser
python3 "scrape pipe/scrape_gamelogs.py" --show-browser
python3 "scrape pipe/run_until_complete.py" --max-rounds 10 --sleep-between 15
```

## Notes
- The scrape lists only include games with `game_date <= yesterday` by default.
- `master_boxscore.csv` is used as the source of truth for which game_ids are already present.
- `gamelog_clean.csv` is used as the source of truth for which team-game dates are already present.
