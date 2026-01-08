cand <- read.csv('/users/coop/desktop/w_hoops/kalshi/today_candles.csv')

preds <- read.csv('/users/coop/desktop/w_hoops/models/outputs/predictions_2026-01-08.csv')

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

cand <- cand %>% 
  mutate(buy = ifelse((model_glm - .1) > yes_ask_close_dollars &
                        (model_xgb - .1) > yes_ask_close_dollars,1,0))
