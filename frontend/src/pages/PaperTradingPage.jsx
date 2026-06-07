import { useState, useEffect } from 'react'
import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip } from 'recharts'
import client from '../api/client'
import { CardSkeleton } from '../components/skeleton'

export default function PaperTradingPage() {
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [rlRuns, setRlRuns] = useState([])
  const [modelRunId, setModelRunId] = useState('')

  // ── Alpaca paper broker ──────────────────────────────────────────────────
  const [alpaca, setAlpaca] = useState(null)
  const [alpacaPf, setAlpacaPf] = useState(null)
  const [alpacaMode, setAlpacaMode] = useState('rl')
  const [alpacaResult, setAlpacaResult] = useState(null)

  const refreshAlpaca = () => Promise.all([
    client.get('/api/paper-trading/alpaca/status').then(r => setAlpaca(r.data)).catch(() => {}),
    client.get('/api/paper-trading/alpaca/portfolio').then(r => setAlpacaPf(r.data)).catch(() => {}),
  ])

  useEffect(() => {
    refreshAlpaca().finally(() => setLoading(false))
    // RL runs power the "single model" rebalance mode
    client.get('/api/train/runs').then(r => {
      const rl = r.data.filter(x => ['ppo','a2c','ddpg','td3','sac'].includes(x.algorithm)
                                    && x.status === 'done')
      setRlRuns(rl)
      if (rl.length) setModelRunId(rl[0].run_id)
    }).catch(() => {})
  }, [])

  const handleAlpacaRebalance = async () => {
    setBusy(true); setAlpacaResult(null)
    try {
      const params = alpacaMode === 'meta' ? { mode: 'meta' } : { mode: 'rl', run_id: modelRunId }
      const r = await client.post('/api/paper-trading/alpaca/rebalance', null, { params })
      setAlpacaResult(r.data)
      await refreshAlpaca()
    } catch (e) {
      setAlpacaResult({ ok: false, note: e.response?.data?.detail || 'Alpaca rebalance failed' })
    } finally { setBusy(false) }
  }

  if (loading) return (
    <div className="space-y-4">
      <CardSkeleton /><CardSkeleton />
    </div>
  )

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Paper Trading</h1>
      <p className="text-sm text-gray-500 mb-6">Model-driven live paper trading on DOW 30 via Alpaca</p>

      {/* Alpaca paper broker — real US-equity fills */}
      <div className="bg-white border border-emerald-200 rounded-xl p-6 mb-6 max-w-3xl">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="text-sm font-semibold text-gray-900">Alpaca Paper Broker — real fills</h2>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
            alpaca?.configured ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
            {alpaca?.configured ? (alpaca?.market_open ? 'market open' : 'market closed') : 'not configured'}
          </span>
          {alpacaPf?.drawdown != null && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              alpacaPf.drawdown_breached ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}`}>
              {alpacaPf.drawdown_breached ? '⚠ risk halt' : `drawdown ${(alpacaPf.drawdown*100).toFixed(1)}%`}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Submits real orders to your free Alpaca paper account (US equities = DOW30).
          The model picks the allocation; Alpaca executes and tracks positions + P&L.
        </p>
        {alpaca?.configured && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Equity</div>
              <div className="text-lg font-bold text-gray-900">
                ${Number(alpaca.equity).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Total Return</div>
              <div className={`text-lg font-bold ${(alpacaPf?.total_return ?? 0) >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                {alpacaPf?.total_return != null
                  ? `${alpacaPf.total_return >= 0 ? '+' : ''}${(alpacaPf.total_return * 100).toFixed(2)}%`
                  : '—'}
              </div>
              <div className="text-[10px] text-gray-400">
                {alpacaPf?.total_pl != null
                  ? `${alpacaPf.total_pl >= 0 ? '+' : ''}$${alpacaPf.total_pl.toLocaleString(undefined,{maximumFractionDigits:0})} since start`
                  : ''}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Cash</div>
              <div className="text-lg font-bold text-gray-900">
                ${Number(alpaca.cash).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Buying Power</div>
              <div className="text-lg font-bold text-gray-900">
                ${Number(alpaca.buying_power).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <select value={alpacaMode} onChange={e => setAlpacaMode(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
            <option value="rl">Single RL model</option>
            <option value="meta">Meta-learner ensemble (all 7)</option>
          </select>
          {alpacaMode === 'rl' && (
            <select value={modelRunId} onChange={e => setModelRunId(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
              {rlRuns.length === 0 && <option value="">No RL runs</option>}
              {rlRuns.map((r) => {
                const ck = r.data_job_id?.match(/ckpt(\d)/)?.[1]
                const sh = r.metrics?.sharpe_ratio
                return (
                  <option key={r.run_id} value={r.run_id}>
                    {r.algorithm.toUpperCase()}{ck ? ` · ckpt${ck}` : ''}
                    {sh != null ? ` · Sharpe ${sh.toFixed(2)}` : ''}
                  </option>
                )
              })}
            </select>
          )}
          <button onClick={handleAlpacaRebalance}
            disabled={busy || !alpaca?.configured || (alpacaMode === 'rl' && !modelRunId)}
            className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
            {busy ? 'Submitting…' : 'Rebalance Alpaca with Model'}
          </button>
          <button onClick={refreshAlpaca}
            className="px-3 py-2 text-xs rounded-lg border border-gray-300 hover:bg-gray-50">Refresh</button>
        </div>
        {alpacaResult && (
          <div className={`text-xs rounded-lg p-3 mb-3 ${alpacaResult.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>
            {alpacaResult.ok
              ? `✓ ${alpacaResult.model_message} — ${alpacaResult.n_orders} orders submitted. ${alpacaResult.note}`
              : `✗ ${alpacaResult.note}`}
          </div>
        )}
        {alpacaPf?.equity_curve?.length > 2 && (
          <div className="mb-4">
            <div className="text-xs text-gray-500 mb-1">Equity curve (since inception)</div>
            <ResponsiveContainer width="100%" height={140}>
              <LineChart data={alpacaPf.equity_curve.map((v, i) => ({ i, equity: v }))}>
                <YAxis domain={['dataMin', 'dataMax']} hide />
                <Tooltip formatter={(v) => `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`}
                         labelFormatter={() => ''} />
                <Line type="monotone" dataKey="equity" stroke="#059669" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {alpacaPf?.positions?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-gray-100 text-gray-400">
                <th className="text-left py-1">Symbol</th><th className="text-right">Qty</th>
                <th className="text-right">Price</th><th className="text-right">Mkt Val</th><th className="text-right">P&L</th>
              </tr></thead>
              <tbody>
                {alpacaPf.positions.map(p => (
                  <tr key={p.symbol} className="border-b border-gray-50">
                    <td className="py-1 font-medium">{p.symbol}</td>
                    <td className="text-right">{p.qty.toFixed(2)}</td>
                    <td className="text-right">${p.current_price.toFixed(2)}</td>
                    <td className="text-right">${p.market_value.toFixed(0)}</td>
                    <td className={`text-right ${p.unrealized_pl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      ${p.unrealized_pl.toFixed(2)}
                    </td>
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
