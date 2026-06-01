import { useState, useEffect } from 'react'
import client from '../api/client'

const MODEL_KEYS = ['xgboost', 'lstm', 'ppo', 'a2c', 'ddpg', 'td3', 'sac']
const MODEL_COLORS = {
  xgboost: '#6366f1',
  lstm:    '#8b5cf6',
  ppo:     '#ec4899',
  a2c:     '#f59e0b',
  ddpg:    '#10b981',
  td3:     '#3b82f6',
  sac:     '#ef4444',
}

export default function ModelWeightsPage() {
  const [weights, setWeights]   = useState(null)
  const [history, setHistory]   = useState([])
  const [scores,  setScores]    = useState([])
  const [days,    setDays]      = useState(30)
  const [loading, setLoading]   = useState(true)
  const [error,   setError]     = useState(null)

  const fetchAll = () => {
    setLoading(true)
    setError(null)
    Promise.all([
      client.get('/api/ml/weights/current').catch(() => null),
      client.get(`/api/ml/weights/history?days=${days}`).catch(() => null),
      client.get('/api/ml/performance/scores').catch(() => null),
    ]).then(([w, h, s]) => {
      setWeights(w?.data || null)
      setHistory(h?.data?.history || [])
      setScores(s?.data?.recent_scores || [])
    }).catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchAll() }, [days])

  const method = weights?.method || 'not_initialized'
  const isLive = method !== 'not_initialized' && method !== 'fixed_fallback'

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Model Weights</h1>
          <p className="text-sm text-gray-500 mt-1">
            Adaptive EWMA fusion weights — updated daily based on prediction accuracy
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${
            isLive ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${isLive ? 'bg-green-500' : 'bg-amber-500'}`} />
            {isLive ? 'EWMA Live' : 'Fixed Fallback'}
          </span>
          <button onClick={fetchAll}
            className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50">
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Current Weights Bar Chart */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Current Fusion Weights</h2>
        {loading ? (
          <div className="space-y-3">
            {MODEL_KEYS.map(k => (
              <div key={k} className="h-8 bg-gray-100 rounded animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {MODEL_KEYS.map(key => {
              const w = weights?.[key] ?? (1 / MODEL_KEYS.length)
              const pct = (w * 100).toFixed(1)
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="w-16 text-xs font-medium text-gray-600 text-right uppercase">
                    {key}
                  </span>
                  <div className="flex-1 bg-gray-100 rounded-full h-5 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500 flex items-center justify-end pr-2"
                      style={{ width: `${Math.max(pct, 3)}%`, backgroundColor: MODEL_COLORS[key] }}
                    >
                      <span className="text-[10px] font-bold text-white">{pct}%</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
        {weights?.updated_at && (
          <p className="text-xs text-gray-400 mt-4">
            Last updated: {new Date(weights.updated_at).toLocaleString()}
          </p>
        )}
      </div>

      {/* Weight History Chart */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-700">Weight Evolution</h2>
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>

        {history.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <div className="text-4xl mb-3">📊</div>
            <p className="text-sm font-medium">No weight history yet</p>
            <p className="text-xs mt-1">Run Step 6 (EWMA tracker) to populate this chart</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-gray-500 font-medium">Date</th>
                  {MODEL_KEYS.map(k => (
                    <th key={k} className="text-right py-2 font-medium" style={{ color: MODEL_COLORS[k] }}>
                      {k.toUpperCase()}
                    </th>
                  ))}
                  <th className="text-right py-2 text-gray-500 font-medium">Top Model</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 30).map((row, i) => (
                  <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-1.5 text-gray-600">{row.date}</td>
                    {MODEL_KEYS.map(k => (
                      <td key={k} className="py-1.5 text-right tabular-nums"
                        style={{ color: MODEL_COLORS[k] }}>
                        {((row[k] ?? 0) * 100).toFixed(1)}%
                      </td>
                    ))}
                    <td className="py-1.5 text-right font-medium text-gray-700">
                      {row.top_model || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent EWMA Scores */}
      <div className="bg-white border border-gray-200 rounded-xl p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Recent EWMA Scores</h2>
        {scores.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-sm">
            No scores yet — run the EWMA tracker after meta-learner training
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-gray-500">Date</th>
                  <th className="text-left py-2 text-gray-500">Model</th>
                  <th className="text-right py-2 text-gray-500">EWMA Score</th>
                  <th className="text-right py-2 text-gray-500">Daily Correct</th>
                  <th className="text-right py-2 text-gray-500">Weight</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s, i) => (
                  <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-1.5 text-gray-600">{s.date}</td>
                    <td className="py-1.5 font-medium uppercase"
                      style={{ color: MODEL_COLORS[s.model_key] || '#6b7280' }}>
                      {s.model_key}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">{(s.ewma_score * 100).toFixed(1)}%</td>
                    <td className="py-1.5 text-right">
                      {s.daily_correct === 1 ? '✓' : s.daily_correct === 0 ? '✗' : '—'}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">{(s.weight * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
