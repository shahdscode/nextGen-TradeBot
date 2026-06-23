# Chapter 2: Literature Review and Existing Solutions

This chapter reviews the research and systems that underpin NextGen TradeBot.
Section 2.2 surveys the relevant literature, tracing the evolution from statistical
forecasting to machine learning, deep learning, reinforcement learning, ensemble and
online-learning methods, time-series foundation models, and the supporting areas of
explainability, sentiment analysis, calibration, and evaluation rigour. Section 2.3
examines existing systems and applications, and Section 2.4 compares them. Section 2.5
identifies the gaps that remain, and Section 2.6 explains how this project addresses
them. Section 2.7 summarises the chapter.

## 2.1 Introduction

The objective of this review is to establish the theoretical and empirical foundation
for an explainable, risk-aware AI decision-support platform for retail equity trading.
The review is deliberately broad because the proposed system is not a single predictor
but a pipeline that combines several model families and a foundation model behind a
common decision and risk layer. Accordingly, the survey covers both the predictive
methods themselves and the methodological concerns — overfitting, leakage-controlled
evaluation, calibration, and explainability — that determine whether such a system is
trustworthy in practice.

## 2.2 Research Literature Review

### 2.2.1 From statistical models to machine learning

Financial forecasting originally relied on statistical techniques such as linear
regression and autoregressive models, whose accuracy is limited by the nonlinear and
stochastic nature of markets. As computational power and data availability grew,
rule-based algorithmic trading using technical indicators (moving averages, RSI,
Bollinger Bands) became widespread, and classical machine-learning models were shown to
capture nonlinear relationships that statistical methods miss [15], [16]. Subsequent
systematic reviews confirmed that supervised learners — random forests, support vector
machines, and neural networks — are effective for trend classification and price
prediction when combined with engineered technical features [22], [23]. Table 2.1
summarises this evolution.

*Table 2.1: Historical evolution of trading technologies.*

| Period | Main approach | Characteristics |
|--------|---------------|-----------------|
| Pre-1990s | Manual trading | Fundamental and technical analysis |
| 1990s–2000s | Algorithmic trading | Rule-based strategies |
| 2010s | Machine learning | ANN, SVM, Random Forest |
| 2020s | Deep learning, RL, foundation models | LSTM, DRL, Transformers |

### 2.2.2 Deep learning and reinforcement learning for trading

Deep sequence models, particularly Long Short-Term Memory (LSTM) networks, proved
effective at modelling temporal dependencies in price series and supporting
medium-term (swing) trading over days to weeks [17], [24]. Reinforcement learning (RL)
reframed trading as sequential decision-making under a Markov Decision Process, in
which an agent observes market state, takes BUY/HOLD/SELL actions, and receives
risk-adjusted reward. Yang et al. demonstrated that an *ensemble* of deep RL agents
yields higher and more stable risk-adjusted returns than any single agent [18], and the
FinRL family of frameworks standardised RL trading environments, including transaction
cost modelling and market simulation [19], [20], [21]. These works directly inform the
five RL agents (PPO, A2C, DDPG, TD3, SAC) used in the present system.

### 2.2.3 Ensemble learning, stacking, and adaptive weighting

A central methodological choice in this project is how to combine heterogeneous
models. *Stacked generalisation* [3] and stacked regressions [13] train a
meta-learner on the out-of-fold predictions of base models, learning data-driven
combination weights rather than fixing them by hand. Complementary to stacking,
online-learning theory — the Hedge algorithm of Freund and Schapire [4] — provides a
principled way to reweight experts over time according to their realised performance,
which motivates the adaptive exponentially-weighted tracker used here. Together these
results justify replacing hand-tuned fusion weights with a learned, adaptive scheme.

### 2.2.4 Time-series foundation models and parameter-efficient fine-tuning

A recent shift is the emergence of *foundation models* for time series. TimesFM is a
decoder-only transformer pretrained on large, heterogeneous time-series corpora that
forecasts across domains and temporal scales [5]. Sparsely-gated Mixture-of-Experts
layers allow such models to scale capacity while activating only a subset of experts
per input, supporting regime specialisation [11]. Because full fine-tuning of
billion-parameter models is costly, parameter-efficient fine-tuning (PEFT) methods are
used: Low-Rank Adaptation (LoRA) injects trainable low-rank matrices into frozen
weights [10], and its weight-decomposed variant (DoRA) improves adaptation stability
[6]. These methods underpin the FinCast engine, which adapts a pretrained foundation
model to intraday Egyptian-market microstructure via DoRA.

### 2.2.5 Explainability, sentiment, and calibration

