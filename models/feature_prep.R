# Shared feature preparation utilities for win-prob models (women's CBB)

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
})

# Load team totals from master boxscore and construct per-game prior features
# Returns a list with: box_full, box_prior, model_df
build_prior_features <- function(box_csv) {
  stopifnot(file.exists(box_csv))

  load_box_totals <- function(path) {
    raw <- suppressMessages(readr::read_csv(path, show_col_types = FALSE))
    df <- raw %>%
      filter(player == "School Totals", str_to_lower(table_type) == "basic") %>%
      transmute(
        game_id,
        game_date = as.Date(game_date),
        sid = str_trim(team),
        opp_sid = if_else(is.na(opponent) | opponent == "", "no_sid", str_trim(opponent)),
        across(
          .cols = setdiff(names(.), c("game_id","game_date","team","opponent","table_type","player")),
          .fns = ~ suppressWarnings(as.numeric(.x)),
          .names = "tm_{.col}"
        )
      )
    df
  }

  # women's only by suffix on game_id
  box_totals <- load_box_totals(box_csv) %>%
    filter(opp_sid != "no_sid") %>%
    filter(stringr::str_ends(game_id, "_w")) %>%
    distinct(game_id, sid, .keep_all = TRUE)

  # Opponent stats
  opp_stats <- box_totals %>%
    select(game_id, sid, starts_with("tm_")) %>%
    rename(opp_sid = sid) %>%
    rename_with(~ stringr::str_replace(.x, "^tm_", "opp_"), starts_with("tm_")) %>%
    distinct(game_id, opp_sid, .keep_all = TRUE)

  box_full <- box_totals %>%
    left_join(opp_stats, by = c("game_id", "opp_sid")) %>%
    rename_with(~ stringr::str_replace_all(.x, "%", "pct")) %>%
    mutate(win = as.integer(.data[["tm_PTS"]] > .data[["opp_PTS"]])) %>%
    filter(!is.na(win))

  prior_mean <- function(x) {
    s <- cumsum(replace(x, is.na(x), 0))
    n <- cumsum(!is.na(x))
    dplyr::lag(s) / dplyr::lag(n)
  }

  tm_cols  <- names(box_full)[startsWith(names(box_full), "tm_")]
  opp_cols <- names(box_full)[startsWith(names(box_full), "opp_")]

  box_prior <- box_full %>%
    arrange(game_date) %>%
    group_by(sid) %>%
    mutate(
      gp_prior = dplyr::lag(cumsum(rep(1L, dplyr::n()))),
      across(all_of(tm_cols),  prior_mean, .names = "pr_{.col}"),
      across(all_of(opp_cols), prior_mean, .names = "pr_{.col}")
    ) %>% ungroup()

  opp_prior <- box_prior %>%
    select(sid, game_id, gp_prior, starts_with("pr_")) %>%
    rename(opp_gp_prior = gp_prior) %>%
    rename_with(~ paste0("opp_", .x), starts_with("pr_"))

  model_df <- box_prior %>%
    left_join(opp_prior, by = c("opp_sid" = "sid", "game_id" = "game_id")) %>%
    filter(gp_prior >= 1, opp_gp_prior >= 1) %>%
    distinct(game_id, sid, .keep_all = TRUE)

  list(
    box_full = box_full,
    box_prior = box_prior,
    model_df = model_df
  )
}

# Build a single matchup feature row for prediction date using latest priors (< date)
# Returns named numeric vector or data.frame with columns matching pr_* and opp_pr_*
matchup_features_from_priors <- function(prior_df, sid_a, sid_b, cutoff_date) {
  cutoff_date <- as.Date(cutoff_date)
  # latest prior rows for each team prior to cutoff
  latest_a <- prior_df %>% filter(sid == sid_a, game_date < cutoff_date) %>% arrange(desc(game_date)) %>% slice_head(n = 1)
  latest_b <- prior_df %>% filter(sid == sid_b, game_date < cutoff_date) %>% arrange(desc(game_date)) %>% slice_head(n = 1)

  pr_cols <- names(prior_df)[startsWith(names(prior_df), "pr_")]
  a_list <- as.list(rep(NA_real_, length(pr_cols))); names(a_list) <- pr_cols
  b_list <- as.list(rep(NA_real_, length(pr_cols))); names(b_list) <- paste0("opp_", pr_cols)

  if (nrow(latest_a) == 1) {
    vals <- latest_a %>% dplyr::select(all_of(pr_cols)) %>% as.list()
    for (nm in names(vals)) a_list[[nm]] <- suppressWarnings(as.numeric(vals[[nm]]))
  }
  if (nrow(latest_b) == 1) {
    vals <- latest_b %>% dplyr::select(all_of(pr_cols)) %>% as.list()
    for (nm in names(vals)) b_list[[paste0("opp_", nm)]] <- suppressWarnings(as.numeric(vals[[nm]]))
  }

  as.data.frame(as.list(c(a_list, b_list)))
}
