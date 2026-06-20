import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import client from '../api/client'
import EquityCurveChart from '../components/EquityCurveChart'
import AgentCompareTable from '../components/AgentCompareTable'
import { ChartSkeleton, TableSkeleton } from '../components/Skeleton'

export default function ComparePage() {
  const [backtests, setBacktests] = useState([])
  const [selected, setSelected] = useState([])
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadingBacktests, setLoadingBacktests] = useState(true)

  useEffect(() => {
    client.get('/api/backtest').then((r) =>
      setBacktests(r.data.filter((b) => b.status === 'done'))
    ).finally(() => setLoadingBacktests(false))
  }, [])

  const toggleSelect = (bt) => {
    setSelected((prev) => {
      const exists = prev.find((b) => b.backtest_id === bt.backtest_id)
      if (exists) return prev.filter((b) => b.backtest_id !== bt.backtest_id)
      if (prev.length >= 8) { toast.error('Max 8 runs at once'); return prev }
      return [...prev, bt]
    })
  }

  const handleCompare = async () => {
    if (selected.length < 2) return toast.error('Select at least 2 backtests')
    setLoading(true)
    setResults([])
    try {
      const fetched = await Promise.all(
        selected.map((bt) =>
          client.get(`/api/backtest/${bt.backtest_id}`).then((r) => ({
            label: `${bt.run_id?.slice(0, 6)} (${bt.backtest_id?.slice(0, 6)})`,
            accountValue: r.data.account_value,
            dates: r.data.dates,
            metrics: r.data.metrics,
          }))
        )
      )
      setResults(fetched)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Compare</h1>
      <p className="text-sm text-gray-500 mb-6">Overlay up to 8 backtest results on one chart</p>

      {/* Selection table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-6">
        {loadingBacktests ? (
          <div className="p-6">
            <TableSkeleton rows={6} />
          </div>
        ) : backtests.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-400">
            No completed backtests yet. Run some on the Backtest page first.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="w-10 px-4 py-3" />
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Backtest ID</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Run ID</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Sharpe</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">CAGR</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Total Return</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {backtests.map((bt) => {
                const isSelected = !!selected.find((b) => b.backtest_id === bt.backtest_id)
                return (
                  <tr
                    key={bt.backtest_id}
                    onClick={() => toggleSelect(bt)}
                    className={`cursor-pointer hover:bg-gray-50 ${isSelected ? 'bg-blue-50' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <input type="checkbox" readOnly checked={isSelected}
                        className="accent-blue-600" />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">
                      {bt.backtest_id?.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">
                      {bt.run_id?.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3">{bt.metrics?.sharpe?.toFixed(3) ?? '—'}</td>
                    <td className="px-4 py-3">
                      {bt.metrics?.cagr != null ? `${(bt.metrics.cagr * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {bt.metrics?.total_return != null
                        ? `${(bt.metrics.total_return * 100).toFixed(2)}%`
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="flex items-center gap-4 mb-8">
        <button
          onClick={handleCompare}
          disabled={loadingBacktests || selected.length < 2 || loading}
          className="px-5 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Loading...' : `Compare ${selected.length} selected`}
        </button>
        {selected.length > 0 && (
          <span className="text-sm text-gray-500">{selected.length} selected</span>
        )}
      </div>

      {loading && <ChartSkeleton />}

      {results.length > 0 && (
        <div className="space-y-6">
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-sm font-medium text-gray-700 mb-4">Equity curves</h2>
            <EquityCurveChart curves={results} />
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-sm font-medium text-gray-700 mb-4">Metrics comparison</h2>
            <AgentCompareTable results={results} />
          </div>
        </div>
      )}
    </div>
  )
}