For a retail-facing system, interpretability and trustworthy confidence are essential.
SHapley Additive exPlanations (SHAP) attribute a model's output to its input features
on a sound game-theoretic basis [7], enabling per-signal explanations. Domain-specific
language models such as FinBERT provide financial-text sentiment scoring [8], which can
augment price-derived features. Finally, model confidence must be *calibrated* to be
actionable: Platt scaling maps raw scores to empirical probabilities [12], so that a
stated confidence corresponds to an observed success frequency. Decision-support
frameworks emphasise precisely these qualities — Kraus and Feuerriegel showed deep
models can support investment decisions from disclosures [26], and the SAFE framework
stresses sustainability, accuracy, fairness, and explainability in financial AI [27].

### 2.2.6 Evaluation rigour and market efficiency

A recurring theme is that apparent performance is often an artefact of methodology.
The Efficient Market Hypothesis holds that prices already incorporate available
information, bounding what price-only prediction can achieve [1]. Arnott, Harvey, and
Markowitz catalogue the protocol failures — overfitting, data-mining bias, and leakage —
that make in-sample results unreliable, and prescribe walk-forward, out-of-sample
discipline [9]. López de Prado's *Advances in Financial Machine Learning* provides the
concrete techniques adopted here, including triple-barrier labelling and embargoed
walk-forward validation [2]. Olorunnimbe and Viktor further note that many studies lack
reproducibility and real-world deployment [29]. These works shape the leakage-controlled
evaluation protocol reported in Chapter 4.

## 2.3 Existing Systems and Applications

Existing solutions fall into three groups. *Open-source research frameworks* such as
FinRL and FinRL-Meta provide standardised RL trading environments and datasets, but are
libraries for researchers rather than end-user applications [19], [20]. *Commercial and
automated platforms* offer API-based execution and, in some cases, AI-assisted signals,
but Chakole and Kurhekar highlight the real-time execution challenges of such pipelines
[28], and most target institutional users with limited accessible interfaces for retail
investors [31]. *Academic decision-support systems* demonstrate individual capabilities —
prediction from disclosures [26], explainable/ethical financial AI [27] — but rarely
integrate prediction, explanation, risk control, and a usable interface into one
deployed system. Emerging-market coverage, and Egyptian-market coverage in particular,
remains sparse [30].

## 2.4 Comparative Analysis

Table 2.2 compares representative existing approaches against the proposed system across
the dimensions most relevant to a trustworthy retail decision-support tool.

*Table 2.2: Comparison of existing approaches and the proposed system.*

| Capability | Classical ML/DL studies | RL frameworks (FinRL) | Commercial platforms | NextGen TradeBot |
|------------|:----------------------:|:---------------------:|:--------------------:|:----------------:|
| Multiple model families fused | Rare | Single paradigm | Opaque | Yes (7-model stack) |
| Adaptive / learned weighting | No | No | Unknown | Yes (meta-learner + EWMA) |
| Foundation-model forecasting | No | No | Rare | Yes (FinCast + DoRA) |
| Explainable signals (SHAP) | Rare | No | Rare | Yes |
| Calibrated confidence | Rare | No | Unknown | Yes (Platt) |
| Risk guardrails | Varies | Partial | Varies | Yes (suppression, drawdown) |
| Leakage-controlled evaluation | Often weak | Varies | Not disclosed | Yes (walk-forward + embargo) |
| Retail-facing web + mobile UI | No | No | Some | Yes |
| Emerging-market (EGX) coverage | Rare | Rare | Rare | Yes (US + EGX) |

## 2.5 Identified Gaps

Synthesising the review, four gaps are evident (Table 2.3). First, most studies focus on
developed markets, with limited attention to emerging markets such as Egypt [30].
Second, validation is frequently weak: overfitting and inadequate backtesting undermine
reported results [9], [29]. Third, explainability and user-centred design are
under-emphasised, leaving predictions opaque to retail users [27], [30]. Fourth, few
works deliver an *end-to-end* system that integrates prediction, fusion, explanation,
risk control, and execution support into a single accessible platform [31].

*Table 2.3: Summary of identified research gaps.*

| Area | Limitation in existing work |
|------|-----------------------------|
| Market focus | Predominantly developed markets |
| Validation | Overfitting and weak/leaky backtesting |
| Transparency | Limited explainability and calibration |
| Integration | Few end-to-end, retail-facing systems |

## 2.6 How the Proposed Project Addresses the Gaps

