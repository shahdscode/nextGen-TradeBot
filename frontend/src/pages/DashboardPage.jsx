import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import JobStatusBadge from '../components/jobStatusBadge'
import { TableSkeleton } from '../components/skeleton'

const ALGORITHMS = ['All', 'ppo', 'a2c', 'ddpg', 'td3', 'sac', 'xgboost', 'lstm']
const STATUSES   = ['All', 'done', 'running', 'pending', 'error']
const SORT_OPTS  = [
  { value: 'created_desc', label: 'Newest first' },
  { value: 'created_asc',  label: 'Oldest first' },
  { value: 'reward_desc',  label: 'Best reward' },
  { value: 'reward_asc',   label: 'Worst reward' },
]

export default function DashboardPage() {
  const [runs, setRuns]       = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch]   = useState('')
  const [algoFilter, setAlgoFilter]     = useState('All')
  const [statusFilter, setStatusFilter] = useState('All')
  const [sortBy, setSortBy]             = useState('created_desc')

  useEffect(() => {
    client.get('/api/train/runs')
      .then((r) => setRuns(r.data))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    let list = [...runs]

    // Text search (run ID or algorithm)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(
        (r) => r.run_id?.toLowerCase().includes(q) || r.algorithm?.toLowerCase().includes(q)
      )
    }

    // Algorithm filter
    if (algoFilter !== 'All')
      list = list.filter((r) => r.algorithm === algoFilter)

    // Status filter
    if (statusFilter !== 'All')
      list = list.filter((r) => r.status === statusFilter)

    // Sort
    list.sort((a, b) => {
      if (sortBy === 'created_desc') return new Date(b.created_at) - new Date(a.created_at)
      if (sortBy === 'created_asc')  return new Date(a.created_at) - new Date(b.created_at)
      const ra = a.metrics?.final_reward ?? -Infinity
      const rb = b.metrics?.final_reward ?? -Infinity
      if (sortBy === 'reward_desc') return rb - ra
      if (sortBy === 'reward_asc')  return ra - rb
      return 0
    })

    return list
  }, [runs, search, algoFilter, statusFilter, sortBy])

  const counts = useMemo(() => ({
    total:   runs.length,
    done:    runs.filter((r) => r.status === 'done').length,
    running: runs.filter((r) => r.status === 'running').length,
    error:   runs.filter((r) => r.status === 'error').length,
  }), [runs])

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">All training runs</p>
        </div>
        <Link
          to="/train"
          className="px-4 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 transition-colors"
        >
          New training run
        </Link>
      </div>

      {/* Summary pills */}
      {!loading && runs.length > 0 && (
        <div className="flex gap-3 mb-5 flex-wrap">
          {[
            { label: 'Total',   value: counts.total,   color: 'bg-gray-100 text-gray-700' },
            { label: 'Done',    value: counts.done,    color: 'bg-green-50 text-green-700' },
            { label: 'Running', value: counts.running, color: 'bg-blue-50 text-blue-700' },
            { label: 'Error',   value: counts.error,   color: 'bg-red-50 text-red-600' },
          ].map(({ label, value, color }) => (
            <span key={label} className={`text-xs font-medium px-3 py-1 rounded-full ${color}`}>
              {label}: {value}
            </span>
          ))}
        </div>
      )}

      {/* Filters */}
      {!loading && runs.length > 0 && (
        <div className="flex flex-wrap gap-3 mb-4">
          <input
            type="text"
            placeholder="Search run ID or algorithm…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-300 w-56"
          />
          <select
            value={algoFilter}
            onChange={(e) => setAlgoFilter(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none"
          >
            {ALGORITHMS.map((a) => <option key={a} value={a}>{a === 'All' ? 'All algorithms' : a.toUpperCase()}</option>)}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none"
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s === 'All' ? 'All statuses' : s}</option>)}
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none"
          >
            {SORT_OPTS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {(search || algoFilter !== 'All' || statusFilter !== 'All') && (
            <button
              onClick={() => { setSearch(''); setAlgoFilter('All'); setStatusFilter('All') }}
              className="text-xs text-gray-500 hover:text-gray-800 px-2 underline"
            >
              Clear filters
            </button>
          )}
        </div>
      )}

      {loading ? (
        <TableSkeleton rows={5} />
      ) : runs.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
          <p className="text-gray-400 text-sm">No runs yet.</p>
          <Link to="/train" className="text-blue-600 text-sm mt-2 inline-block hover:underline">
            Start your first training run →
          </Link>
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-10 text-center">
          <p className="text-gray-400 text-sm">No runs match the current filters.</p>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-gray-100 text-xs text-gray-400">
            Showing {filtered.length} of {runs.length} runs
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Algorithm</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Checkpoint</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Sharpe</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Return</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Max DD</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Win Rate</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Trained</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((run) => {
                const m    = run.metrics || {}
                const ckpt = run.data_job_id?.match(/ckpt(\d)/)?.[1]
                const isRL = ['ppo','a2c','ddpg','td3','sac'].includes(run.algorithm)
                return (
                  <tr key={run.run_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900 uppercase">
                      {run.algorithm}
                      {run.published && (
                        <span className="ml-2 text-xs text-teal-600 bg-teal-50 px-1.5 py-0.5 rounded-full font-normal normal-case">
                          Live
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {ckpt ? `Ckpt ${ckpt}` : isRL ? 'Legacy' : 'Full'}
                    </td>
                    <td className="px-4 py-3">
                      <JobStatusBadge status={run.status} />
                    </td>
                    <td className={`px-4 py-3 text-right tabular-nums text-xs font-medium ${
                      (m.sharpe_ratio ?? 0) >= 1 ? 'text-green-600' :
                      (m.sharpe_ratio ?? 0) >= 0 ? 'text-gray-700' : 'text-red-500'}`}>
                      {m.sharpe_ratio != null ? m.sharpe_ratio.toFixed(3)
                        : m.mean_auc != null ? `AUC ${m.mean_auc.toFixed(3)}` : '—'}
                    </td>
                    <td className={`px-4 py-3 text-right tabular-nums text-xs ${
                      (m.total_return ?? 0) >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      {m.total_return != null
                        ? `${m.total_return >= 0 ? '+' : ''}${(m.total_return * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                    <td className={`px-4 py-3 text-right tabular-nums text-xs ${
                      (m.max_drawdown ?? 0) < -0.2 ? 'text-red-500' : 'text-gray-500'}`}>
                      {m.max_drawdown != null ? `${(m.max_drawdown * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-xs text-gray-500">
                      {m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-3 flex gap-3 items-center">
                      {run.status === 'done' && (
                        <Link to={`/backtest?run_id=${run.run_id}`}
                          className="text-blue-600 text-xs hover:underline">
                          Backtest →
                        </Link>
                      )}
                      {run.status === 'error' && run.error && (
                        <span className="text-xs text-red-500 truncate max-w-xs" title={run.error}>
                          {run.error.slice(0, 50)}{run.error.length > 50 ? '…' : ''}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
