import { useState, useEffect } from 'react'
import client from '../api/client'

const MODEL_KEYS = ['xgboost', 'lstm', 'ppo', 'a2c', 'ddpg', 'td3', 'sac']
const MODEL_COLORS = {
  xgboost: '#6366f1', lstm: '#8b5cf6', ppo: '#ec4899',
  a2c: '#f59e0b', ddpg: '#10b981', td3: '#3b82f6', sac: '#ef4444',
}
const REGIME_COLORS = { BULL: '#10b981', BEAR: '#ef4444', SIDEWAYS: '#f59e0b' }

export default function ModelPerformancePage() {
  const [runs,    setRuns]    = useState([])
  const [weights, setWeights] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      client.get('/api/train/runs').catch(() => ({ data: [] })),
      client.get('/api/ml/weights/current').catch(() => null),
    ]).then(([r, w]) => {
      setRuns(r.data)
      setWeights(w?.data || null)
    }).finally(() => setLoading(false))
  }, [])

  // Group runs by algorithm — get best per algo (highest sharpe)
  const bestByAlgo = MODEL_KEYS.reduce((acc, key) => {
    const algoRuns = runs.filter(r => r.algorithm === key && r.status === 'done')
    if (algoRuns.length === 0) return acc
    algoRuns.sort((a, b) => (b.metrics?.sharpe_ratio ?? -Infinity) - (a.metrics?.sharpe_ratio ?? -Infinity))
    acc[key] = algoRuns[0]
    return acc
  }, {})

  // Checkpoint runs for the timeline
  const checkpointRuns = runs.filter(r =>
    r.data_job_id?.startsWith('step4_ckpt') && r.status === 'done'
  ).sort((a, b) => new Date(a.created_at) - new Date(b.created_at))

  const ckptGroups = checkpointRuns.reduce((acc, r) => {
    const ckpt = r.data_job_id?.match(/ckpt(\d)/)?.[1] || '?'
    if (!acc[ckpt]) acc[ckpt] = []
    acc[ckpt].push(r)
    return acc
  }, {})

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Model Performance</h1>
        <p className="text-sm text-gray-500 mt-1">
          Comparative performance across all 7 base models and checkpoints
        </p>
      </div>

      {/* Best-per-algo summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
        {MODEL_KEYS.map(key => {
          const run = bestByAlgo[key]
          const m   = run?.metrics || {}
          const w   = weights?.[key]
          return (
            <div key={key} className="bg-white border border-gray-200 rounded-xl p-3">
              <div className="text-xs font-bold uppercase mb-2" style={{ color: MODEL_COLORS[key] }}>
                {key}
              </div>
              {run ? (
                <>
                  <div className="text-lg font-bold text-gray-900">
                    {m.sharpe_ratio != null ? m.sharpe_ratio.toFixed(2) : '—'}
                  </div>
                  <div className="text-[10px] text-gray-400">Sharpe</div>
                  {m.total_return != null && (
                    <div className={`text-xs font-medium mt-1 ${m.total_return >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {m.total_return >= 0 ? '+' : ''}{(m.total_return * 100).toFixed(1)}%
                    </div>
                  )}
                  {w != null && (
                    <div className="text-[10px] text-gray-400 mt-1">
                      Weight: {(w * 100).toFixed(1)}%
                    </div>
                  )}
                </>
              ) : (
                <div className="text-xs text-gray-300 mt-2">Not trained</div>
              )}
            </div>
          )
        })}
      </div>

      {/* Full comparison table */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Full Performance Comparison</h2>
        {loading ? (
          <div className="space-y-2">
            {[1,2,3,4,5].map(i => (
              <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />
            ))}
          </div>
        ) : runs.filter(r => r.status === 'done').length === 0 ? (
          <div className="text-center py-10 text-gray-400 text-sm">No completed runs yet</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-gray-400 font-medium">Algorithm</th>
                  <th className="text-left py-2 text-gray-400 font-medium">Checkpoint</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Sharpe</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Sortino</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Calmar</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Max DD</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Win Rate</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Return</th>
                  <th className="text-right py-2 text-gray-400 font-medium">vs B&H</th>
                  <th className="text-right py-2 text-gray-400 font-medium">T/day</th>
                  <th className="text-right py-2 text-gray-400 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {runs
                  .filter(r => r.status === 'done')
                  .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
                  .map((r, i) => {
                    const m    = r.metrics || {}
                    const ckpt = r.data_job_id?.match(/ckpt(\d)/)?.[1]
                    const isRL = ['ppo','a2c','ddpg','td3','sac'].includes(r.algorithm)
                    return (
                      <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                        <td className="py-2 font-medium uppercase"
                          style={{ color: MODEL_COLORS[r.algorithm] || '#6b7280' }}>
                          {r.algorithm}
                        </td>
                        <td className="py-2 text-gray-500">
                          {ckpt ? `Ckpt ${ckpt}` : isRL ? 'Legacy' : 'Full'}
                        </td>
                        <td className={`py-2 text-right tabular-nums font-medium ${
                          (m.sharpe_ratio ?? 0) >= 1 ? 'text-green-600' :
                          (m.sharpe_ratio ?? 0) >= 0 ? 'text-gray-700' : 'text-red-500'}`}>
                          {m.sharpe_ratio != null ? m.sharpe_ratio.toFixed(3) : '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums text-gray-600">
                          {m.sortino_ratio != null ? m.sortino_ratio.toFixed(3) : '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums text-gray-600">
                          {m.calmar_ratio != null ? m.calmar_ratio.toFixed(3) : '—'}
                        </td>
                        <td className={`py-2 text-right tabular-nums ${
                          (m.max_drawdown ?? 0) < -0.2 ? 'text-red-500' : 'text-gray-600'}`}>
                          {m.max_drawdown != null ? `${(m.max_drawdown*100).toFixed(1)}%` : '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums text-gray-600">
                          {m.win_rate != null ? `${(m.win_rate*100).toFixed(1)}%` : '—'}
                        </td>
                        <td className={`py-2 text-right tabular-nums font-medium ${
                          (m.total_return ?? 0) >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                          {m.total_return != null
                            ? `${m.total_return >= 0 ? '+' : ''}${(m.total_return*100).toFixed(1)}%`
                            : '—'}
                        </td>
                        <td className={`py-2 text-right tabular-nums ${
                          (m.vs_buyhold ?? 0) >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                          {m.vs_buyhold != null
                            ? `${m.vs_buyhold >= 0 ? '+' : ''}${(m.vs_buyhold*100).toFixed(1)}%`
                            : '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums text-gray-500">
                          {m.trades_per_day != null ? m.trades_per_day.toFixed(1) : '—'}
                        </td>
                        <td className="py-2 text-right text-gray-400">
                          {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                        </td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Checkpoint progress */}
      {Object.keys(ckptGroups).length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">
            3-Checkpoint Expanding Window Training
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {['1','2','3'].map(ckpt => {
              const ckptRuns = ckptGroups[ckpt] || []
              const labels   = ['2019–2021 → signals 2022', '2019–2022 → signals 2023', '2019–2023 → signals 2024']
              return (
                <div key={ckpt} className={`border rounded-xl p-4 ${
                  ckptRuns.length > 0 ? 'border-green-200 bg-green-50' : 'border-gray-200 bg-gray-50'
                }`}>
                  <div className="flex items-center gap-2 mb-3">
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
                      ckptRuns.length > 0 ? 'bg-green-500 text-white' : 'bg-gray-300 text-gray-500'
                    }`}>{ckpt}</span>
                    <span className="text-xs font-medium text-gray-700">
                      Checkpoint {ckpt}
                    </span>
                    {ckptRuns.length > 0 && (
                      <span className="ml-auto text-xs text-green-600 font-medium">
                        {ckptRuns.length}/5 models
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-gray-500 mb-3">{labels[parseInt(ckpt)-1]}</p>
                  <div className="space-y-1">
                    {MODEL_KEYS.filter(k => ['ppo','a2c','ddpg','td3','sac'].includes(k)).map(key => {
                      const run = ckptRuns.find(r => r.algorithm === key)
                      return (
                        <div key={key} className="flex items-center justify-between">
                          <span className="text-xs uppercase font-medium"
                            style={{ color: MODEL_COLORS[key] }}>{key}</span>
                          {run ? (
                            <span className="text-xs text-green-600">
                              Sharpe {run.metrics?.sharpe_ratio?.toFixed(2) ?? '✓'}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-300">Pending</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
