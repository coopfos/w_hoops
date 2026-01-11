args <- commandArgs(trailingOnly = TRUE)

input_path <- if (length(args) >= 1) args[[1]] else "players/unique.csv"
output_path <- if (length(args) >= 2) args[[2]] else "players/unique_with_pid.csv"

if (!file.exists(input_path)) {
  stop(sprintf("Input file not found: %s", input_path))
}

df <- read.csv(input_path, stringsAsFactors = FALSE)

if (!("sid" %in% names(df)) && !("team" %in% names(df))) {
  stop("Expected a 'sid' or 'team' column in the input CSV.")
}

sid <- if ("sid" %in% names(df)) df$sid else df$team
sid <- tolower(trimws(sid))

if (!("player" %in% names(df))) {
  stop("Expected a 'player' column in the input CSV.")
}

player_alpha <- gsub("[^A-Za-z]", "", df$player)
player_alpha <- tolower(player_alpha)
player_key <- substr(player_alpha, 1, 4)

# Sequence within team + player_key groups, in original row order.
grp <- interaction(sid, player_key, drop = TRUE, lex.order = TRUE)
seq_in_grp <- ave(seq_along(player_key), grp, FUN = seq_along)

pid <- paste0(sid, "_", player_key, seq_in_grp)

df$pid <- pid

write.csv(df, output_path, row.names = FALSE)
message(sprintf("Wrote %s", output_path))
