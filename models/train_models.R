# Train logistic regression and xgboost models for women's CBB win probability
# Uses master boxscore at 2025/master_boxscore.csv and saves artifacts to models/artifacts

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
  library(stringr)
  library(xgboost)
})

args <- commandArgs(trailingOnly = TRUE)
repo_root <- normalizePath("..")
box_csv <- file.path(repo_root, "2025", "master_boxscore.csv")
art_dir <- file.path(repo_root, "models", "artifacts")
dir.create(art_dir, showWarnings = FALSE, recursive = TRUE)

source(file.path(repo_root, "models", "feature_prep.R"))

message("[1/4] Building prior features from ", box_csv)
pf <- build_prior_features(box_csv)
m_df <- pf$model_df

# Select numeric, prior-derived feature columns only
drop_cols <- c("game_id","game_date","sid","opp_sid","win","gp_prior","opp_gp_prior")
num_cols <- names(m_df)[vapply(m_df, is.numeric, logical(1))]
feature_cols <- setdiff(num_cols, drop_cols)
feature_cols <- feature_cols[grepl("^pr_|^opp_pr_", feature_cols)]
stopifnot(length(feature_cols) > 0)

# Train set (all rows available with priors)
train_x <- as.data.frame(m_df[, feature_cols, drop = FALSE])
train_y <- m_df$win

# Mean imputation using training means
train_means <- vapply(train_x, function(x) mean(as.numeric(x), na.rm = TRUE), numeric(1))
train_means[is.na(train_means)] <- 0
for (nm in names(train_x)) {
  v <- as.numeric(train_x[[nm]]); v[is.na(v)] <- train_means[[nm]]; train_x[[nm]] <- v
}

message("[2/4] Training logistic regression (glm)")
glm_df <- cbind.data.frame(win = train_y, train_x)
glm_formula <- as.formula(paste("win ~", paste(colnames(train_x), collapse = " + ")))
glm_fit <- glm(glm_formula, data = glm_df, family = binomial())

message("[3/4] Training XGBoost")
dtrain <- xgb.DMatrix(data = data.matrix(train_x), label = train_y, missing = NA)
params <- list(
  objective = "binary:logistic",
  eval_metric = c("logloss", "auc"),
  max_depth = 5,
  eta = 0.05,
  min_child_weight = 5,
  subsample = 0.8,
  colsample_bytree = 0.8
)
set.seed(42)
xgb_fit <- xgb.train(
  params = params,
  data = dtrain,
  nrounds = 300,
  early_stopping_rounds = 15,
  verbose = 0
)

message("[4/4] Saving artifacts")
meta <- list(
  feature_cols = feature_cols,
  train_means = train_means,
  trained_at = Sys.time()
)

saveRDS(glm_fit, file = file.path(art_dir, "glm_model.rds"))
saveRDS(xgb_fit, file = file.path(art_dir, "xgb_model.rds"))
saveRDS(meta,    file = file.path(art_dir, "model_meta.rds"))

message("Artifacts written to ", art_dir)

