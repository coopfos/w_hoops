Models production quickstart

- Train models after updating box scores
  - Command: `Rscript models/train_models.R`
  - Inputs: `2025/master_boxscore.csv`
  - Outputs (saved under `models/artifacts/`): `glm_model.rds`, `xgb_model.rds`, `model_meta.rds`

- Generate predictions for today’s NCAAW games
  - Command: `Rscript models/predict_daily.R --date=YYYY-MM-DD`
  - Defaults: schedule at `2025/future_games.csv`, outputs to `models/outputs/predictions_<date>.csv`
  - Options: `--schedule=/path/to/schedule.csv` and `--out=/path/to/output.csv`

Notes

- The feature pipeline uses team and opponent rolling priors derived from team totals rows in `master_boxscore.csv` and filters women’s games via the `_w` game_id suffix.
- Predictions require teams in the schedule to use the same team slug SIDs as appear in `master_boxscore.csv` (e.g., `connecticut`, `iowa`).
- If a team has no prior games, features are imputed using training means; predictions will still be generated.
- To refresh a larger future schedule, prefer the existing Python in `scrape pipe/update_game_links.py` / notebook in `scrape/` or keep `2025/future_games.csv` updated.

