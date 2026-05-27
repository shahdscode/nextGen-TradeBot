import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import client from '../api/client'
import EquityCurveChart from '../components/equityCurveChart'
import MetricsCard from '../components/metricsCard'
import { ChartSkeleton, CardSkeleton } from '../components/skeleton'

const FMT = (v) => v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'

export default function SimulatorPage() {
  const [searchParams] = useSearchParams()
  const [runs, setRuns] = useState([])
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get('run_id') || '')
  const [testStart, setTestStart] = useState('2023-01-01')
  const [testEnd, setTestEnd] = useState('2023-12-31')
  const [initialCapital, setInitialCapital] = useState('100000')
  const [backtestId, setBacktestId] = useState(null)
  const [backtestStatus, setBacktestStatus] = useState(null)
  const [result, setResult] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    client.get('/api/train/runs')
      .then((r) => setRuns(r.data.filter((r) => r.status === 'done')))
  }, [])

  useEffect(() => {
    if (!backtestId || backtestStatus === 'done' || backtestStatus === 'failed') return
    const timer = setInterval(async () => {
      const r = await client.get(`/api/backtest/${backtestId}`)
      setBacktestStatus(r.data.status)
      if (r.data.status === 'done') { clearInterval(timer); setResult(r.data); toast.success('Simulation complete!') }
      if (r.data.status === 'failed') { clearInterval(timer); toast.error(r.data.error || 'Simulation failed') }
    }, 2000)
    return () => clearInterval(timer)
  }, [backtestId, backtestStatus])

  const handleSubmit = async () => {
    if (!selectedRunId) return toast.error('Select a model run')
    const capital = parseFloat(initialCapital.replace(/,/g, ''))
    if (isNaN(capital) || capital <= 0) return toast.error('Enter a valid starting capital')
    setSubmitting(true)
    setResult(null)
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

  const metrics = result?.metrics || {}

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Simulator</h1>
        <p className="text-sm text-gray-500 mt-1">Run a backtest simulation on any trained model</p>
      </div>

      {/* Config */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        <h2 className="text-sm font-medium text-gray-700 mb-4">Simulation Parameters</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Model Run</label>
            <select value={selectedRunId} onChange={(e) => setSelectedRunId(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-400">
              <option value="">Select a run…</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.algorithm.toUpperCase()} — {r.run_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Start Date</label>
            <input type="date" value={testStart} onChange={(e) => setTestStart(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-400" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">End Date</label>
            <input type="date" value={testEnd} onChange={(e) => setTestEnd(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-400" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Starting Capital ($)</label>
            <input type="text" value={initialCapital} onChange={(e) => setInitialCapital(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-400" />
          </div>
        </div>
        <button onClick={handleSubmit} disabled={submitting}
          className="px-5 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors">
          {submitting ? 'Starting…' : backtestStatus === 'running' ? 'Running…' : 'Run Simulation'}
        </button>
      </div>

      {/* Results */}
      {(result || backtestStatus === 'running') && (
        <div className="space-y-5">
          {backtestStatus === 'running' && !result && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => <CardSkeleton key={i} />)}
            </div>
          )}
          {result && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricsCard label="Total Return" value={`${(metrics.total_return * 100).toFixed(2)}%`} />
                <MetricsCard label="Sharpe Ratio" value={metrics.sharpe?.toFixed(3)} />
                <MetricsCard label="Max Drawdown" value={`${(metrics.max_drawdown * 100).toFixed(2)}%`} negative />
                <MetricsCard label="Final Value" value={FMT(metrics.final_value)} />
              </div>
              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <h3 className="text-sm font-medium text-gray-700 mb-4">Equity Curve vs S&P 500</h3>
                <EquityCurveChart
                  dates={result.dates || []}
                  accountValues={result.account_value || []}
                  benchmarkValues={result.benchmark?.account_value}
                  trades={result.trades || []}
                />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
