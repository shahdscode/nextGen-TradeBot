import { useState, useEffect } from 'react'
import client from '../api/client'
import { TableSkeleton } from '../components/skeleton'

const actionBadge = {
  BUY:  'bg-emerald-100 text-emerald-700',
  SELL: 'bg-red-100 text-red-700',
  HOLD: 'bg-amber-100 text-amber-700',
}
const riskColor = { LOW: 'text-emerald-600', MEDIUM: 'text-amber-600', HIGH: 'text-red-500' }
const MEDAL = ['🥇', '🥈', '🥉']

export default function LeaderboardPage() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [market, setMarket] = useState('us')
  const [hours, setHours] = useState(168)

  useEffect(() => {
    setLoading(true)
    client.get('/api/signals/leaderboard', { params: { market, hours } })
      .then((r) => setRows(r.data))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [market, hours])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Leaderboard</h1>
          <p className="text-sm text-gray-500 mt-1">Highest-confidence signals ranked by average confidence</p>
        </div>
        <div className="flex gap-2">
          {['us', 'egx'].map((m) => (
            <button key={m} onClick={() => setMarket(m)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium ${market === m ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
              {m === 'us' ? 'US' : 'EGX'}
            </button>
          ))}
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}
            className="px-3 py-1.5 rounded-lg text-xs bg-gray-100 text-gray-600 border-0 focus:ring-0">
            <option value={24}>Last 24h</option>
            <option value={168}>Last 7 days</option>
            <option value={720}>Last 30 days</option>
          </select>
        </div>
      </div>

      {loading ? <TableSkeleton rows={10} /> : rows.length === 0 ? (
        <div className="text-center py-20 bg-gray-50 rounded-2xl border border-gray-100">
          <p className="text-gray-400">No signal data yet.</p>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium w-12">#</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Ticker</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Signal</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Confidence</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Avg Conf</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Regime</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Risk</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Signals</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((row, i) => (
                <tr key={row.ticker} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-400 font-medium">
                    {i < 3 ? MEDAL[i] : i + 1}
                  </td>
                  <td className="px-4 py-3 font-semibold text-gray-900">{row.ticker}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${actionBadge[row.latest_action] || ''}`}>
                      {row.latest_action}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${row.latest_action === 'BUY' ? 'bg-emerald-500' : row.latest_action === 'SELL' ? 'bg-red-500' : 'bg-amber-500'}`}
                          style={{ width: `${Math.round(row.latest_confidence * 100)}%` }} />
                      </div>
                      <span className="text-sm font-medium text-gray-900">{Math.round(row.latest_confidence * 100)}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{Math.round(row.avg_confidence * 100)}%</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{row.regime || '—'}</td>
                  <td className={`px-4 py-3 text-xs font-medium ${riskColor[row.risk_level] || 'text-gray-500'}`}>{row.risk_level || '—'}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">{row.signal_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
