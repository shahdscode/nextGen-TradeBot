# NextGen TradeBot — Launch Checklist

A realistic path from "strong codebase" to "live product people rely on." Ordered
by what blocks what. Legend: ✅ done · 🔶 partial · ⬜ not started.

> **Positioning (decide first, it shapes everything):**
> NextGen TradeBot is an **AI-powered quantitative research & paper-trading platform
> with explainable decision provenance.** It is a research/education/analytics tool.
> It is **not** investment advice, does not execute real-money trades, and makes **no
> claim of market-beating returns.** Every user-facing surface must reflect this.

---

## Phase 0 — Legal & business (before ANY real user)
These are not optional for a financial product, and no code fixes them.

- ⬜ Form an entity (LLC or local equivalent) so liability isn't personal
- ⬜ Lawyer-reviewed **Terms of Service** + **Privacy Policy** (templates exist in-app — not legal cover)
- 🔶 **Financial disclaimer** shown prominently (in-app page done; confirm it's on every relevant surface)
- ⬜ Confirm you're outside investment-adviser registration scope (US: SEC/state; EG: FRA) — get a lawyer's read
- ⬜ Decide data-licensing: your market-data provider must permit commercial redistribution
- ⬜ Business bank account + payment processor (Stripe) KYC

## Phase 1 — Production infrastructure (make it actually live)
- 🔶 **HTTPS backend** (Caddy reverse-proxy on the server / managed host) — *in progress, blocked on SSH access*
- ⬜ Wire the Vercel frontend: set `VITE_API_URL` to the HTTPS backend, redeploy
- 🔶 **Managed Postgres** (Supabase) instead of SQLite — supported in code; provision + set `DATABASE_URL`
- ⬜ Automated DB backups (Supabase does this; verify + test a restore)
- ⬜ Deploy pipeline: push → server sync + restart (currently manual)
- ✅ Ship trained ML artifacts in repo (meta-learner, calibrator, deploy models)
- ✅ Production guardrails: refuses default JWT secret; admin seed gated

## Phase 2 — Security
- ✅ Passwords hashed (bcrypt)
- ✅ Rate limiting on auth endpoints
- ✅ **Encrypt Alpaca API keys at rest** (Fernet)
- ✅ Global exception handler (no stack-trace leaks) + request-id logging
- ⬜ Refresh tokens (currently single short-lived JWT)
- ⬜ 2FA (mobile UI references it; not implemented)
- ⬜ Account deletion / data-export (privacy compliance)
- ⬜ Dependency vulnerability scanning (GitHub Dependabot / `pip-audit`)
- ⬜ Set a dedicated `SECRET_ENCRYPTION_KEY` in prod (don't rely on JWT-derived)

## Phase 3 — Data & reliability (biggest technical risk)
- ⬜ **Replace `yfinance`** with a licensed provider (Polygon / Alpaca data / Twelve Data). yfinance is unofficial, rate-limited, and not licensed for commercial use — it *will* break in prod
- ⬜ Provider adapter behind a clean interface (so you can swap providers)
- ⬜ Confirm the daily signal scheduler runs on the server (stale signals = dead product)
- ⬜ Model-drift monitoring + retraining cadence
- 🔶 Monitoring/alerting: error tracking (Sentry) + uptime (UptimeRobot) — logging done, external alerting not wired

## Phase 4 — Billing & product
- ⬜ Stripe: plans (Free / Pro), checkout, entitlements, dunning
- ⬜ Email delivery in prod (SMTP configured; verify deliverability + SPF/DKIM)
- ⬜ Onboarding flow + product docs / FAQ
- ⬜ Status page + support channel (email/Discord)
- 🔶 **Mobile parity** — web has Command Center / Decision Explorer / Portfolio Intelligence / Alpaca settings; mobile does not. Either build parity or drop mobile from launch

## Phase 5 — Growth (after it's genuinely live)
- ⬜ 5–20 invited beta users; collect feedback
- ⬜ Analytics (privacy-respecting) to see what's used
- ⬜ Iterate on the one flow that matters: signal → "why" → paper trade

---

## Engineering quality (foundation — already strong)
- ✅ Unit tests for the trading math (sizing, portfolio, backtest metrics, crypto)
- ✅ CI (tests + frontend build on every push)
- ✅ End-to-end smoke test (`scripts/smoke_test.py`) — gate deploys on it
- ✅ Explainable decision provenance (Trade Journal + Decision Explorer)
- ✅ Multi-tenant data scoping (per-user sessions/backtests/jobs)

## The honest bottom line
The **code** is no longer the risk. The path to a real product runs through
**legal (Phase 0), a licensed data source (Phase 3), and a working live deploy
(Phase 1)** — in roughly that order of importance. Keep it **paper-trading + signals
only** at launch; real-money execution is a different, regulated company.
