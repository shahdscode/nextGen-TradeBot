import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import JobStatusBadge from '../components/JobStatusBadge'
import { TableSkeleton } from '../components/Skeleton'

export default function DashboardPage() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    client.get('/api/train/runs')
      .then((r) => setRuns(r.data))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
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

      {loading ? (
        <TableSkeleton rows={5} />
      ) : runs.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
          <p className="text-gray-400 text-sm">No runs yet.</p>
          <Link to="/train" className="text-blue-600 text-sm mt-2 inline-block hover:underline">
            Start your first training run →
          </Link>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Algorithm</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Final Reward</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Created</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.map((run) => (
                <tr key={run.run_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 uppercase">
                    {run.algorithm}
                  </td>
                  <td className="px-4 py-3">
                    <JobStatusBadge status={run.status} />
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {run.metrics?.final_reward != null
                      ? run.metrics.final_reward.toFixed(2)
                      : '—'}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {run.status === 'done' && (
                      <Link
                        to={`/backtest?run_id=${run.run_id}`}
                        className="text-blue-600 text-xs hover:underline"
                      >
                        Backtest →
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
