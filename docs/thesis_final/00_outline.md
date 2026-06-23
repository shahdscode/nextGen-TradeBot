# NextGen TradeBot — Final Thesis (Graduation 2): Restructured Outline

**Working title:** NextGen TradeBot — An Explainable AI Decision-Support Platform
for Retail Equity Trading on the US and Egyptian Markets

This outline maps the standard 6-chapter TOC onto (a) reusable Graduation-1 (G1)
content, (b) the system as actually built this term, and (c) `docs/model_evaluation.md`.
Each section notes its content source so drafting is traceable.

---

## Front Matter
- Title Page · Abstract · Acknowledgment · Table of Contents · List of Figures ·
  List of Tables · List of Abbreviations · Keywords
- Source: regenerate (G1 abstract rewritten to match the built system).

## Chapter 1 — Introduction
- 1.1 Background and Motivation — *rewrite from G1 §Background/§Motivation*
- 1.2 Problem Statement — *new (sharpen from G1)*
- 1.3 Project Objectives — *revise G1 objectives to match built system*
- 1.4 Target Users — *new (retail investors + admin/analyst)*
- 1.5 Project Scope — *rewrite G1 scope (it now includes sentiment, paper trading, US+EGX, intraday FinCast)*
- 1.6 Proposed Solution Overview — *new (two-engine architecture)*
- 1.7 Project Contributions — *new*
- 1.8 Thesis Organization — *rewrite G1 outline*

## Chapter 2 — Literature Review and Existing Solutions
- 2.1 Introduction
- 2.2 Research Literature Review — *extend G1 Ch2: ML/DL trading, RL trading, stacking
  ensembles (Wolpert), online learning (Hedge), time-series foundation models (TimesFM),
  PEFT (LoRA/DoRA), calibration (Platt), backtesting protocol (Arnott et al.), EMH (Fama)*
- 2.3 Existing Systems and Applications — *commercial/academic DSS + robo-advisors*
- 2.4 Comparative Analysis — *Table 2.x comparison*
- 2.5 Identified Gaps — *from G1 research gaps, updated*
- 2.6 How the Proposed Project Addresses the Gaps
- 2.7 Summary

## Chapter 3 — System Analysis and Requirements (mostly new)
- 3.1 Introduction
- 3.2 System Overview
- 3.3 User Roles — admin (train/publish/generate) vs user (consume signals/paper trade)
- 3.4 Functional Requirements — *Table 3.x*
- 3.5 Non-Functional Requirements — *Table 3.x*
- 3.6 Use Case Diagram + descriptions
- 3.7 System Diagrams — architecture, sequence, activity, DFD, ERD
- 3.8 Database Design — 7 core tables + `model_performance_scores` (EWMA)
- 3.9 User Interface Design — web (React) + mobile (React Native)
- 3.10 Summary

## Chapter 4 — AI Integration and Methodology
- Source: `docs/model_evaluation.md` + the FinCast chapter draft.
- 4.1 Introduction
- 4.2 Role of AI in the System
- 4.3 AI Problem Definition
- 4.4 Dataset Description — daily OHLCV (US DOW-30 + EGX) **and** EGX 5-min (FinCast)
- 4.5 Data Preprocessing — 25 features, triple-barrier labels, walk-forward folds; FinCast 5-min pipeline
- 4.6 Model Selection
- 4.7 Proposed AI Pipeline — Engine A (7-model ensemble → meta-learner → EWMA → calibration → risk)
  and Engine B (FinCast foundation model + DoRA + contextual bandit)
- 4.8 Training Methodology
- 4.9 Evaluation Metrics — AUC, accuracy, Brier, Sharpe, max drawdown, MAE (FinCast)
- 4.10 Experimental Results — honest in-sample/OOS gap; US vs EGX; FinCast
- 4.11 AI Deployment and Integration
- 4.12 AI Limitations
- 4.13 Summary

## Chapter 5 — System Implementation and Evaluation (mostly new, from codebase)
- 5.1 Introduction
- 5.2 Development Environment
- 5.3 Technologies and Tools — FastAPI, React, React Native/Expo, Celery+Redis, SQLite,
  PyTorch, XGBoost, FinRL/SB3, Alpaca, Docker
- 5.4 Frontend Implementation (web, 15 pages)
- 5.5 Backend Implementation (FastAPI, 11 routers, ~45+ endpoints; JWT auth; admin gating)
- 5.6 Database Implementation
- 5.7 AI Module Implementation
- 5.8 System Integration (Celery jobs, scheduler, signal pipeline)
- 5.9 Deployment (Docker Compose)
- 5.10 System Screenshots and Walkthrough
- 5.11 Testing and Validation — functional/integration/performance/AI-output; *test-case tables*
- 5.12 Evaluation Results
- 5.13 Summary

## Chapter 6 — Discussion, Conclusion, and Future Work
- 6.1 Introduction
- 6.2 Discussion of Results — efficiency ceiling; value = risk-adjusted weighting + control + explainability
- 6.3 Challenges Faced
- 6.4 Project Limitations
- 6.5 Summary of Achievements
- 6.6 Conclusion
- 6.7 Future Work

## References — IEEE style, cited in-text.
## Appendices — Gantt, progress logs, risk/ethics, diagrams, API docs, test cases, manual, install guide.
