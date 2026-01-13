library(dplyr)
library(stringr)

cand <- read.csv('/users/coop/desktop/w_hoops/kalshi/today_candles.csv')

preds <- read.csv('/users/coop/desktop/w_hoops/models/outputs/predictions_2026-01-14.csv')

sid_map <- read.csv('/users/coop/desktop/w_hoops/kalshi/kalshi_sid_map.csv')

cand <- cand %>%
  select(ticker, yes_bid_close_dollars, yes_ask_close_dollars) %>% 
  mutate(k_sid = stringr::str_extract(ticker, "(?<=-)[^-]*$"))

cand <- sid_map %>% 
  select(sid_guess, kalshi_code) %>% 
  right_join(cand, by = c('kalshi_code' = 'k_sid'))

cand <- preds %>%
  select(sid, model_glm, model_xgb) %>% 
  right_join(cand, by = c('sid' = 'sid_guess'))

size_order <- function(p, q, bankroll, mos = 0.15,
                       kelly_scale = 0.5, max_fraction = 0.05) {
  edge <- p - q
  if (is.na(edge) || edge < mos) return(list(contracts = 0, stake = 0, f = 0))
  f_star <- edge / (1 - q)
  f <- max(0, min(kelly_scale * f_star, max_fraction))
  stake <- bankroll * f
  contracts <- floor(stake / q)
  list(contracts = contracts, stake = stake, f = f)
}

bankroll <- 250

cand <- cand %>%
  mutate(
    ask = as.numeric(yes_ask_close_dollars),
    edge_xgb = model_xgb - ask,
    buy = ifelse(edge_xgb >= 0.15, 1, 0),
    kelly = ifelse(
      buy == 1,
      pmin(0.05, 0.5 * (edge_xgb / (1 - ask))),
      0
    ),
    stake = bankroll * kelly,
    contracts = floor(stake / ask)
  )

write.csv(cand, '/users/coop/desktop/w_hoops/kalshi/today_buys.csv', row.names = F)
