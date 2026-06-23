import { Link } from 'react-router-dom'
import { useAuth } from '../context/authContext'

const FEATURES = [
  {
    title: '7-Model Ensemble',
    desc: 'XGBoost, LSTM, and five FinRL agents (PPO, A2C, DDPG, TD3, SAC) fused into one signal.',
    icon: '🧠',
  },
  {
    title: 'Meta-Learner Fusion',
    desc: 'A stacking meta-learner learns data-driven weights, refined daily by an adaptive EWMA tracker.',
    icon: '🧩',
  },
  {
    title: 'FinCast Forecasting',
    desc: 'A fine-tuned time-series foundation model forecasts 5-minute price paths with quantile bands.',
    icon: '🔮',
  },
  {
    title: 'Explainable Signals',
    desc: 'Every BUY/HOLD/SELL card carries SHAP feature attribution and calibrated confidence.',
    icon: '🔍',
  },
  {
    title: 'Regime & Sentiment',
    desc: '3-state HMM regime detection with FinBERT (US) and Arabic (EGX) headline sentiment.',
    icon: '📊',
  },
  {
    title: 'Paper Trading & Risk',
    desc: 'Simulated and Alpaca paper sessions with stop-loss, regime defense, and a drawdown kill-switch.',
    icon: '💼',
  },
]

const STATS = [
  { value: '8', label: 'AI / RL models' },
  { value: '25', label: 'Engineered features' },
  { value: '50+', label: 'US & EGX tickers' },
  { value: '2', label: 'Decision engines' },
]

// Realistic mixed movers (not all green) for an authentic ticker strip
const TICKERS = [
  { sym: 'AAPL', chg: '+1.24%', up: true },
  { sym: 'MSFT', chg: '+0.87%', up: true },
  { sym: 'COMI.CA', chg: '-0.42%', up: false },
  { sym: 'JPM', chg: '+1.05%', up: true },
  { sym: 'SWDY.CA', chg: '+0.63%', up: true },
  { sym: 'NVDA', chg: '-1.18%', up: false },
  { sym: 'HRHO.CA', chg: '+0.31%', up: true },
  { sym: 'AMZN', chg: '-0.55%', up: false },
]

function SignalCard() {
  return (
    <div className="rounded-2xl border border-white/10 bg-gray-900/80 backdrop-blur-xl p-5 shadow-2xl shadow-black/50">
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider">Signal</p>
          <p className="text-lg font-bold">AAPL · US</p>
        </div>
        <span className="px-3 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 text-sm font-semibold border border-emerald-500/30">
          BUY
        </span>
      </div>
      <div className="space-y-2 mb-4">
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Calibrated confidence</span>
          <span className="text-white font-medium">72%</span>
        </div>
        <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
          <div className="h-full w-[72%] rounded-full bg-gradient-to-r from-teal-500 to-emerald-400 landing-bar-fill" />
        </div>
      </div>
      <div className="flex gap-2 flex-wrap">
        <span className="text-[10px] px-2 py-0.5 rounded bg-teal-500/10 text-teal-300 border border-teal-500/20">BULL regime</span>
        <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">XGB +0.68</span>
        <span className="text-[10px] px-2 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20">SHAP: RSI ↑</span>
        <span className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">Risk: LOW</span>
      </div>
    </div>
  )
}

