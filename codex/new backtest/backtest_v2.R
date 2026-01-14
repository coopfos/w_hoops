library(dplyr)

preds <- read.csv("/Users/coop/Desktop/w_hoops/codex/new backtest/backtest_xgb_preds_2025_1120_1231_v2.csv")
prices <- read.csv("/Users/coop/Desktop/w_hoops/codex/historical_prices.csv")

comp <- preds %>%
  select(date, sid, pred) %>%
  right_join(prices, by = c("date", "sid"))

size_order <- function(p, q, bankroll, mos = 0.14,
                       kelly_scale = 0.5, max_fraction = 0.05) {
  edge <- p - q
  if (is.na(edge) || edge < mos) return(list(contracts = 0, stake = 0, f = 0))
  f_star <- edge / (1 - q)
  f <- max(0, min(kelly_scale * f_star, max_fraction))
  stake <- bankroll * f
  contracts <- floor(stake / q)
  list(contracts = contracts, stake = stake, f = f)
}

bankroll_start <- 1000
kelly_scale <- 0.5
max_fraction <- 0.05
mos <- 0.15

gl <- read.csv("/users/coop/desktop/w_hoops/2025/master_gamelog.csv")

gl_filt <- gl %>%
  filter(!(opp == "no_sid"))

res <- gl_filt %>%
  select(date, sid, opp, res) %>%
  mutate(win = ifelse(res == "W", 1, 0)) %>%
  select(-res)

test <- res %>%
  right_join(comp, by = c("date", "sid"))

# Daily bankroll update loop
dates <- sort(unique(test$date))
bankroll <- bankroll_start
daily_positions <- list()

for (d in dates) {
  day_rows <- test %>% filter(date == d)
  if (nrow(day_rows) == 0) next

  day_rows <- day_rows %>%
    mutate(
      ask = as.numeric(ask),
      edge_xgb = pred - ask
    )

  sized <- lapply(seq_len(nrow(day_rows)), function(i) {
    row <- day_rows[i, ]
    size_order(
      p = as.numeric(row$pred),
      q = as.numeric(row$ask),
      bankroll = bankroll,
      mos = mos,
      kelly_scale = kelly_scale,
      max_fraction = max_fraction
    )
  })

  day_rows$kelly <- vapply(sized, function(x) x$f, numeric(1))
  day_rows$stake <- vapply(sized, function(x) x$stake, numeric(1))
  day_rows$contracts <- vapply(sized, function(x) x$contracts, numeric(1))
  day_rows$buy <- ifelse(day_rows$stake > 0, 1, 0)
  day_rows$payoff <- ifelse(day_rows$win == 1, (day_rows$contracts - day_rows$stake), (day_rows$stake * -1))

  bankroll <- bankroll + sum(day_rows$payoff, na.rm = TRUE)
  day_rows$bankroll_start <- bankroll - sum(day_rows$payoff, na.rm = TRUE)
  day_rows$bankroll_end <- bankroll

  daily_positions[[as.character(d)]] <- day_rows
}

test <- bind_rows(daily_positions) %>%
  filter(stake > 0)
