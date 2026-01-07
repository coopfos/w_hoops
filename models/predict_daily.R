# Generate daily predictions for NCAAW games using trained models

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(tidyr)
  library(xgboost)
})

args <- commandArgs(trailingOnly = TRUE)

parse_flag <- function(flag, default = NULL) {
  # very small parser: expects --key=value in args
  key <- paste0("--", flag, "=")
  hit <- args[startsWith(args, key)]
  if (length(hit) == 0) return(default)
  sub(key, "", hit[[1]], fixed = TRUE)
}

repo_root <- normalizePath("..")
box_csv <- file.path(repo_root, "2025", "master_boxscore.csv")
future_csv <- file.path(repo_root, "2025", "future_games.csv")
art_dir <- file.path(repo_root, "models", "artifacts")
out_dir <- file.path(repo_root, "models", "outputs")
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

pred_date <- as.Date(parse_flag("date", as.character(Sys.Date())))
out_path  <- parse_flag("out", file.path(out_dir, paste0("predictions_", pred_date, ".csv")))
schedule_path <- parse_flag("schedule", future_csv)

if (!file.exists(box_csv)) stop("Missing box score master: ", box_csv)
if (!file.exists(schedule_path)) stop("Missing future schedule csv: ", schedule_path)
if (!file.exists(file.path(art_dir, "glm_model.rds"))) stop("Missing glm model artifact")
if (!file.exists(file.path(art_dir, "xgb_model.rds"))) stop("Missing xgb model artifact")
if (!file.exists(file.path(art_dir, "model_meta.rds"))) stop("Missing model meta artifact")

source(file.path(repo_root, "models", "feature_prep.R"))

message("[1/4] Loading artifacts and priors (", as.character(pred_date), ")")
glm_fit <- readRDS(file.path(art_dir, "glm_model.rds"))
xgb_fit <- readRDS(file.path(art_dir, "xgb_model.rds"))
meta    <- readRDS(file.path(art_dir, "model_meta.rds"))

pf <- build_prior_features(box_csv)
prior_df <- pf$box_prior

message("[2/4] Reading schedule and filtering to date")
sch <- suppressMessages(readr::read_csv(schedule_path, show_col_types = FALSE))

# Normalize columns from future_games.csv
canon <- sch %>%
  rename_with(~ gsub("\\s+", "_", tolower(.x)))

# expected columns: game_date, team1, team2 (gender present as womens/women)
if (!all(c("game_date","team1","team2") %in% names(canon))) {
  stop("Schedule must include columns: game_date, team1, team2")
}
canon <- canon %>%
  mutate(
    game_date = as.Date(game_date),
    team1 = str_trim(team1),
    team2 = str_trim(team2),
    gender = dplyr::coalesce(.data[["gender"]], .data[["gender"]])
  )

today_games <- canon %>%
  filter(game_date == pred_date) %>%
  # sports-ref sometimes uses "womens"; accept both
  filter(is.na(gender) | gender %in% c("women","womens","female","w")) %>%
  select(game_date, sid_a = team1, sid_b = team2)

if (nrow(today_games) == 0) {
  message("No games found in schedule for ", pred_date)
  invisible(q(status = 0))
}

message("[3/4] Building feature rows for matchups")
feats_list <- lapply(seq_len(nrow(today_games)), function(i) {
  row <- today_games[i,]
  fx <- matchup_features_from_priors(prior_df, row$sid_a, row$sid_b, pred_date)
  # add ids
  fx$game_date <- row$game_date
  fx$sid <- row$sid_a
  fx$opp_sid <- row$sid_b
  fx
})
feat_df <- bind_rows(feats_list)

# Align to training feature set and impute
feature_cols <- meta$feature_cols
for (mc in setdiff(feature_cols, names(feat_df))) {
  feat_df[[mc]] <- NA_real_
}
feat_df <- feat_df[, c("game_date","sid","opp_sid", feature_cols), drop = FALSE]

for (nm in feature_cols) {
  v <- as.numeric(feat_df[[nm]])
  m <- meta$train_means[[nm]]
  if (is.null(m) || is.na(m)) m <- 0
  v[is.na(v)] <- m
  feat_df[[nm]] <- v
}

message("[4/4] Predicting and writing output: ", out_path)

# Logistic regression
glm_probs <- suppressWarnings(as.numeric(stats::predict(glm_fit, newdata = as.data.frame(feat_df[, feature_cols, drop = FALSE]), type = "response")))

# XGBoost
dx <- xgb.DMatrix(data = data.matrix(as.data.frame(feat_df[, feature_cols, drop = FALSE])))
xgb_probs <- as.numeric(predict(xgb_fit, dx))

out <- feat_df %>%
  transmute(
    date = game_date,
    sid, opp_sid,
    model_glm = glm_probs,
    model_xgb = xgb_probs
  )

readr::write_csv(out, out_path)
print(out)

