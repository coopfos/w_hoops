For modeling and analytics purposes, use the R language, and produce .R or .rmd files for me to review steps in model build process. Output data in csv form, always using row.names = False when using the write.csv() command in R.

The rough structure of this repo is as follows:

main_data contains large aggregated datasets. This will contain the best and cleanest data sources for model building.

starters is currently a work-in-progress data scrape for future modeling efforts, it can be disregarded for now

gamelogs is the raw scrape if individual team box scores. This data has been binded and cleaned and appears in the main_data folder.

scrape contains python logic for scraping data off the sports-reference website.

miscellaneous csv files contain things like school_id (sid) codes, and summary statistics for the 2024-2025 NCAA womens basketball season.
