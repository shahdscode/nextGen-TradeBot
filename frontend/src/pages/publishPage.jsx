import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import client from '../api/client'
import JobStatusBadge from '../components/jobStatusBadge'
import { TableSkeleton } from '../components/skeleton'

// Default fallback lists — kept as safety net when no data jobs exist
const DEFAULT_US_TICKERS = [
  'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'JNJ',
]
// Full EGX 30 constituents
const DEFAULT_EGX_TICKERS = [
  'COMI.CA', 'HRHO.CA', 'ETEL.CA', 'TMGH.CA', 'EFIH.CA',
  'AMOC.CA', 'ABUK.CA', 'PHDC.CA', 'SWDY.CA', 'ORWE.CA',
  'CLHO.CA', 'ESRS.CA', 'MNHD.CA', 'FWRY.CA', 'EGTS.CA',
  'EAST.CA', 'OCDI.CA', 'ACGC.CA', 'ISPH.CA', 'GBCO.CA',
  'GTHE.CA', 'MFPC.CA', 'ABIS.CA', 'BICO.CA', 'BTFH.CA',
]

export default function PublishPage() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [publishing, setPublishing] = useState({})
  const [generating, setGenerating] = useState(false)
  const [availableTickers, setAvailableTickers] = useState({ us: DEFAULT_US_TICKERS, egx: DEFAULT_EGX_TICKERS })
  const [genConfig, setGenConfig] = useState({
    market: 'us',
    xgb_run_id: '',
    lstm_run_id: '',
    ppo_run_id: '',
    data_job_id: '',
  })

  const fetchRuns = () => {
    setLoading(true)
    client.get('/api/train/runs')
      .then((r) => setRuns(r.data.filter((r) => r.status === 'done')))
      .catch(() => setRuns([]))
      .finally(() => setLoading(false))
  }

  // Discover tickers from completed data-download jobs
  const fetchTickers = async () => {
    try {
      const r = await client.get('/api/data/jobs')
      const jobs = (r.data || []).filter((j) => j.status === 'done')
      const usSeen = new Set(DEFAULT_US_TICKERS)
      const egxSeen = new Set(DEFAULT_EGX_TICKERS)
      jobs.forEach((j) => {
        const tickers = j.meta?.tickers || []
        tickers.forEach((t) => {
          if (t.endsWith('.CA')) egxSeen.add(t)
          else usSeen.add(t)
        })
      })
      setAvailableTickers({
        us:  [...usSeen].sort(),
        egx: [...egxSeen].sort(),
      })
    } catch {
      // silently keep defaults
    }
  }

  useEffect(() => { fetchRuns(); fetchTickers() }, [])

  const togglePublish = async (run) => {
    setPublishing((p) => ({ ...p, [run.run_id]: true }))
    try {
      if (run.published) {
        await client.post(`/api/train/runs/${run.run_id}/unpublish`)
        toast.success('Unpublished')
      } else {
        await client.post(`/api/train/runs/${run.run_id}/publish`)
        toast.success('Published!')
      }
      fetchRuns()
    } finally {
      setPublishing((p) => ({ ...p, [run.run_id]: false }))
    }
  }

  const generateSignals = async () => {
    const tickers = genConfig.market === 'egx' ? availableTickers.egx : availableTickers.us
    setGenerating(true)
    try {
      const r = await client.post('/api/ml/signals/generate', {
        tickers,
        market: genConfig.market,
        xgb_run_id: genConfig.xgb_run_id || null,
        lstm_run_id: genConfig.lstm_run_id || null,
        ppo_run_id: genConfig.ppo_run_id || null,
        data_job_id: genConfig.data_job_id || null,
      })
      toast.success(`Signal generation queued (job ${r.data.job_id?.slice(0, 8)})`)
    } finally {
      setGenerating(false)
    }
  }

  const doneRuns = runs.filter((r) => r.status === 'done')
  const xgbRuns = doneRuns.filter((r) => r.algorithm === 'xgboost')
  const lstmRuns = doneRuns.filter((r) => r.algorithm === 'lstm')
  const ppoRuns = doneRuns.filter((r) => !['xgboost', 'lstm'].includes(r.algorithm))

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Publish & Generate Signals</h1>
        <p className="text-sm text-gray-500 mt-1">Publish models and generate signal cards for users</p>
      </div>

      {/* Signal Generator */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        <h2 className="text-sm font-medium text-gray-700 mb-4">Generate Signals</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Market</label>
            <select value={genConfig.market} onChange={(e) => setGenConfig({ ...genConfig, market: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
              <option value="us">US Market (DOW 30)</option>
              <option value="egx">EGX (Egypt)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">XGBoost Run (optional)</label>
            <select value={genConfig.xgb_run_id} onChange={(e) => setGenConfig({ ...genConfig, xgb_run_id: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
              <option value="">None</option>
              {xgbRuns.map((r) => <option key={r.run_id} value={r.run_id}>XGB — {r.run_id.slice(0, 8)}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">LSTM Run (optional)</label>
            <select value={genConfig.lstm_run_id} onChange={(e) => setGenConfig({ ...genConfig, lstm_run_id: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
              <option value="">None</option>
              {lstmRuns.map((r) => <option key={r.run_id} value={r.run_id}>LSTM — {r.run_id.slice(0, 8)}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">PPO/RL Run (optional)</label>
            <select value={genConfig.ppo_run_id} onChange={(e) => setGenConfig({ ...genConfig, ppo_run_id: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
              <option value="">None</option>
              {ppoRuns.map((r) => <option key={r.run_id} value={r.run_id}>{r.algorithm.toUpperCase()} — {r.run_id.slice(0, 8)}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">Data Job ID (optional)</label>
            <input type="text" placeholder="Paste data job ID…"
              value={genConfig.data_job_id}
              onChange={(e) => setGenConfig({ ...genConfig, data_job_id: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" />
          </div>
        </div>
        <button onClick={generateSignals} disabled={generating}
          className="px-5 py-2 bg-teal-600 hover:bg-teal-500 text-white text-sm rounded-lg disabled:opacity-50 transition-colors">
          {generating ? 'Queuing…' : 'Generate Signals Now'}
        </button>
      </div>

      {/* Runs table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="text-sm font-medium text-gray-700">Completed Runs — Publish to activate</h2>
        </div>
        {loading ? <TableSkeleton rows={5} /> : doneRuns.length === 0 ? (
          <div className="py-12 text-center text-sm text-gray-400">No completed runs yet. Train a model first.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Algorithm</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Metric</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Created</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Published</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {doneRuns.map((run) => {
                const metric = run.metrics?.mean_auc
                  ? `AUC ${run.metrics.mean_auc.toFixed(3)}`
                  : run.metrics?.final_reward != null
                  ? `Reward ${run.metrics.final_reward.toFixed(2)}`
                  : '—'
                return (
                  <tr key={run.run_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900 uppercase">{run.algorithm}</td>
                    <td className="px-4 py-3"><JobStatusBadge status={run.status} /></td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{metric}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {run.created_at ? new Date(run.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {run.published ? (
                        <span className="text-xs font-medium text-teal-600 bg-teal-50 px-2 py-0.5 rounded-full">Live</span>
                      ) : (
                        <span className="text-xs text-gray-400">Draft</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => togglePublish(run)}
                        disabled={publishing[run.run_id]}
                        className={`text-xs px-3 py-1 rounded-lg transition-colors disabled:opacity-50 ${
                          run.published
                            ? 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                            : 'bg-teal-600 text-white hover:bg-teal-500'
                        }`}
                      >
                        {publishing[run.run_id] ? '…' : run.published ? 'Unpublish' : 'Publish'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
