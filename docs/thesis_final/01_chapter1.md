# Chapter 1: Introduction

This chapter introduces the NextGen TradeBot project. It establishes the financial
and technological context that motivates the work (Section 1.1), defines the
problem it addresses (Section 1.2), and states the objectives that guide it
(Section 1.3). It then identifies the intended users (Section 1.4), delimits the
scope (Section 1.5), and presents a high-level overview of the proposed solution
(Section 1.6). The chapter concludes by summarising the project's contributions
(Section 1.7) and outlining the organisation of the remainder of the thesis
(Section 1.8).

## 1.1 Background and Motivation

Equity markets have become increasingly shaped by algorithmic and artificial
intelligence (AI) driven decision-making. Institutional investors routinely deploy
quantitative models, machine-learning predictors, and automated execution systems,
whereas retail investors typically lack access to comparable tools and to the
expertise required to interpret them. This asymmetry is especially pronounced in
emerging markets such as the Egyptian Exchange (EGX), where intelligent
decision-support tools tailored to local market behaviour are scarce.

Two further considerations motivate the work. First, financial time series are
notoriously difficult to predict: the Efficient Market Hypothesis [1] holds that
asset prices already reflect available information, so consistent directional
prediction from historical data alone is unlikely. The modern backtesting
literature [9] reinforces this caution, warning that strong in-sample performance
frequently fails to generalise. A credible system must therefore be evaluated under
a rigorous, leakage-controlled protocol and must derive value from more than raw
predictive accuracy. Second, opaque "black-box" predictions are of limited use to a
retail investor who must ultimately make and justify a decision; explainability is
a practical requirement, not an optional feature.

These observations motivate a system that combines multiple complementary models,
calibrates and explains its own confidence, enforces explicit risk controls, and is
honest about the limits of predictability — providing decision *support* rather than
a promise of guaranteed profit.

## 1.2 Problem Statement

Retail investors in markets such as the EGX face three coupled problems: (i) limited
access to AI-based decision-support tools that institutional traders take for granted;
(ii) a tendency among existing tools to report optimistic, in-sample performance that
does not survive out-of-sample testing; and (iii) a lack of transparency, with
predictions presented without the reasoning, confidence calibration, or risk context
needed to act on them responsibly. The problem this project addresses is therefore to
design, build, and rigorously evaluate an accessible, explainable, risk-aware AI
decision-support platform for retail equity trading, whose performance claims are
established under a leakage-controlled evaluation protocol.

## 1.3 Project Objectives

The overall objective is to design, implement, and evaluate an explainable AI
decision-support platform for retail equity trading on the US and Egyptian markets.
The specific objectives are:

1. To acquire and preprocess historical and live market data for US (DOW-30) and
   Egyptian (EGX) equities, including engineered technical features and a
   leakage-controlled walk-forward labelling scheme.
2. To design a multi-model AI pipeline that combines gradient-boosted trees, a deep
   sequence model, and reinforcement-learning agents through a stacking meta-learner
   with adaptive, performance-weighted fusion.
3. To integrate a time-series foundation model (FinCast) adapted to intraday data, as
   a complementary forecasting engine, together with a decision layer that converts
   forecasts into trading actions.
4. To produce calibrated, explainable BUY/HOLD/SELL signals with explicit risk
   guardrails (confidence suppression, regime awareness, and drawdown control).
5. To deliver web and mobile applications through which users can view signals and
   their explanations and operate a paper-trading account.
6. To evaluate the system under a rigorous, leakage-controlled protocol and to report
   results honestly, including out-of-sample limitations.

## 1.4 Target Users

The platform serves two roles. The primary users are **retail investors** who consume
explainable signals, inspect model confidence and risk metadata, and operate a
risk-managed paper-trading account without requiring quantitative-finance expertise.
The secondary role is the **administrator/analyst**, who trains and publishes models,
generates signal batches, and monitors model performance through the administrative
web interface. Access to model-management functions is restricted to the
administrator role through authenticated, role-gated endpoints.

## 1.5 Project Scope

The project delivers a working prototype with the following scope:

- **Markets and instruments:** US large-cap equities (DOW-30) and Egyptian equities
  (EGX); no derivatives, foreign exchange, or cryptocurrencies are traded by the
  system, although the FinCast base model was pretrained on such data by its authors.
- **AI:** a seven-model ensemble unified by a stacking meta-learner with adaptive
  fusion and calibrated confidence, plus an intraday foundation-model forecaster
  (FinCast) with a contextual-bandit decision layer.
