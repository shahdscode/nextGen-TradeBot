import { useState, useEffect } from 'react'
import client from '../api/client'
import { CardSkeleton } from '../components/skeleton'

export default function PaperTradingPage() {
  const [status, setStatus] = useState(null)
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('paper-mt5-demo')
  const [symbols, setSymbols] = useState('BTCUSDm,ETHUSDm,EURUSD')
  const [timeframe, setTimeframe] = useState('M15')
  const [rlRuns, setRlRuns] = useState([])
  const [modelRunId, setModelRunId] = useState('')
  const [rebal, setRebal] = useState(null)

  const refreshData = () => {
    return Promise.all([
      client.get('/api/paper-trading/status'),
      client.get('/api/paper-trading/portfolio'),
    ]).then(([s, p]) => {
      setStatus(s.data)
      setPortfolio(p.data)
    })
  }

  useEffect(() => {
    refreshData().finally(() => setLoading(false))
    // Load RL runs (the only models that can trade the DOW30 portfolio live)
    client.get('/api/train/runs').then(r => {
      const rl = r.data.filter(x => ['ppo','a2c','ddpg','td3','sac'].includes(x.algorithm)
                                    && x.status === 'done')
      setRlRuns(rl)
      if (rl.length) setModelRunId(rl[0].run_id)
    }).catch(() => {})
  }, [])

  const handleRebalance = async () => {
    if (!modelRunId) return
    setBusy(true)
    setRebal(null)
    try {
      const r = await client.post('/api/paper-trading/rebalance', null, {
        params: { run_id: modelRunId },
      })
      setRebal(r.data)
      await refreshData()
    } catch (e) {
      setRebal({ ok: false, message: e.response?.data?.detail || 'Rebalance failed' })
    } finally {
      setBusy(false)
    }
  }

  // ── Alpaca paper broker ──────────────────────────────────────────────────
  const [alpaca, setAlpaca] = useState(null)
  const [alpacaPf, setAlpacaPf] = useState(null)
  const [alpacaMode, setAlpacaMode] = useState('rl')
  const [alpacaResult, setAlpacaResult] = useState(null)

  const refreshAlpaca = () => Promise.all([
    client.get('/api/paper-trading/alpaca/status').then(r => setAlpaca(r.data)).catch(() => {}),
    client.get('/api/paper-trading/alpaca/portfolio').then(r => setAlpacaPf(r.data)).catch(() => {}),
  ])
  useEffect(() => { refreshAlpaca() }, [])

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

  const handleStart = async () => {
    setBusy(true)
    try {
      await client.post('/api/paper-trading/start', null, {
        params: { run_id: runId, symbols, timeframe },
      })
      await refreshData()
    } finally {
      setBusy(false)
    }
  }

  const handleStop = async () => {
    setBusy(true)
    try {
      await client.post('/api/paper-trading/stop')
      await refreshData()
    } finally {
      setBusy(false)
    }
  }

  if (loading) return (
    <div className="space-y-4">
      <CardSkeleton /><CardSkeleton />
    </div>
  )

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Paper Trading</h1>
      <p className="text-sm text-gray-500 mb-6">Simulated live trading via MT5 Gateway</p>

      {/* Status banner */}
      <div className={`rounded-xl p-4 mb-6 flex items-center gap-3 border ${
        status?.configured
          ? 'bg-green-50 border-green-200 text-green-800'
          : 'bg-amber-50 border-amber-200 text-amber-800'
      }`}>
        <div className={`w-2 h-2 rounded-full ${status?.configured ? 'bg-green-500' : 'bg-amber-500'}`} />
        <p className="text-sm">{status?.message}</p>
      </div>

      {/* Model-driven live trading on DOW30 (Yahoo feed, no MT5 needed) */}
      <div className="bg-white border border-indigo-200 rounded-xl p-6 mb-6 max-w-3xl">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="text-sm font-semibold text-gray-900">Model-Driven Live Trading — DOW 30</h2>
          <span className="text-[10px] bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
            live Yahoo feed
          </span>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Runs a trained RL model on live DOW30 daily bars and rebalances the paper
          portfolio to the allocation the model would hold right now. No MT5 required.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <select
            value={modelRunId}
            onChange={(e) => setModelRunId(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          >
            {rlRuns.length === 0 && <option value="">No RL runs available</option>}
            {rlRuns.map((r) => {
              const ck = r.data_job_id?.match(/ckpt(\d)/)?.[1]
              const sh = r.metrics?.sharpe_ratio
              return (
                <option key={r.run_id} value={r.run_id}>
                  {r.algorithm.toUpperCase()}{ck ? ` · ckpt${ck}` : ''}
                  {sh != null ? ` · Sharpe ${sh.toFixed(2)}` : ''} · {r.run_id.slice(0, 8)}
                </option>
              )
            })}
          </select>
          <button
            onClick={handleRebalance}
            disabled={busy || !modelRunId}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? 'Running model…' : 'Run Model on Live DOW30'}
          </button>
        </div>
        {rebal && (
          <div className={`text-xs rounded-lg p-3 ${rebal.ok ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-700'}`}>
            {rebal.ok
              ? `✓ ${rebal.message} — invested $${rebal.invested?.toLocaleString()} across ${rebal.positions_held} stocks (as of ${rebal.as_of})`
              : `✗ ${rebal.message}`}
          </div>
        )}
      </div>

      {/* Alpaca paper broker — real US-equity fills */}
      <div className="bg-white border border-emerald-200 rounded-xl p-6 mb-6 max-w-3xl">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="text-sm font-semibold text-gray-900">Alpaca Paper Broker — real fills</h2>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
            alpaca?.configured ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
            {alpaca?.configured ? (alpaca?.market_open ? 'market open' : 'market closed') : 'not configured'}
          </span>
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
        <div className="flex items-center gap-2 mb-3">
          <select value={alpacaMode} onChange={e => setAlpacaMode(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
            <option value="rl">Single RL model (selected above)</option>
            <option value="meta">Meta-learner ensemble (all 7)</option>
          </select>
          <button onClick={handleAlpacaRebalance} disabled={busy || !alpaca?.configured}
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

      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6 max-w-3xl">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">MT5 Paper Session (forex/crypto)</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          <input
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            placeholder="run id"
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="BTCUSDm,ETHUSDm,EURUSD"
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          />
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
          >
            {['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'].map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleStart}
            disabled={!status?.configured || busy}
            className="px-4 py-2 text-sm rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-50"
          >
            Start
          </button>
          <button
            onClick={handleStop}
            disabled={!status?.configured || busy}
            className="px-4 py-2 text-sm rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            Stop
          </button>
          <button
            onClick={refreshData}
            disabled={busy}
            className="px-4 py-2 text-sm rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            Refresh
          </button>
          <span className="text-xs text-gray-500">
            {status?.running ? 'Running' : 'Stopped'}
          </span>
        </div>
      </div>

      {!status?.configured && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6 max-w-lg">
          <h2 className="text-sm font-semibold text-gray-900 mb-2">How to enable paper trading</h2>
          <ol className="text-sm text-gray-600 space-y-1 list-decimal list-inside">
            <li>Ensure your MT5 gateway service is reachable</li>
            <li>Generate or copy your MT5 gateway API key</li>
            <li>Add to your <code className="bg-gray-100 px-1 rounded">.env</code> file:</li>
          </ol>
          <pre className="mt-3 bg-gray-900 text-gray-100 rounded-lg p-3 text-xs overflow-x-auto">
{`MT5_GATEWAY_URL=http://51.21.209.128:8000
MT5_API_KEY=your_key_here`}
          </pre>
          <p className="text-xs text-gray-400 mt-2">Restart Docker after saving the .env file</p>
        </div>
      )}

      {/* Portfolio summary */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Portfolio value</p>
          <p className="text-2xl font-semibold text-gray-900">
            ${portfolio?.portfolio_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}
          </p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Cash</p>
          <p className="text-2xl font-semibold text-gray-900">
            ${portfolio?.cash?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '—'}
          </p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">Daily return</p>
          <p className={`text-2xl font-semibold ${
            portfolio?.daily_return > 0 ? 'text-green-600' : portfolio?.daily_return < 0 ? 'text-red-600' : 'text-gray-900'
          }`}>
            {portfolio?.daily_return != null
              ? `${portfolio.daily_return >= 0 ? '+' : ''}${(portfolio.daily_return * 100).toFixed(3)}%`
              : '—'}
          </p>
        </div>
      </div>

      {/* Positions table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200">
          <h2 className="text-sm font-medium text-gray-700">Positions</h2>
        </div>
        {!portfolio?.positions?.length ? (
          <div className="p-8 text-center text-sm text-gray-400">
            {status?.configured ? 'No open positions' : 'Configure MT5 gateway to see positions'}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Symbol</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Qty</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Market Value</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Unrealized P&L</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Return</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {portfolio.positions.map((p) => (
                <tr key={p.symbol} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-semibold text-gray-900">{p.symbol}</td>
                  <td className="px-4 py-3 text-right text-gray-600">{p.qty}</td>
                  <td className="px-4 py-3 text-right text-gray-600">
                    ${p.market_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                  <td className={`px-4 py-3 text-right font-medium ${p.unrealized_pl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {p.unrealized_pl >= 0 ? '+' : ''}${p.unrealized_pl?.toFixed(2)}
                  </td>
                  <td className={`px-4 py-3 text-right font-medium ${p.unrealized_plpc >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {p.unrealized_plpc >= 0 ? '+' : ''}{(p.unrealized_plpc * 100).toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
