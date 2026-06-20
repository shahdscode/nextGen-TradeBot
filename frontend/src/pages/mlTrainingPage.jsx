import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import client from '../api/client'
import JobStatusBadge from '../components/JobStatusBadge'
import { TableSkeleton } from '../components/Skeleton'

export default function MLTrainingPage() {
  const [dataJobs, setDataJobs] = useState([])
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const [xgbConfig, setXgbConfig] = useState({ data_job_id: '', ticker: 'AAPL', n_trials: 30, market: 'us' })
  const [lstmConfig, setLstmConfig] = useState({ data_job_id: '', ticker: 'AAPL', epochs: 30, market: 'us' })

  const fetchData = () => {
    setLoading(true)
    Promise.all([
      client.get('/api/data/jobs').catch(() => ({ data: [] })),
      client.get('/api/train/runs').catch(() => ({ data: [] })),
    ]).then(([d, r]) => {
      setDataJobs(d.data.filter((j) => j.status === 'done'))
      setRuns(r.data.filter((r) => ['xgboost', 'lstm'].includes(r.algorithm)))
    }).finally(() => setLoading(false))
  }

  useEffect(() => { fetchData() }, [])

  const trainXGB = async () => {
    if (!xgbConfig.data_job_id) return toast.error('Select a data job')
    setSubmitting(true)
    try {
      await client.post('/api/ml/train/xgboost', xgbConfig)
      toast.success('XGBoost training queued!')
      setTimeout(fetchData, 1000)
    } finally { setSubmitting(false) }
  }

  const trainXGBBatch = async () => {
    if (!xgbConfig.data_job_id) return toast.error('Select a data job')
    setSubmitting(true)
    try {
      const r = await client.post('/api/research/alpha-pipeline/xgb-batch', {
        data_job_id: xgbConfig.data_job_id,
        n_trials: xgbConfig.n_trials,
      })
      if (!r.data.ok) {
        toast.error(r.data.validation?.issues?.[0] || 'Validation failed')
        return
      }
      toast.success(`Queued XGB for ${r.data.queued?.length || 0} tickers`)
      setTimeout(fetchData, 1500)
    } catch (e) {
      if (e.response?.status === 404) {
        toast.error('Alpha pipeline not on API — restart: ./scripts/start-all.sh')
      }
    } finally { setSubmitting(false) }
  }

  const trainLSTM = async () => {
    if (!lstmConfig.data_job_id) return toast.error('Select a data job')
    setSubmitting(true)
    try {
      await client.post('/api/ml/train/lstm', lstmConfig)
      toast.success('LSTM training queued!')
      setTimeout(fetchData, 1000)
    } finally { setSubmitting(false) }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">ML Training</h1>
        <p className="text-sm text-gray-500 mt-1">Train XGBoost and LSTM models with walk-forward validation</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* XGBoost */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-sm font-semibold text-gray-900">XGBoost</span>
            <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full">+ SHAP</span>
          </div>
          <div className="space-y-3 mb-4">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Data Job</label>
              <select value={xgbConfig.data_job_id} onChange={(e) => setXgbConfig({ ...xgbConfig, data_job_id: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
                <option value="">Select data job…</option>
                {dataJobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.job_id.slice(0, 8)} — {j.meta?.tickers?.join(', ') || 'unknown'}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Primary Ticker</label>
              <input value={xgbConfig.ticker} onChange={(e) => setXgbConfig({ ...xgbConfig, ticker: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" placeholder="AAPL" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">HPO Trials</label>
                <input type="number" value={xgbConfig.n_trials} onChange={(e) => setXgbConfig({ ...xgbConfig, n_trials: Number(e.target.value) })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" min={5} max={100} />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Market</label>
                <select value={xgbConfig.market} onChange={(e) => setXgbConfig({ ...xgbConfig, market: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
                  <option value="us">US</option>
                  <option value="egx">EGX</option>
                </select>
              </div>
            </div>
          </div>
          <button onClick={trainXGB} disabled={submitting}
            className="w-full py-2 bg-gray-900 hover:bg-gray-700 text-white text-sm rounded-lg disabled:opacity-50 transition-colors mb-2">
            Train XGBoost (single ticker)
          </button>
          <button onClick={trainXGBBatch} disabled={submitting}
            className="w-full py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg disabled:opacity-50 transition-colors">
            Train all tickers (alpha pipeline)
          </button>
        </div>

        {/* LSTM */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-sm font-semibold text-gray-900">LSTM</span>
            <span className="text-xs bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full">Wavelet denoising</span>
          </div>
          <div className="space-y-3 mb-4">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Data Job</label>
              <select value={lstmConfig.data_job_id} onChange={(e) => setLstmConfig({ ...lstmConfig, data_job_id: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
                <option value="">Select data job…</option>
                {dataJobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.job_id.slice(0, 8)} — {j.meta?.tickers?.join(', ') || 'unknown'}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Primary Ticker</label>
              <input value={lstmConfig.ticker} onChange={(e) => setLstmConfig({ ...lstmConfig, ticker: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" placeholder="AAPL" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Epochs</label>
                <input type="number" value={lstmConfig.epochs} onChange={(e) => setLstmConfig({ ...lstmConfig, epochs: Number(e.target.value) })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none" min={5} max={200} />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Market</label>
                <select value={lstmConfig.market} onChange={(e) => setLstmConfig({ ...lstmConfig, market: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none">
                  <option value="us">US</option>
                  <option value="egx">EGX</option>
                </select>
              </div>
            </div>
          </div>
          <button onClick={trainLSTM} disabled={submitting}
            className="w-full py-2 bg-gray-900 hover:bg-gray-700 text-white text-sm rounded-lg disabled:opacity-50 transition-colors">
            Train LSTM
          </button>
        </div>
      </div>

      {/* Results */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-medium text-gray-700">ML Training Runs</h2>
          <button onClick={fetchData} className="text-xs text-gray-400 hover:text-gray-700">Refresh</button>
        </div>
        {loading ? <TableSkeleton rows={4} /> : runs.length === 0 ? (
          <div className="py-10 text-center text-sm text-gray-400">No ML training runs yet.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Model</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">AUC</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Val'23</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Accuracy</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Folds</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Run ID</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.map((run) => (
                <tr key={run.run_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 uppercase">{run.algorithm}</td>
                  <td className="px-4 py-3"><JobStatusBadge status={run.status} /></td>
                  <td className="px-4 py-3 text-gray-600">{run.metrics?.mean_auc?.toFixed(4) ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{run.metrics?.val_year_2023_auc?.toFixed(4) ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{run.metrics?.mean_accuracy?.toFixed(4) ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs">{run.metrics?.n_folds ?? '—'}</td>
                  <td className="px-4 py-3 text-gray-400 text-xs font-mono cursor-pointer" title="Click to copy"
                    onClick={() => { navigator.clipboard?.writeText(run.run_id); toast.success('Copied run ID') }}>
                    {run.run_id?.slice(0, 8)}…
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
