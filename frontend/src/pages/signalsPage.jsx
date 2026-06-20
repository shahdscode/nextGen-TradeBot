import { useState, useEffect } from 'react'
import client from '../api/client'
import SignalCard from '../components/signalCard'
import { CardSkeleton } from '../components/Skeleton'

const MARKETS = [
  { value: 'us', label: 'US Market' },
  { value: 'egx', label: 'EGX (Egypt)' },
  { value: 'all', label: 'All Markets' },
]

const ACTIONS = [
  { value: '', label: 'All' },
  { value: 'BUY', label: 'Buy' },
  { value: 'SELL', label: 'Sell' },
  { value: 'HOLD', label: 'Hold' },
]

export default function SignalsPage() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)
  const [regime, setRegime] = useState(null)
  const [market, setMarket] = useState('us')
  const [actionFilter, setActionFilter] = useState('')

  const fetchSignals = () => {
    setLoading(true)
    const params = { market, limit: 30, ...(actionFilter ? { action: actionFilter } : {}) }
    client.get('/api/signals/top', { params })
      .then((r) => setSignals(r.data))
      .catch(() => setSignals([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    client.get('/api/market/regime', { params: { market } })
      .then((r) => setRegime(r.data))
      .catch(() => {})
  }, [market])

  useEffect(() => { fetchSignals() }, [market, actionFilter])

  const filtered = actionFilter ? signals.filter((s) => s.action === actionFilter) : signals

  return (
    <div>
      {/* Regime Banner */}
      {regime?.current_regime && (
        <div className={`mb-6 rounded-xl px-5 py-3 border flex items-center justify-between ${
          regime.current_regime === 'BULL'
            ? 'bg-emerald-500/10 border-emerald-500/30'
            : regime.current_regime === 'BEAR'
            ? 'bg-red-500/10 border-red-500/30'
            : 'bg-amber-500/10 border-amber-500/30'
        }`}>
          <div className="flex items-center gap-3">
            <span className={`text-lg font-bold ${
              regime.current_regime === 'BULL' ? 'text-emerald-400' : regime.current_regime === 'BEAR' ? 'text-red-400' : 'text-amber-400'
            }`}>
              {regime.current_regime} REGIME
            </span>
            <span className="text-xs text-gray-400">Active market context for all signals</span>
          </div>
          {regime.weights && (
            <div className="hidden sm:flex gap-4 text-xs text-gray-400">
              <span>XGB {Math.round(regime.weights.xgb * 100)}%</span>
              <span>LSTM {Math.round(regime.weights.lstm * 100)}%</span>
              <span>PPO {Math.round(regime.weights.ppo * 100)}%</span>
            </div>
          )}
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Signals</h1>
          <p className="text-sm text-gray-500 mt-1">{filtered.length} active signals</p>
        </div>
        <button onClick={fetchSignals} className="text-xs text-gray-500 hover:text-gray-900 px-3 py-1.5 border border-gray-200 rounded-lg">
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <div className="flex gap-1">
          {MARKETS.map((m) => (
            <button
              key={m.value}
              onClick={() => setMarket(m.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                market === m.value ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {ACTIONS.map((a) => (
            <button
              key={a.value}
              onClick={() => setActionFilter(a.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                actionFilter === a.value ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      {/* Signal Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 bg-gray-50 rounded-2xl border border-gray-100">
          <p className="text-gray-400">No signals available yet.</p>
          <p className="text-sm text-gray-400 mt-1">An admin needs to generate signals first.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((s) => <SignalCard key={s.id} signal={s} />)}
        </div>
      )}
    </div>
  )
}
