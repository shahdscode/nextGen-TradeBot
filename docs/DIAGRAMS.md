# NextGen TradeBot — Defense Diagrams

Mermaid diagrams for thesis slides and examiner handouts. Render in GitHub, VS Code, or [mermaid.live](https://mermaid.live).

---

## 1. System architecture

```mermaid
flowchart TB
    subgraph clients [Clients]
        Web[React Web App]
        Mobile[React Native Mobile]
    end

    subgraph api [Application Layer]
        FastAPI[FastAPI + JWT Auth]
        Celery[Celery Workers]
    end

    subgraph ai [AI Decision Layer]
        Meta[Meta-Learner]
        ML[XGBoost + LSTM]
        RL[5 RL Agents]
        EWMA[EWMA Weights]
        Risk[Risk Engine]
        Regime[Regime HMM]
    end

    subgraph research [Research Layer]
        BT[Backtest Engine]
        WF[Walk-Forward Validation]
        SHAP[SHAP Explainability]
    end

    subgraph exec [Execution Layer]
        Sim[Paper Simulator per-user]
        Alpaca[Alpaca Paper per-user]
    end

    subgraph data [Persistence]
        DB[(SQLite / PostgreSQL)]
        Models[(Model Artifacts)]
        Logs[(Trade Logs + Signals)]
    end

    Web --> FastAPI
    Mobile --> FastAPI
    FastAPI --> Celery
    FastAPI --> ai
    FastAPI --> research
    FastAPI --> exec
    ai --> exec
    research --> Models
    ai --> Logs
    exec --> Logs
    FastAPI --> DB
    Celery --> Redis[(Redis)]
```

---

## 2. Entity-relationship (core tables)

```mermaid
erDiagram
    User ||--o{ PaperSession : owns
    User ||--o{ Backtest : owns
    User ||--o{ Job : triggers
    PaperSession ||--o{ TradeLog : generates

    User {
        string id PK
        string username
        string role
        string alpaca_api_key
    }

    PaperSession {
        string id PK
        string user_id FK
        boolean running
        json positions
        float cash
    }

    TradeLog {
        string id PK
        string session_id FK
        string ticker
        string action
        float meta_prob
        json model_signals
        json indicators
    }

    Signal {
        string id PK
        string ticker
        string action
        float confidence
        string market
    }

    Backtest {
        string id PK
        string user_id FK
        string run_id
        json result_json
    }

    Run {
        string id PK
        string algorithm
        string model_path
        boolean published
    }

    Job {
        string id PK
        string user_id FK
        string type
        string status
    }

    ModelPerformanceScore {
        string id PK
        string model_key
        float ewma_score
    }
```

**Tenancy:** `Signal`, `Run`, `ModelPerformanceScore` are **shared**. `PaperSession`, `Backtest`, `Job`, `TradeLog` are **per-user**.

---

## 3. AI pipeline (live signals)

```mermaid
flowchart LR
    OHLCV[Yahoo OHLCV + VIX] --> FEAT[26 Features]
    FEAT --> XGB[XGBoost]
    FEAT --> LSTM[LSTM]
    FEAT --> RL[5 RL Agents]

    XGB --> OOF[OOF Predictions]
    LSTM --> OOF
    RL --> OOF

    OOF --> META[Meta-Learner Train]
    META --> LIVE[Live Fusion]

    REGIME[Regime HMM] --> LIVE
    SENT[Sentiment FinBERT] --> LIVE
    EWMA[EWMA Tracker] --> LIVE

    LIVE --> GUARD[Risk Guardrails]
    GUARD --> SIG[Signal Card]
    SIG --> DB[(signals table)]

    LIVE --> ALLOC[Portfolio Allocation]
    ALLOC --> SIM[Paper Sim]
    ALLOC --> ALP[Alpaca Paper]
    ALLOC --> LOG[(trade_logs)]
```

---

## 4. Decision provenance chain

```mermaid
flowchart TD
    A[Market Data] --> B[7 Base Model Signals]
    B --> C[Meta-Learner Probability]
    C --> D{Regime + Risk OK?}
    D -->|Yes| E[Position Sizing ATR]
    D -->|No| F[SUPPRESS / HOLD / Cash]
    E --> G[Stop + Target]
    G --> H[Execute BUY or SELL]
    H --> I[TradeLog Row]

    I --> J1[Model Votes]
    I --> J2[Technical Snapshot]
    I --> J3[Fundamentals]
    I --> J4[Risk Block]
    I --> J5[Final Explanation]

    J1 --> DE[Decision Explorer UI]
    J2 --> DE
    J3 --> DE
    J4 --> DE
    J5 --> DE
```

---

## 5. Product effort distribution (v1.0)

```mermaid
pie title NextGen TradeBot v1.0 Composition
    "AI & Meta-Learner" : 25
    "Research & Validation" : 20
    "SaaS Platform" : 20
    "Explainability & Provenance" : 15
    "Portfolio Intelligence" : 10
    "Documentation & Release" : 10
```

---

## 6. User journey (defense demo)

```mermaid
sequenceDiagram
    actor User
    participant Web
    participant API
    participant AI
    participant Broker

    User->>Web: Register / Login
    Web->>API: JWT auth
    User->>Web: Open Command Center
    API->>AI: Signals + Analytics
    AI-->>Web: Health + Opportunities
    User->>Web: Meta Rebalance
    Web->>API: POST rebalance
    API->>AI: generate_meta_allocation
    AI->>Broker: Orders or Sim positions
    API->>API: log_trades
    User->>Web: Decision Explorer
    Web->>API: GET trade-log/id
    API-->>Web: Full provenance trace
```
