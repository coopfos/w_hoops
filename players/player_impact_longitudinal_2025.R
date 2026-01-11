#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)

pid_path <- if (length(args) >= 1) args[[1]] else "pid_map.csv"
master_path <- if (length(args) >= 2) args[[2]] else file.path("..", "2025", "master_boxscore.csv")
output_path <- if (length(args) >= 3) args[[3]] else "player_impact_longitudinal_2025.csv"

if (!file.exists(pid_path)) {
  stop(sprintf("Missing pid mapping: %s", pid_path))
}
if (!file.exists(master_path)) {
  stop(sprintf("Missing master boxscore: %s", master_path))
}

parse_num <- function(x) {
  if (is.numeric(x)) return(x)
  as.numeric(gsub("[^0-9.-]", "", x))
}

pid_map <- read.csv(pid_path, stringsAsFactors = FALSE)
box <- read.csv(master_path, stringsAsFactors = FALSE)

# Attach pid by team + player
key_map <- paste(pid_map$team, pid_map$player, sep = "||")
key_box <- paste(box$team, box$player, sep = "||")
box$pid <- pid_map$pid[match(key_box, key_map)]

# Use basic rows when available
impact_source <- box
if ("table_type" %in% names(box)) {
  basic_rows <- box[box$table_type == "basic", ]
  if (nrow(basic_rows) > 0) {
    impact_source <- basic_rows
  }
}

impact_cols <- c("MP", "PTS", "TRB", "AST", "STL", "BLK", "TOV")
missing_cols <- setdiff(impact_cols, names(impact_source))
if (length(missing_cols) > 0) {
  stop(sprintf("Missing columns in boxscore: %s", paste(missing_cols, collapse = ", ")))
}

for (col in impact_cols) {
  impact_source[[col]] <- parse_num(impact_source[[col]])
}

if (!all(c("game_id", "game_date", "team", "player") %in% names(impact_source))) {
  stop("Expected columns game_id, game_date, team, player in boxscore.")
}

# Per-game player totals (for games where player appears)
per_game_player <- aggregate(
  impact_source[impact_cols],
  by = list(
    game_id = impact_source$game_id,
    game_date = impact_source$game_date,
    team = impact_source$team,
    player = impact_source$player,
    pid = impact_source$pid
  ),
  FUN = sum,
  na.rm = TRUE
)

# Team games list
team_games <- unique(impact_source[, c("game_id", "game_date", "team")])
team_games <- team_games[order(team_games$team, team_games$game_date, team_games$game_id), ]

# Ensure every pid for a team is included for each team game
pid_by_team <- pid_map[, c("team", "player", "pid")]

# Expand: each team game x every pid on the team
expanded <- merge(
  team_games,
  pid_by_team,
  by = "team",
  all.x = TRUE,
  sort = FALSE
)

# Merge per-game stats (missing => did not appear)
master_df <- merge(
  expanded,
  per_game_player,
  by = c("game_id", "game_date", "team", "player", "pid"),
  all.x = TRUE,
  sort = FALSE
)

for (col in impact_cols) {
  master_df[[col]][is.na(master_df[[col]])] <- 0
}

# Team totals per game
team_totals <- aggregate(
  master_df[impact_cols],
  by = list(team = master_df$team, game_id = master_df$game_id, game_date = master_df$game_date),
  FUN = sum,
  na.rm = TRUE
)

master_df <- merge(
  master_df,
  team_totals,
  by = c("team", "game_id", "game_date"),
  suffixes = c("", "_team"),
  all.x = TRUE,
  sort = FALSE
)

share <- function(x, denom) ifelse(denom > 0, x / denom, NA_real_)

master_df$mp_share <- share(master_df$MP, master_df$MP_team)
master_df$pts_share <- share(master_df$PTS, master_df$PTS_team)
master_df$trb_share <- share(master_df$TRB, master_df$TRB_team)
master_df$ast_share <- share(master_df$AST, master_df$AST_team)
master_df$stl_share <- share(master_df$STL, master_df$STL_team)
master_df$blk_share <- share(master_df$BLK, master_df$BLK_team)
master_df$tov_share <- share(master_df$TOV, master_df$TOV_team)

# Impact score: minutes + scoring + playmaking/rebounding + defensive events - turnovers
master_df$impact_score <- (
  0.45 * master_df$mp_share +
    0.25 * master_df$pts_share +
    0.10 * master_df$trb_share +
    0.10 * master_df$ast_share +
    0.05 * master_df$stl_share +
    0.05 * master_df$blk_share -
    0.05 * master_df$tov_share
)

# Keep columns tidy
keep_cols <- c(
  "game_id", "game_date", "team", "player", "pid",
  impact_cols,
  paste0(impact_cols, "_team"),
  "mp_share", "pts_share", "trb_share", "ast_share", "stl_share", "blk_share", "tov_share",
  "impact_score"
)

keep_cols <- keep_cols[keep_cols %in% names(master_df)]
master_df <- master_df[, keep_cols]

master_df <- master_df[order(master_df$team, master_df$pid, master_df$game_date, master_df$game_id), ]

write.csv(master_df, output_path, row.names = FALSE)
message(sprintf("Wrote %s", output_path))
