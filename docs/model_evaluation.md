# Model Evaluation — NextGen TradeBot

**Evaluation date:** 2026-06-07
**Data window:** 2019-01-01 → 2026-06-07 (retrained on current data)
**Universe:** DOW 30 (US, 29 tradable tickers) + EGX 30 (Egypt, 21 tickers)
**Author:** GP2 — Nile University

---

## 1. Purpose and headline finding

This chapter evaluates whether the system's machine-learning and reinforcement-learning
models produce a **genuine, out-of-sample directional edge** on US and Egyptian equities,
using a leakage-controlled walk-forward protocol retrained through the present day.

> **Headline result.** Out-of-sample directional predictability sits at the
> **market-efficiency ceiling (~0.51–0.52 AUC)**. Reinforcement-learning agents that
> achieve strong *in-sample* Sharpe ratios (1.2–2.8) **fail to generalise**, producing
> **negative returns on genuinely unseen 2026 data**. The system's demonstrable value is
> therefore **risk-adjusted ensemble weighting and risk control**, not raw alpha.

This is a deliberately honest, falsifiable result. It is consistent with the Efficient
Market Hypothesis (Fama, 1970) and with the modern backtesting-protocol literature
(Arnott, Harvey & Markowitz, 2019), which warns that in-sample performance is not
evidence of a real edge.

---

## 2. Methodology

### 2.1 Data and features
- **Sources:** Yahoo Finance OHLCV; `^VIX` for US regime context.
- **Feature set:** 25 engineered features (MACD, RSI-14/30, Bollinger, SMA-30/60,
  CCI-30, DX-30, ATR-14, volume z-score, momentum 5d/20d, fractional differentiation
  d=0.4, Mahalanobis turbulence, VIX level/z-score, 52-week position, cross-sectional
  momentum rank, etc.). VIX features are US-only (EGX set to 0).
- **Rows after engineering:** US 53,510 (29 tickers); EGX 36,568 (21 tickers).

### 2.2 Labelling — triple-barrier (López de Prado, 2018)
The naive *k*-day sign target was replaced with **volatility-scaled triple-barrier
labelling** (horizon = 20 days, barrier multiple *k* = 2.0σ). A row is labelled +1 if the
upper barrier is hit first, 0 if the lower barrier is hit first, else the sign at expiry.
This produces an economically meaningful, balanced target (up-rate ≈ 0.54).

### 2.3 Walk-forward protocol (no leakage)
- **64 walk-forward folds:** 12-month train, 1-month test, rolling.
- **20-day embargo** between train and test (matches the label horizon) to prevent
  look-ahead through overlapping labels.
- **Out-of-fold (OOF) predictions only:** every prediction used to train the meta-learner
  was produced by a base model that did **not** train on that row.
- **LSTM scaler fit on the training fold only**; XGBoost requires no scaler.
- **6 automated leakage checks** pass on every fold (temporal boundary, no future-price
  columns, target excluded from features, row-count sanity, causal feature registry,
  backward-only construction).

### 2.4 RL training — 3-checkpoint expanding window
RL agents are validated on a **forward-chaining** design so that each signal window is
strictly unseen:

| Checkpoint | Train window | Out-of-sample signal window |
|-----------:|--------------|------------------------------|
| Ckpt 1 | 2019-01-01 → 2023-12-31 | 2024 |
| Ckpt 2 | 2019-01-01 → 2024-12-31 | 2025 |
| **Ckpt 3 (live model)** | 2019-01-01 → 2025-12-31 | **2026-01-01 → 2026-06-07** |

Algorithms: PPO, A2C, DDPG, TD3, SAC (Stable-Baselines3) in an identical FinRL
`StockTradingEnv`. Transaction costs: 0.1% fee + Almgren-Chriss square-root slippage.

---

## 3. Results

### 3.1 The in-sample / out-of-sample gap (the core evidence)

The table below contrasts each RL agent's **in-sample training Sharpe** (ckpt 3 training
period) with its performance on the **genuinely unseen 2026 window**.

