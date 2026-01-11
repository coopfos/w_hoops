# Kelly sizing + MOS notes

- Using historical prices in `codex/historical_prices.csv` with rolling model predictions, the earliest statistically safe MOS found (95% CI lower bound > 0) was for XGBoost only at ~0.14 edge. LogReg had no MOS in 0.00–0.25 that cleared this test.
- Combined filter (both models must clear same MOS) did not produce a positive lower 95% CI across 0.00–0.50 with the current sample (447 matched observations).
- Adopted XGBoost-only rule: buy if `edge_xgb = model_xgb - ask >= 0.14`.
- Kelly sizing function used (fractional Kelly + cap):
  - `f* = (p - q) / (1 - q)`
  - `f = clamp(kelly_scale * f*, 0, max_fraction)`
  - `stake = bankroll * f`, `contracts = floor(stake / q)`
- In `kalshi/buy_find.R`, kelly defaults were `kelly_scale = 0.5`, `max_fraction = 0.05`, `bankroll = 1000`.
- Observed issue: sum of stakes can exceed bankroll when many bets qualify (per-bet cap only); all Kelly values can match if all bets hit the cap.
- Recommendation: add portfolio-level scaling (e.g., total fraction cap) if needed.