export default function LandingPage() {
  const { user } = useAuth()
  const appHref = user?.role === 'admin' ? '/app' : user ? '/app/signals' : '/login'

  return (
    <div className="landing-page min-h-screen bg-[#050810] text-white overflow-x-hidden">
      {/* Animated background */}
      <div className="landing-bg" aria-hidden="true">
        <div className="landing-orb landing-orb-1" />
        <div className="landing-orb landing-orb-2" />
        <div className="landing-orb landing-orb-3" />
        <div className="landing-grid" />
      </div>

      {/* Nav */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5 max-w-6xl mx-auto">
        <Link to="/" className="flex items-center gap-2.5 group">
          <img
            src="/logo.png"
            alt="NextGen TradeBot logo"
            className="w-9 h-9 rounded-xl shadow-lg shadow-teal-500/20 group-hover:scale-105 transition-transform"
          />
          <span className="font-semibold tracking-tight">NextGen TradeBot</span>
        </Link>
        <nav className="flex items-center gap-3">
          <a href="#features" className="hidden sm:inline text-sm text-gray-400 hover:text-white transition-colors">
            Features
          </a>
          <a href="#pipeline" className="hidden sm:inline text-sm text-gray-400 hover:text-white transition-colors">
            Pipeline
          </a>
          <Link
            to={user ? appHref : '/login'}
            className="text-sm px-4 py-2 rounded-lg border border-white/10 text-gray-300 hover:bg-white/5 transition-colors"
          >
            {user ? 'Open app' : 'Sign in'}
          </Link>
          <Link
            to={appHref}
            className="text-sm px-4 py-2 rounded-lg bg-teal-600 hover:bg-teal-500 font-medium transition-colors shadow-lg shadow-teal-600/25"
          >
            {user ? 'Dashboard' : 'Get started'}
          </Link>
        </nav>
      </header>

      {/* Hero — two-column on desktop */}
      <section className="relative z-10 px-6 pt-16 pb-20 max-w-6xl mx-auto">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-8 items-center">
          {/* Left: copy */}
          <div>
            <h1
              className="landing-fade-up text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight leading-[1.1]"
              style={{ animationDelay: '80ms' }}
            >
              AI trading intelligence{' '}
              <span className="bg-gradient-to-r from-teal-300 via-cyan-300 to-emerald-400 bg-clip-text text-transparent">
                you can explain
              </span>
            </h1>

            <p
              className="landing-fade-up mt-6 text-lg text-gray-400 max-w-xl leading-relaxed"
              style={{ animationDelay: '160ms' }}
            >
              Explainable BUY/HOLD/SELL signals for US and Egyptian equities — a 7-model
              ensemble and a fine-tuned forecasting foundation model, with SHAP attribution,
              calibrated confidence, and regime-aware risk guardrails.
            </p>

            <div
              className="landing-fade-up mt-10 flex flex-wrap gap-4"
              style={{ animationDelay: '240ms' }}
            >
              <Link
                to={appHref}
                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-teal-600 hover:bg-teal-500 font-semibold transition-all hover:shadow-xl hover:shadow-teal-600/30 hover:-translate-y-0.5"
              >
                Launch dashboard
                <span aria-hidden>→</span>
              </Link>
              <a
                href="#features"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-white/10 text-gray-300 hover:bg-white/5 transition-colors"
              >
                Explore features
              </a>
            </div>
          </div>

          {/* Right: floating signal card */}
          <div className="landing-fade-up lg:justify-self-end w-full max-w-md landing-float" style={{ animationDelay: '360ms' }}>
            <SignalCard />
          </div>
        </div>

        {/* Live ticker strip */}
        <div className="landing-fade-up mt-16 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03] backdrop-blur-sm" style={{ animationDelay: '440ms' }}>
          <div className="landing-ticker flex gap-8 py-3 px-4 text-sm font-mono text-gray-400">
            {[...TICKERS, ...TICKERS].map((t, i) => (
              <span key={`${t.sym}-${i}`} className="flex items-center gap-2 shrink-0">
                <span className="text-teal-300">{t.sym}</span>
                <span className={t.up ? 'text-emerald-400' : 'text-rose-400'}>
                  {t.up ? '▲' : '▼'} {t.chg}
                </span>
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="relative z-10 border-y border-white/5 bg-white/[0.02]">
        <div className="max-w-6xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
          {STATS.map(({ value, label }, i) => (
            <div key={label} className="landing-fade-up text-center" style={{ animationDelay: `${i * 60}ms` }}>
              <p className="text-3xl sm:text-4xl font-bold bg-gradient-to-b from-white to-gray-400 bg-clip-text text-transparent">
                {value}
              </p>
              <p className="text-sm text-gray-500 mt-1">{label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section id="features" className="relative z-10 px-6 py-24 max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">Built for serious research</h2>
          <p className="text-gray-400 mt-4 max-w-xl mx-auto">
            From feature engineering to meta-learner stacking and foundation-model forecasting —
            every layer is wired into one platform.
          </p>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f, i) => (
            <article
              key={f.title}
              className="landing-card group rounded-2xl border border-white/10 bg-gray-900/40 backdrop-blur-sm p-6 hover:border-teal-500/40 hover:bg-gray-900/60 transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-teal-900/20"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span className="inline-flex w-11 h-11 items-center justify-center rounded-xl bg-teal-500/10 border border-teal-500/20 text-2xl mb-4 group-hover:scale-110 transition-transform duration-300">{f.icon}</span>
              <h3 className="font-semibold text-lg mb-2">{f.title}</h3>
              <p className="text-sm text-gray-400 leading-relaxed">{f.desc}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Pipeline visual */}
      <section id="pipeline" className="relative z-10 px-6 py-20 border-t border-white/5">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-2xl sm:text-3xl font-bold text-center mb-3">Signal pipeline</h2>
          <p className="text-gray-400 text-center mb-12 max-w-xl mx-auto">
            Raw market data becomes an explainable, risk-checked signal in five stages.
          </p>
          <div className="flex flex-col md:flex-row items-stretch gap-3 md:gap-0">
            {['OHLCV + VIX', '25 Features', '7 Models + Meta', 'Calibrate + Risk', 'Signal Card'].map((step, i, arr) => (
              <div key={step} className="flex-1 flex items-center gap-3">
                <div className="flex-1 rounded-xl border border-white/10 bg-gradient-to-b from-white/5 to-transparent p-4 text-center landing-pipeline-step" style={{ animationDelay: `${i * 120}ms` }}>
                  <p className="text-xs text-teal-400 font-mono mb-1">Step {i + 1}</p>
                  <p className="text-sm font-medium">{step}</p>
                </div>
                {i < arr.length - 1 && (
                  <span className="hidden md:block text-teal-500/50 text-xl animate-pulse">→</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="relative z-10 px-6 py-24">
        <div className="max-w-3xl mx-auto text-center rounded-3xl border border-teal-500/20 bg-gradient-to-b from-teal-500/10 to-transparent p-12 landing-glow">
          <h2 className="text-3xl font-bold mb-4">Ready to explore signals?</h2>
          <p className="text-gray-400 mb-8 max-w-lg mx-auto">
            Sign in to the web dashboard or connect via the mobile app. No real trades —
            decision support only.
          </p>
          <Link
            to="/login"
            className="inline-flex px-8 py-3 rounded-xl bg-white text-gray-900 font-semibold hover:bg-gray-100 transition-colors hover:-translate-y-0.5"
          >
            Sign in to TradeBot
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-white/5 px-6 py-8 text-center text-xs text-gray-600">
        <p>NextGen TradeBot · Not financial advice</p>
      </footer>
    </div>
  )
}