NextGen TradeBot addresses each gap directly. **Market focus:** the system is evaluated
on both US (DOW-30) and Egyptian (EGX) equities, contributing emerging-market evidence.
**Validation:** all predictive claims are produced under a leakage-controlled
walk-forward protocol with embargoed, out-of-fold predictions and automated leakage
checks, following [2] and [9]; results are reported honestly, including negative
out-of-sample findings. **Transparency:** signals carry SHAP-based feature attributions
[7] and Platt-calibrated confidence [12], with explicit risk guardrails. **Integration:**
the project delivers a complete pipeline — a stacking ensemble [3] with adaptive
weighting [4], a foundation-model engine [5], [6], explainability, risk control, and
paper trading — exposed through web and mobile interfaces. In doing so it unifies, in a
single deployed and reproducible system, capabilities that prior work demonstrates only
in isolation.

## 2.7 Summary

This chapter reviewed the literature spanning statistical, machine-learning, deep,
reinforcement, ensemble, and foundation-model approaches to trading, together with the
explainability, sentiment, calibration, and evaluation concerns that govern their
trustworthiness. It examined existing research frameworks, commercial platforms, and
academic decision-support systems, and compared them against the proposed approach. The
review identified four persistent gaps — emerging-market coverage, validation rigour,
transparency, and end-to-end integration — and showed how NextGen TradeBot is designed
to address them. The next chapter translates these requirements into a concrete system
analysis and design.

---

### Chapter 2 references (IEEE; consolidated into the thesis References)
- [1] E. F. Fama, "Efficient capital markets: A review of theory and empirical work," *J. Finance*, 1970.
- [2] M. López de Prado, *Advances in Financial Machine Learning*. Wiley, 2018.
- [3] D. H. Wolpert, "Stacked generalization," *Neural Networks*, 1992.
- [4] Y. Freund and R. E. Schapire, "A decision-theoretic generalization of on-line learning," *J. Comput. Syst. Sci.*, 1997.
- [5] A. Das et al., "A decoder-only foundation model for time-series forecasting," *ICML*, 2024.
- [6] S.-Y. Liu et al., "DoRA: Weight-decomposed low-rank adaptation," *ICML*, 2024.
- [7] S. Lundberg and S.-I. Lee, "A unified approach to interpreting model predictions (SHAP)," *NeurIPS*, 2017.
- [8] D. Araci, "FinBERT: Financial sentiment analysis with pre-trained language models," *arXiv:1908.10063*, 2019.
- [9] R. Arnott, C. R. Harvey, and H. Markowitz, "A backtesting protocol in the era of machine learning," *J. Financial Data Science*, 2019.
- [10] E. Hu et al., "LoRA: Low-rank adaptation of large language models," *ICLR*, 2022.
- [11] N. Shazeer et al., "Outrageously large neural networks: The sparsely-gated mixture-of-experts layer," *ICLR*, 2017.
- [12] J. Platt, "Probabilistic outputs for support vector machines," *Advances in Large Margin Classifiers*, 1999.
- [13] L. Breiman, "Stacked regressions," *Machine Learning*, 1996.
- [15] A. Vijh et al., "Stock closing price prediction using machine learning techniques," *Procedia Computer Science*, 2020.
- [16] M. Obthong et al., "A survey on machine learning for stock price prediction," 2020.
- [17] N. Totakura et al., "Stock price prediction using LSTM for swing trading," 2020.
- [18] H. Yang et al., "Deep reinforcement learning for automated stock trading: An ensemble strategy," *ACM ICAIF*, 2020.
- [19] X.-Y. Liu et al., "FinRL: A deep reinforcement learning library for automated trading," 2022.
- [20] X.-Y. Liu et al., "FinRL-Meta: Market environments and benchmarks for data-driven financial RL," *NeurIPS*, 2022/2023.
- [21] Z. Zhang et al., "Deep reinforcement learning for trading," *J. Financial Data Science*, 2021.
- [22] M. Kumbure et al., "Machine learning techniques and data for stock market forecasting: A literature review," *Expert Systems with Applications*, 2022.
- [23] G. Sonkavde et al., "Forecasting stock market prices using machine and deep learning: A systematic review," 2023.
- [24] J. Soni et al., "Deep learning for stock market prediction: A review," 2022.
- [25] R. Sukma and C. Namahoot, "Hybrid technical-indicator machine-learning trading strategy," 2024.
- [26] M. Kraus and S. Feuerriegel, "Decision support from financial disclosures with deep neural networks," *Decision Support Systems*, 2017.
- [27] D. Dung and P. Giudici, "SAFE artificial intelligence in finance," 2025.
- [28] J. Chakole and M. Kurhekar, "Automated trading systems using APIs," 2023.
- [29] M. Olorunnimbe and H. Viktor, "Deep learning in the stock market — a systematic survey of practice, backtesting, and applications," *Artificial Intelligence Review*, 2023.
- [30] S. Chopra and R. Sharma, "Application of artificial intelligence in stock market forecasting: A systematic review," 2021.
- [31] O. Sholoiko and Y. Hou, "Accessibility of AI-based trading tools for retail investors," 2025.