- **Explainability and risk:** SHAP-based feature attribution on signals, confidence
  calibration, regime-aware suppression, and a portfolio drawdown kill-switch.
- **Execution:** decision support and **paper trading only** (simulated sessions and a
  brokerage paper account); the system never executes real-money trades.
- **Applications:** a web application and a mobile application backed by a REST API.

Out of scope are high-frequency trading, real-money execution, and production-scale
cloud deployment beyond a containerised reference configuration.

## 1.6 Proposed Solution Overview

NextGen TradeBot is organised around two complementary decision engines that operate
at different time horizons, served through a common application and risk layer
(illustrated in Figure 1.1, *Proposed Solution Overview*).

- **Engine A — Daily ensemble.** Engineered features feed seven base models
  (XGBoost, an LSTM network, and five reinforcement-learning agents — PPO, A2C, DDPG,
  TD3, SAC). Their out-of-fold predictions train a stacking meta-learner [3] whose
  coefficients act as data-driven fusion weights; an adaptive exponentially-weighted
  performance tracker [4] reweights the models over time, confidence is calibrated,
  and risk guardrails gate the final BUY/HOLD/SELL signal.
- **Engine B — Intraday FinCast.** A decoder-only time-series foundation model [5],
  adapted to 5-minute market microstructure via parameter-efficient fine-tuning [6],
  forecasts a short-horizon price path with uncertainty bands; a contextual bandit
  converts these forecasts into trading actions.

Both engines surface explainable, risk-aware signals through a FastAPI backend to the
web and mobile clients, where users can additionally operate a paper-trading account.

## 1.7 Project Contributions

The project makes the following contributions:

1. **A unified, multi-model decision-support platform** that combines a stacking
   ensemble, adaptive online reweighting, calibrated confidence, and SHAP-based
   explanations behind a single web and mobile interface.
2. **The integration of a time-series foundation model (FinCast)** with
   parameter-efficient fine-tuning and a contextual-bandit trading layer, deployed
   end-to-end behind the same decision and risk infrastructure.
3. **A leakage-controlled, walk-forward evaluation** across US and Egyptian markets
   that reports results honestly — including the finding that out-of-sample
   directional predictability sits near the market-efficiency ceiling — and that
   locates the system's demonstrable value in risk-adjusted fusion, risk control, and
   explainability rather than in raw alpha.
4. **A reproducible engineering artefact:** a modular FastAPI/React/React-Native
   system with role-based access control, asynchronous model jobs, and a paper-trading
   gateway.

## 1.8 Thesis Organization

The remainder of this thesis is organised as follows. Chapter 2 reviews the relevant
literature and existing systems, and identifies the gaps this project addresses.
Chapter 3 presents the system analysis and requirements, including user roles,
functional and non-functional requirements, system diagrams, the database design, and
the user-interface design. Chapter 4 details the AI methodology — datasets,
preprocessing, model selection, the proposed pipeline, training, evaluation metrics,
and experimental results — and how the AI is integrated into the system. Chapter 5
describes the implementation of the frontend, backend, database, and AI modules,
their integration and deployment, and the testing and evaluation of the system.
Chapter 6 discusses the results, the challenges encountered, the project's
limitations, and directions for future work.

## 1.9 Summary

This chapter introduced NextGen TradeBot, an explainable AI decision-support platform
for retail equity trading on the US and Egyptian markets. It motivated the work
through the access gap faced by retail investors and the dual requirements of rigorous
evaluation and explainability, stated the problem and objectives, identified the
target users, and delimited the scope to risk-managed paper trading. It then
introduced the two-engine solution — a daily multi-model ensemble and an intraday
foundation-model forecaster — and summarised the project's contributions. The next
chapter situates these choices within the existing research and systems landscape.

---

### Chapter 1 references (consolidated into the thesis References, IEEE style)
- [1] E. F. Fama, "Efficient capital markets: A review of theory and empirical work,"
  *The Journal of Finance*, 1970.
- [3] D. H. Wolpert, "Stacked generalization," *Neural Networks*, 1992.
- [4] Y. Freund and R. E. Schapire, "A decision-theoretic generalization of on-line
  learning and an application to boosting," *J. Computer and System Sciences*, 1997.
- [5] A. Das et al., "A decoder-only foundation model for time-series forecasting
  (TimesFM)," *ICML*, 2024.
- [6] S.-Y. Liu et al., "DoRA: Weight-decomposed low-rank adaptation," *ICML*, 2024.
- [9] R. Arnott, C. R. Harvey, and H. Markowitz, "A backtesting protocol in the era of
  machine learning," *The Journal of Financial Data Science*, 2019.