| Model (ckpt 3) | In-sample train Sharpe | In-sample MaxDD | **2026 OOS return** | **2026 OOS Sharpe** |
|----------------|-----------------------:|----------------:|--------------------:|--------------------:|
| PPO  | 1.65 | −26.4% | **−0.04%** | **+0.12** |
| A2C  | 1.23 | −16.2% | **−2.35%** | **−0.38** |
| DDPG | 1.19 | −16.4% | **−0.71%** | **−0.09** |
| TD3  | 1.27 | −16.0% | **−2.77%** | **−0.58** |
| SAC  | 1.58 | −26.7% | **−4.46%** | **−0.67** |

**Interpretation.** SAC's in-sample episodes reached terminal equity > $5.8M (≈ +480%) at
Sharpe ≈ 1.0, yet the same policy **lost 4.46%** on 2026 data. This divergence is the
textbook signature of **overfitting / in-sample memorisation**, not a tradable edge.
Every agent under-performed cash out-of-sample except PPO, which was statistically flat.

> ⚠️ **Methodological warning for the reader.** The Step-4 summary table prints
> *in-sample* Sharpe ratios (1.1–2.8). These are **not** evidence of profitability and
> must not be reported as live performance. The only trustworthy numbers are the OOS
> columns above and the meta-learner validation in §3.3.

### 3.2 Base-learner out-of-sample discrimination

OOF predictions over the full walk-forward period (2021-01-04 → 2026-05-01, 64,721 rows,
50 tickers), scored against triple-barrier ground truth:

| Base model | OOF AUC | Accuracy | Brier |
|------------|--------:|---------:|------:|
| XGBoost | 0.509 | 0.506 | 0.317 |
| LSTM    | 0.515 | 0.507 | 0.368 |

Both sit a fraction above the 0.50 coin-flip line — i.e. **no economically meaningful
directional skill** on unseen data.

### 3.3 Meta-learner (stacking ensemble)

Trained on merged OOF predictions (63,898 rows; time-ordered 70/30 split; logistic
regression, *C* = 1.0; StandardScaler fit on train only):

| Metric | Value |
|--------|------:|
| Validation AUC | **0.524** |
| Validation accuracy | 0.536 |
| Brier score | 0.249 |
| n train / n val | 44,728 / 19,170 |

**Learned fusion weights** (normalised \|coefficient\|) — the data-driven replacement for
hand-coded fusion weights:

| Signal | Weight |
|--------|------:|
| LSTM | 0.221 |
| A2C  | 0.221 |
| TD3  | 0.188 |
| PPO  | 0.187 |
| DDPG | 0.143 |
| SAC  | 0.030 |
| XGBoost | 0.011 |

The meta-learner (0.524 AUC) edges the best base learner (0.515) — a small but
**consistent** improvement from combining decorrelated signals, exactly the benefit
predicted by stacked generalisation (Wolpert, 1992). It does **not**, however, lift
predictability off the efficiency ceiling.

### 3.4 Adaptive EWMA weights (Hedge algorithm)

Daily EWMA performance tracking (λ = 0.94) over 1,584 trading dates converges to
near-uniform weights, confirming that **no single model dominates out-of-sample**:

| Model | Final weight |
|-------|------:|
| XGBoost | 18.5% |
| LSTM | 17.2% |
| SAC | 13.8% |
| DDPG | 13.6% |
| TD3 | 12.5% |
| PPO | 12.3% |
| A2C | 12.1% |

Top model: XGBoost — but only marginally, and the ranking is unstable over time.

### 3.5 In-sample return vs buy-and-hold (context only)

For completeness, each algorithm's final-checkpoint cumulative return vs buy-and-hold
**within its (in-sample) checkpoint window**. These are bull-market, in-sample figures and
are reported only to characterise behaviour, not to claim a live edge:

| Algo | In-sample return | vs B&H |
|------|-----------------:|-------:|
| PPO | 62.3% | +34.2% |
| SAC | 58.7% | +30.7% |
| A2C | 28.4% | +0.4% |
| TD3 | 28.4% | +0.3% |
| DDPG | 26.4% | −1.7% |

---

## 4. Discussion

1. **Market efficiency holds on this universe.** Across XGBoost, LSTM, five RL agents,
   and a meta-learner, out-of-sample AUC never exceeds ~0.52. Daily/20-day direction on
   liquid DOW 30 and EGX names is, to first order, unpredictable from price-derived
   features — the expected result under weak-form efficiency.

