import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import client from '../api/client'
import EquityCurveChart from '../components/EquityCurveChart'
import MetricsCard from '../components/MetricsCard'
import JobStatusBadge from '../components/JobStatusBadge'
import { ChartSkeleton, CardSkeleton } from '../components/Skeleton'

const FORMAT_CURRENCY = (v) =>
  v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'

const ACTION_BADGE = {
  buy:  'bg-green-100 text-green-700',
  sell: 'bg-red-100 text-red-700',
  hold: 'bg-gray-100 text-gray-500',
}

export default function BacktestPage() {
  const [searchParams] = useSearchParams()
  const [runs, setRuns]                   = useState([])
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get('run_id') || '')
  const [testStart, setTestStart]         = useState('2023-01-01')
  const [testEnd, setTestEnd]             = useState('2023-12-31')
  const [initialCapital, setInitialCapital] = useState('100000')
  const [showTrades, setShowTrades]       = useState(true)
  const [backtestId, setBacktestId]       = useState(null)
  const [backtestStatus, setBacktestStatus] = useState(null)
  const [result, setResult]               = useState(null)
  const [submitting, setSubmitting]       = useState(false)
  const [tradeFilter, setTradeFilter]     = useState('all')

  useEffect(() => {
    client.get('/api/train/runs')
      .then((r) => setRuns(r.data.filter((r) => r.status === 'done')))
  }, [])

  // Poll backtest status
  useEffect(() => {
    if (!backtestId || backtestStatus === 'done' || backtestStatus === 'failed') return
    const timer = setInterval(async () => {
      const r = await client.get(`/api/backtest/${backtestId}`)
      setBacktestStatus(r.data.status)
      if (r.data.status === 'done') {
        clearInterval(timer)
        setResult(r.data)
        toast.success('Backtest complete!')
      }
      if (r.data.status === 'failed') {
        clearInterval(timer)
        toast.error(r.data.error || 'Backtest failed')
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [backtestId, backtestStatus])

  const handleSubmit = async () => {
    if (!selectedRunId) return toast.error('Select a training run')
    const capital = parseFloat(initialCapital.replace(/,/g, ''))
    if (isNaN(capital) || capital <= 0) return toast.error('Enter a valid starting capital')
    setResult(null)
    setSubmitting(true)
    try {
      const r = await client.post('/api/backtest', {
        run_id: selectedRunId,
        test_start: testStart,
        test_end: testEnd,
        initial_capital: capital,
      })
      setBacktestId(r.data.backtest_id)
      setBacktestStatus('pending')
    } finally {
      setSubmitting(false)
    }
  }

  const selectedRun = runs.find((r) => r.run_id === selectedRunId)
  const loading = (backtestStatus === 'running' || backtestStatus === 'pending') && !result

  const curveData = result ? [{
    label: selectedRun?.algorithm?.toUpperCase() || 'Agent',
    accountValue: result.account_value,
    dates: result.dates,
    trades: result.trades,
  }] : []

  const filteredTrades = (result?.trades ?? []).filter((t) =>
    tradeFilter === 'all' ? true : t.action === tradeFilter
  )

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Backtest</h1>
      <p className="text-sm text-gray-500 mb-6">Evaluate a trained agent on historical data</p>

      {/* Config form */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-3xl mb-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Training run</label>
            <select
              value={selectedRunId}
              onChange={(e) => setSelectedRunId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Select a completed run...</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.algorithm.toUpperCase()} — {r.run_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Test start</label>
            <input
              type="date" value={testStart}
              onChange={(e) => setTestStart(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Test end</label>
            <input
              type="date" value={testEnd}
              onChange={(e) => setTestEnd(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Starting capital ($)
            </label>
            <input
              type="text"
              value={initialCapital}
              onChange={(e) => setInitialCapital(e.target.value)}
              placeholder="e.g. 100000"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">
              Preset: &nbsp;
              {[10000, 50000, 100000, 1000000].map((v) => (
                <button key={v} onClick={() => setInitialCapital(String(v))}
                  className="text-blue-600 hover:underline mr-2">
                  ${v.toLocaleString()}
                </button>
              ))}
            </p>
          </div>

          <div className="flex items-end pb-1">
            <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
              <input
                type="checkbox"
                checked={showTrades}
                onChange={(e) => setShowTrades(e.target.checked)}
                className="accent-blue-600 w-4 h-4"
              />
              Show buy / sell markers on chart
            </label>
          </div>
        </div>

        <div className="flex items-center gap-4 mt-5">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="px-5 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Submitting...' : 'Run backtest'}
          </button>
          {backtestStatus && <JobStatusBadge status={backtestStatus} />}
        </div>
      </div>

      {/* Skeletons while loading */}
      {loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[0,1,2,3].map(i => <CardSkeleton key={i} />)}
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-6"><ChartSkeleton /></div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-6">

          {/* Capital summary */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">Starting capital</p>
              <p className="text-xl font-semibold text-gray-900">
                {FORMAT_CURRENCY(result.initial_capital)}
              </p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">Final value</p>
              <p className="text-xl font-semibold text-gray-900">
                {FORMAT_CURRENCY(result.metrics?.final_value)}
              </p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">P&L</p>
              <p className={`text-xl font-semibold ${
                result.metrics?.final_value - result.initial_capital >= 0
                  ? 'text-green-600' : 'text-red-600'
              }`}>
                {FORMAT_CURRENCY(result.metrics?.final_value - result.initial_capital)}
              </p>
            </div>
          </div>

          {/* Metrics */}
          <MetricsCard metrics={result.metrics} />

          {/* Benchmark comparison strip */}
          {result.benchmark?.metrics && (
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
              <p className="text-xs font-medium text-blue-700 mb-3">vs S&P 500 benchmark (same period)</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                {[
                  { label: 'Total return', agentKey: 'total_return', fmt: (v) => `${(v*100).toFixed(2)}%` },
                  { label: 'CAGR',         agentKey: 'cagr',         fmt: (v) => `${(v*100).toFixed(2)}%` },
                  { label: 'Sharpe',       agentKey: 'sharpe',       fmt: (v) => v?.toFixed(3) },
                  { label: 'Max drawdown', agentKey: 'max_drawdown', fmt: (v) => `${(v*100).toFixed(2)}%` },
                ].map(({ label, agentKey, fmt }) => {
                  const agentVal = result.metrics?.[agentKey]
                  const spVal    = result.benchmark.metrics?.[agentKey]
                  const better   = agentKey === 'max_drawdown'
                    ? agentVal <= spVal : agentVal >= spVal
                  return (
                    <div key={agentKey}>
                      <p className="text-xs text-blue-500 mb-1">{label}</p>
                      <div className="flex items-baseline gap-2">
                        <span className={`font-semibold ${better ? 'text-green-600' : 'text-red-600'}`}>
                          {fmt(agentVal)}
                        </span>
                        <span className="text-xs text-gray-400">vs {fmt(spVal)}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Equity curve */}
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium text-gray-700">Equity curve</h2>
              <span className="text-xs text-gray-400">
                Normalized to 100 from starting capital
              </span>
            </div>
            <EquityCurveChart
              curves={curveData}
              benchmark={result.benchmark}
              showTrades={showTrades}
            />
          </div>

          {/* Trade log */}
          {result.trades?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
                <h2 className="text-sm font-medium text-gray-700">
                  Trade log
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    {result.trades.length} trades
                  </span>
                </h2>
                <div className="flex gap-2">
                  {['all', 'buy', 'sell'].map((f) => (
                    <button
                      key={f}
                      onClick={() => setTradeFilter(f)}
                      className={`px-3 py-1 rounded-full text-xs transition-colors ${
                        tradeFilter === f
                          ? 'bg-gray-900 text-white'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {f.charAt(0).toUpperCase() + f.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="max-h-72 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 sticky top-0 border-b border-gray-200">
                    <tr>
                      <th className="text-left px-4 py-2 text-gray-500 font-medium">Date</th>
                      <th className="text-left px-4 py-2 text-gray-500 font-medium">Ticker</th>
                      <th className="text-left px-4 py-2 text-gray-500 font-medium">Action</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium">Shares</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium">Price</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {filteredTrades.map((t, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-500 text-xs">{t.date}</td>
                        <td className="px-4 py-2 font-semibold text-gray-900">{t.ticker}</td>
                        <td className="px-4 py-2">
                          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${ACTION_BADGE[t.action]}`}>
                            {t.action}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right text-gray-600">{t.shares}</td>
                        <td className="px-4 py-2 text-right text-gray-600">
                          ${t.price?.toFixed(2)}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-600">
                          ${(t.shares * t.price).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  )
}
