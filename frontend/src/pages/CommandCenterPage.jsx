import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import { CardSkeleton } from '../components/Skeleton'
import { AllocationDonut } from '../components/PortfolioIntelligence'
import DecisionExplorerModal from '../components/DecisionExplorerModal'

function HealthRing({ score }) {
  const color = score >= 80 ? '#14b8a6' : score >= 60 ? '#f59e0b' : '#ef4444'
  const r = 36
  const circ = 2 * Math.PI * r
  const offset = circ - (score / 100) * circ
  return (
    <div className="relative w-24 h-24 shrink-0">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 96 96">
        <circle cx="48" cy="48" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
        <circle
          cx="48" cy="48" r={r} fill="none" stroke={color} strokeWidth="8"
          strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-bold text-white">{score}</span>
        <span className="text-[9px] text-gray-500 uppercase">Health</span>
      </div>
    </div>
  )
}

function regimeColor(regime) {
  if (regime === 'BULL') return 'text-emerald-400'
  if (regime === 'BEAR') return 'text-red-400'
  return 'text-amber-400'
}

export default function CommandCenterPage() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [market, setMarket] = useState('us')
  const [exploreId, setExploreId] = useState(null)

  const load = () => {
    setLoading(true)
    client.get('/api/paper-trading/command-center', { params: { market } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [market])

  if (loading && !data) {
    return <div className="space-y-4"><CardSkeleton /><CardSkeleton /><CardSkeleton /></div>
  }

  const conf = data?.ai_confidence || {}
  const perf = data?.performance || {}
  const regime = data?.regime?.current_regime || '—'
  const advisor = data?.advisor || {}
  const analytics = data?.analytics || {}

  const advisorBorder = advisor.tone === 'critical'
    ? 'border-red-500/40 bg-red-500/5'
    : advisor.tone === 'warning'
    ? 'border-amber-500/40 bg-amber-500/5'
    : 'border-teal-500/30 bg-teal-500/5'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-white">Today&apos;s Portfolio</h1>
          <p className="text-sm text-gray-500 mt-1">Your daily command center — AI, risk, and performance at a glance</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={market}
            onChange={(e) => setMarket(e.target.value)}
            className="bg-gray-900/80 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-gray-300"
          >
            <option value="us">US Market</option>
            <option value="egx">EGX</option>
          </select>
          <button
            type="button"
            onClick={load}
            className="px-3 py-1.5 text-xs rounded-lg border border-white/10 text-gray-400 hover:text-white"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Top status strip */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-2 bg-gray-900/60 border border-white/10 rounded-xl p-5 flex items-center gap-5">
          <HealthRing score={data?.portfolio_health ?? 0} />
          <div className="flex-1 grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-[10px] text-gray-500 uppercase">AI Confidence</p>
              <p className={`font-semibold ${
                conf.label === 'HIGH' ? 'text-emerald-400' : conf.label === 'MEDIUM' ? 'text-amber-400' : 'text-red-400'
              }`}>
                {conf.pct != null ? `${conf.pct}% · ${conf.label}` : conf.label}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 uppercase">Market Regime</p>
              <p className={`font-semibold ${regimeColor(regime)}`}>{regime}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 uppercase">Meta-Learner</p>
              <p className="text-gray-200">{data?.meta_status?.loaded ? '✓ Live' : 'Fallback'}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 uppercase">Source</p>
              <p className="text-gray-200 capitalize">{perf.source || '—'} portfolio</p>
            </div>
          </div>
        </div>

        <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
          <p className="text-[10px] text-gray-500 uppercase mb-1">Today&apos;s Performance</p>
          <p className={`text-2xl font-bold ${(perf.daily_pl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {(perf.daily_pl || 0) >= 0 ? '+' : ''}${Number(perf.daily_pl || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
            <span className="text-base ml-2 opacity-80">
              ({(perf.daily_return_pct || 0) >= 0 ? '+' : ''}{(perf.daily_return_pct || 0).toFixed(2)}%)
            </span>
          </p>
          <p className="text-xs text-gray-500 mt-2">
            Portfolio ${Number(perf.portfolio_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </p>
        </div>

        <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
          <p className="text-[10px] text-gray-500 uppercase mb-2">Top AI Opportunities</p>
          {(data?.top_opportunities || []).length === 0 ? (
            <p className="text-xs text-gray-600">No BUY signals in the last 48h.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {data.top_opportunities.map((s) => (
                <span key={s.id || s.ticker} className="text-xs px-2 py-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
                  BUY {s.ticker}
                </span>
              ))}
            </div>
          )}
          <Link to="/app/signals" className="text-[10px] text-teal-400 hover:text-teal-300 mt-3 inline-block">
            Full signal feed →
          </Link>
        </div>
      </div>

      {/* AI Portfolio Advisor */}
      <div className={`rounded-xl border p-6 ${advisorBorder}`}>
        <h2 className="text-sm font-semibold text-white mb-3">{advisor.title || 'Portfolio Insight'}</h2>
        <div className="space-y-2 text-sm text-gray-300 leading-relaxed">
          {(advisor.paragraphs || []).map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
        {advisor.recommendation && (
          <p className="mt-4 text-sm font-medium text-teal-200 border-t border-white/10 pt-3">
            → {advisor.recommendation}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AllocationDonut
          title="Portfolio Allocation (Sectors)"
          data={analytics.sector_allocation}
          emptyHint="Allocate capital via Paper Trading to see sector breakdown."
        />
        <AllocationDonut
          title="Holdings"
          data={analytics.symbol_allocation}
          emptyHint="Symbol weights appear after your first rebalance."
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Recent trades */}
        <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Recent Trades</h3>
            <Link to="/app/paper-trading" className="text-[10px] text-teal-400">Paper Trading →</Link>
          </div>
          {(data?.recent_trades || []).length === 0 ? (
            <p className="text-xs text-gray-600">No trades yet — journal fills after meta rebalance.</p>
          ) : (
            <div className="space-y-2">
              {data.recent_trades.slice(0, 5).map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setExploreId(t.id)}
                  className="w-full flex items-center gap-2 text-xs border-b border-white/5 pb-2 hover:bg-white/5 rounded px-1 -mx-1 text-left"
                >
                  <span className={t.action === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>{t.action}</span>
                  <span className="text-white font-medium">{t.ticker}</span>
                  {t.meta_prob != null && <span className="text-gray-500">meta {(t.meta_prob * 100).toFixed(0)}%</span>}
                  <span className="ml-auto text-teal-500/80 text-[10px]">Explore →</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Alerts */}
        <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Alerts</h3>
          {(data?.alerts || []).length === 0 ? (
            <p className="text-xs text-gray-600">No active alerts.</p>
          ) : (
            <ul className="space-y-2">
              {data.alerts.map((a, i) => (
                <li key={i} className="text-xs flex gap-2">
                  <span className={
                    a.level === 'critical' ? 'text-red-400' : a.level === 'warning' ? 'text-amber-400' : 'text-gray-400'
                  }>•</span>
                  <span className="text-gray-300">{a.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Model health footer */}
      <div className="flex flex-wrap gap-4 text-[10px] text-gray-600 border-t border-white/5 pt-4">
        <span>EWMA: {data?.meta_status?.ewma_initialized ? 'initialized' : 'pending'}</span>
        <span>Holdings: {analytics.holdings_count ?? 0}</span>
        <span>Diversification: {analytics.diversification_score ?? '—'}</span>
        {analytics.portfolio_beta != null && <span>Beta: {analytics.portfolio_beta}</span>}
        {data?.as_of && <span className="ml-auto">Updated {new Date(data.as_of).toLocaleString()}</span>}
      </div>

      <DecisionExplorerModal tradeId={exploreId} onClose={() => setExploreId(null)} />
    </div>
  )
}