2. **In-sample Sharpe is dangerously misleading.** RL agents reached Sharpe 1.5–2.8 in
   sample and still lost money out-of-sample. Any evaluation that stops at the training
   curve would have reported a "profitable" system that does not exist. This is the single
   most important methodological lesson of the project.

3. **Where the system genuinely adds value:**
   - *Data-driven fusion* (meta-learner) beats hand-coded weights and the best single
     model on validation AUC, however slightly.
   - *Risk control* — turbulence hard-filter, 15% drawdown kill-switch, 2% cash buffer,
     Platt-calibrated confidence — bounds downside regardless of weak predictive signal.
   - *Explainability* — SHAP attributions and regime context make every signal auditable,
     which is the actual product (decision support), not a profit guarantee.

4. **Retraining freshens, it does not create alpha.** Moving the data window from 2023 to
   2026 removed staleness and confirmed the efficiency finding on the most recent data.
   It did not, and theoretically cannot, manufacture an edge the market does not concede.

---

## 5. Limitations

- **Feature scope:** price/volume-derived features only. No live news sentiment
  (FinBERT/AraBERT integrated but fed as 0 in this run), no fundamentals, no order-book or
  alternative data.
- **Daily frequency:** intraday microstructure (where short-horizon edges more plausibly
  exist) is out of scope.
- **EGX data quality:** thinner liquidity and Yahoo coverage gaps for several `.CA` names.
- **Single historical path:** no block-bootstrap or combinatorial purged CV confidence
  intervals on the OOS returns (recommended future work).
- **Survivorship:** the universe uses the *current* index constituents.

---

## 6. Conclusion

The system is a **methodologically rigorous, leakage-controlled decision-support
platform** whose honest empirical finding is that **liquid US and Egyptian equity
direction is not profitably predictable** from the features tested — out-of-sample AUC
~0.51–0.52, and RL agents that look excellent in sample lose money out of sample. The
project's contribution is therefore the **evaluation methodology and risk-controlled
ensemble**, which correctly *avoids* the overfitting trap that the raw RL Sharpe ratios
would otherwise lead a practitioner into.

For live paper trading, expected performance is **approximately market-like, not
market-beating**, and should be judged on risk-adjusted terms (Sharpe, drawdown) against a
buy-and-hold benchmark over months, not on short-run P&L.

---

## References

- Fama, E. (1970). *Efficient Capital Markets.* Journal of Finance.
- Arnott, Harvey & Markowitz (2019). *A Backtesting Protocol in the Era of Machine Learning.*
- Wolpert, D. (1992). *Stacked Generalization.* Neural Networks.
- Breiman, L. (1996). *Stacked Regressions.* Machine Learning.
- Freund & Schapire (1997). *A Decision-Theoretic Generalization of On-Line Learning (Hedge).*
- Kritzman et al. (2010). *Skulls, Financial Turbulence, and Risk Management.*
- Platt, J. (1999). *Probabilistic Outputs for Support Vector Machines.*
- López de Prado, M. (2018). *Advances in Financial Machine Learning.*

---

### Appendix A — Reproduction

```bash
cd /Users/shaahdmaansour/Downloads/nextGen-TradeBot
source .venv/bin/activate
python scripts/step1_data_features.py      # features through today + fold_definitions.json
python scripts/step2_xgb_oof.py            # XGBoost OOF (+ SHAP, Optuna)
python scripts/step3_lstm_oof.py           # LSTM OOF (wavelet denoise, per-fold scaler)
python scripts/step4_train_rl.py           # 3-checkpoint expanding-window RL (PPO/A2C/DDPG/TD3/SAC)
python scripts/step5_meta_learner.py       # stacking meta-learner + learned weights
python scripts/step6_ewma_tracker.py       # adaptive EWMA weights
python scripts/register_oof_runs.py        # register base-model OOF metrics
python scripts/train_deployable_models.py  # pooled XGB/LSTM for live inference
```

### Appendix B — Registered run IDs (this evaluation)
- Meta-learner: `38d1316c`
- XGBoost OOF summary: `2d6a1e48` (AUC 0.509)
- LSTM OOF summary: `81d6428f` (AUC 0.515)
- Deployable models: `data/models/deploy/` (XGB holdout AUC 0.586, LSTM 0.570)
