library(dplyr)
library(stringr)

bs <- read.csv('/Users/coop/Desktop/w_hoops/2024/master_boxscore.csv')

abc <- bs %>% 
  filter(team == "abilene-christian")

abc_ru <- abc %>%
  filter(!(player == "School Totals")) %>% 
  filter(table_type == "basic") %>% 
  group_by(game_id, team) %>% 
  summarise(pts = sum(PTS))

new_gl <- bs %>% 
  filter(player == "School Totals")
