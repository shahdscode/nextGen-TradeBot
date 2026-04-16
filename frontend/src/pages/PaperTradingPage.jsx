import { useState, useEffect } from 'react'
import client from '../api/client'
import { CardSkeleton } from '../components/Skeleton'

export default function PaperTradingPage() {
  const [status, setStatus] = useState(null)
  const [portfolio, setPortfolio] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [runId, setRunId] = useState('paper-mt5-demo')
  const [symbols, setSymbols] = useState('BTCUSDm,ETHUSDm,EURUSD')
  const [timeframe, setTimeframe] = useState('M15')

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
  }, [])

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

      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6 max-w-3xl">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">MT5 Paper Session</h2>
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
