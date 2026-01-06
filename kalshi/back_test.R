prices <- read.csv('/users/coop/desktop/w_hoops/kalshi/prices.csv')
prices$game_date_local <- ymd(prices$game_date_local)

sid_map <- read.csv('/users/coop/desktop/w_hoops/kalshi/kalshi_sid_map.csv')

prices <- prices %>% 
  select(input_ticker, game_date_local, yes_bid_close_dollars, yes_ask_close_dollars) %>% 
  mutate(k_sid = stringr::str_extract(input_ticker, "(?<=-)[^-]*$")) %>% 
  select(-input_ticker) %>% 
  rename(date = game_date_local,
         bid = yes_bid_close_dollars,
         ask = yes_ask_close_dollars)

prices <- sid_map %>% 
  select(kalshi_code, sid_guess) %>% 
  right_join(prices, by = c('kalshi_code' = 'k_sid'))

prices <- prices %>% 
  filter(!(is.na(ask)))

df$date <- ymd(df$date)

df <- prices %>% 
  select(sid_guess, date, ask) %>% 
  right_join(df, by = c('date', 'sid_guess' = 'sid'))

filt <- df %>% 
  filter((pred_xg - .1) > ask &
           (pred_log - .1) > ask)

buys <- filt %>% 
  mutate(cons = floor(10/ask))

buys <- buys %>% 
  mutate(payoff = ifelse(win == 1, cons, -10))
