import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import client from '../api/client'
import JobStatusBadge from '../components/jobStatusBadge'
import RewardCurveChart from '../components/rewardCurveChart'
import { ChartSkeleton } from '../components/skeleton'

export default function TrainingPage() {
  const [agents, setAgents] = useState({})
  const [jobs, setJobs] = useState([])
  const [selectedAlgo, setSelectedAlgo] = useState('ppo')
  const [hyperparams, setHyperparams] = useState({})
  const [dataJobId, setDataJobId] = useState('')
  const [xgbRunId, setXgbRunId] = useState('')
  const [lstmRunId, setLstmRunId] = useState('')
  const [trainStart, setTrainStart] = useState('2020-01-01')
  const [trainEnd, setTrainEnd] = useState('2022-12-31')
  const [presets, setPresets] = useState({})
  const [showHyperparams, setShowHyperparams] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [activeRun, setActiveRun] = useState(null)
  const [pipelineStatus, setPipelineStatus] = useState(null)
  const [pipelineBusy, setPipelineBusy] = useState(false)

  useEffect(() => {
    client.get('/api/info').then((r) => {
      setAgents(r.data.agents)
      const algo = Object.keys(r.data.agents)[0]
      setSelectedAlgo(algo)
      setHyperparams(r.data.agents[algo]?.default_hyperparams || {})
    })
    client.get('/api/train/runs').then((r) => setJobs(r.data))
    client.get('/api/research/walk-forward-presets')
      .then((r) => setPresets(r.data.presets || {}))
      .catch(() => {})
  }, [])

  // When algo changes, reset hyperparams to defaults
  const handleAlgoChange = (algo) => {
    setSelectedAlgo(algo)
    setHyperparams(agents[algo]?.default_hyperparams || {})
  }

  // Poll active run
  useEffect(() => {
    if (!activeRun || activeRun.status === 'done' || activeRun.status === 'failed') return
    const timer = setInterval(async () => {
      const r = await client.get(`/api/train/runs/${activeRun.run_id}`)
      setActiveRun(r.data)
      setJobs((prev) => prev.map((j) => j.run_id === r.data.run_id ? r.data : j))
      if (r.data.status === 'done') {
        clearInterval(timer)
        toast.success(`${r.data.algorithm.toUpperCase()} training complete!`)
      }
      if (r.data.status === 'failed') {
        clearInterval(timer)
        toast.error('Training failed')
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [activeRun])

  const refreshPipeline = async () => {
    if (!dataJobId.trim()) return
    try {
      const r = await client.get(`/api/research/alpha-pipeline/status/${dataJobId.trim()}`)
      setPipelineStatus(r.data)
      if (r.data.primary_xgb_run_id && !xgbRunId) {
        setXgbRunId(r.data.primary_xgb_run_id)
      }
    } catch (e) {
      setPipelineStatus(null)
      if (e.response?.status === 404) {
        toast.error('Alpha pipeline API not found — restart backend: ./scripts/start-all.sh')
      }
    }
  }

  const runAlphaPipeline = async () => {
    if (!dataJobId.trim()) return toast.error('Paste a Data Job ID first')
    setPipelineBusy(true)
    try {
      const v = await client.post('/api/research/alpha-pipeline/validate', { data_job_id: dataJobId.trim() })
      if (!v.data.ok) {
        toast.error(v.data.issues?.[0] || 'Data validation failed — fix on Data page')
        return
      }
      await client.post('/api/research/alpha-pipeline/xgb-batch', {
        data_job_id: dataJobId.trim(),
        n_trials: 25,
      })
      toast.success('XGB batch queued — wait for ML Train runs, then Start training')
      const preset = v.data.preset?.train
      if (preset) {
        setTrainStart(preset.start)
        setTrainEnd(preset.end)
      }
      await refreshPipeline()
    } catch (e) {
      if (e.response?.status === 404) {
        toast.error('Alpha pipeline not on API — run: ./scripts/stop-all.sh && ./scripts/start-all.sh')
      }
    } finally {
      setPipelineBusy(false)
    }
  }

  useEffect(() => {
    if (!dataJobId.trim()) return
    refreshPipeline()
    const t = setInterval(refreshPipeline, 8000)
    return () => clearInterval(t)
  }, [dataJobId])

  const handleSubmit = async () => {
    if (!dataJobId.trim()) return toast.error('Paste a Data Job ID first')
    if (selectedAlgo === 'ppo' && pipelineStatus && !pipelineStatus.ready_for_ppo) {
      const ok = window.confirm(
        'XGB alpha not ready yet. Train anyway? (PPO works best after XGB batch completes.)'
      )
      if (!ok) return
    }
    setSubmitting(true)
    try {
      const r = await client.post('/api/train', {
        data_job_id: dataJobId.trim(),
        algorithm: selectedAlgo,
        hyperparams,
        train_start: trainStart,
        train_end: trainEnd,
        ...(xgbRunId.trim() ? { xgb_run_id: xgbRunId.trim() } : {}),
        ...(lstmRunId.trim() ? { lstm_run_id: lstmRunId.trim() } : {}),
      })
      const run = { run_id: r.data.run_id, algorithm: selectedAlgo, status: 'pending' }
      setActiveRun(run)
      setJobs((prev) => [run, ...prev])
      toast.success('Training job submitted!')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Train</h1>
      <p className="text-sm text-gray-500 mb-2">Configure and launch a training run</p>
      {selectedAlgo === 'ppo' && (
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-6">
          Alpha-first PPO: reward = your return − S&amp;P 500 − best baseline penalty.
          28+ features + ML confidence. Default 400k steps, curriculum 2020→2023.
          Train XGBoost first, paste run ID for hybrid alpha.
        </p>
      )}
      {selectedAlgo !== 'ppo' && <div className="mb-6" />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Config form */}
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Train window (walk-forward)</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {Object.entries(presets).map(([key, p]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    setTrainStart(p.train.start)
                    setTrainEnd(p.train.end)
                    toast.success('Train window set')
                  }}
                  className="px-2 py-1 text-xs rounded-full bg-gray-100 hover:bg-gray-200"
                >
                  {key}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                type="date"
                value={trainStart}
                onChange={(e) => setTrainStart(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
              <input
                type="date"
                value={trainEnd}
                onChange={(e) => setTrainEnd(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <p className="text-xs text-gray-400 mt-1">Default: train 2020–2022, backtest on 2024–2025 holdout</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Data Job ID</label>
            <input
              type="text"
              value={dataJobId}
              onChange={(e) => setDataJobId(e.target.value)}
              placeholder="Paste job_id from the Data page"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">
              Go to <Link to="/data" className="text-blue-600 hover:underline">Data page</Link> to download data first
            </p>
          </div>

          {dataJobId.trim() && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-medium text-emerald-900">Alpha pipeline</span>
                <button type="button" onClick={refreshPipeline} className="text-emerald-700 hover:underline">Refresh</button>
              </div>
              {pipelineStatus ? (
                <p className="text-emerald-800">
                  XGB done: {pipelineStatus.xgb_done} · pending: {pipelineStatus.xgb_pending} ·
                  quality (AUC≥0.52): {pipelineStatus.xgb_quality_ok} ·
                  {pipelineStatus.ready_for_ppo ? ' ✓ Ready for PPO' : ' ⏳ Train XGB first'}
                </p>
              ) : (
                <p className="text-emerald-700">Validate data and queue XGB for all tickers.</p>
              )}
              <button
                type="button"
                onClick={runAlphaPipeline}
                disabled={pipelineBusy}
                className="w-full py-2 bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 disabled:opacity-50"
              >
                {pipelineBusy ? 'Running…' : '1. Validate + queue XGB (all tickers)'}
              </button>
            </div>
          )}

          {selectedAlgo === 'ppo' && (
            <div className="grid grid-cols-1 gap-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <p className="text-xs font-medium text-slate-700">Hybrid alpha (optional)</p>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">XGBoost run ID</label>
                <input
                  type="text"
                  value={xgbRunId}
                  onChange={(e) => setXgbRunId(e.target.value)}
                  placeholder="From ML Train page — directional probability → PPO state"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">LSTM run ID (optional)</label>
                <input
                  type="text"
                  value={lstmRunId}
                  onChange={(e) => setLstmRunId(e.target.value)}
                  placeholder="Optional second alpha signal"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Algorithm</label>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(agents).map(([key, agent]) => (
                <button
                  key={key}
                  onClick={() => handleAlgoChange(key)}
                  className={`p-3 rounded-lg border text-left transition-colors ${
                    selectedAlgo === key
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-gray-200 hover:border-gray-300 text-gray-700'
                  }`}
                >
                  <div className="font-semibold text-sm uppercase">{key}</div>
                  <div className="text-xs text-gray-400 mt-0.5 leading-tight">{agent.description}</div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <button
              onClick={() => setShowHyperparams(!showHyperparams)}
              className="text-sm text-blue-600 hover:underline"
            >
              {showHyperparams ? 'Hide' : 'Edit'} hyperparameters
            </button>
            {showHyperparams && (
              <div className="mt-3 space-y-2">
                {Object.entries(hyperparams).map(([key, val]) => (
                  <div key={key} className="flex items-center gap-3">
                    <label className="text-xs text-gray-500 w-40 shrink-0">{key}</label>
                    <input
                      type="text"
                      value={String(val)}
                      onChange={(e) => {
                        const parsed = isNaN(e.target.value) ? e.target.value : Number(e.target.value)
                        setHyperparams((prev) => ({ ...prev, [key]: parsed }))
                      }}
                      className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="w-full py-2.5 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Submitting...' : 'Start training'}
          </button>
        </div>

        {/* Live run status */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h2 className="text-sm font-medium text-gray-700 mb-4">Active run</h2>
          {!activeRun ? (
            <div className="text-sm text-gray-400">Submit a run to see live progress</div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="uppercase font-semibold text-gray-900">{activeRun.algorithm}</span>
                <JobStatusBadge status={activeRun.status} />
              </div>
              <div>
                <p className="text-xs text-gray-500 mb-2">Reward curve</p>
                {activeRun.status === 'running' ? (
                  <ChartSkeleton />
                ) : (
                  <RewardCurveChart rewardCurve={activeRun.metrics?.reward_curve} />
                )}
              </div>
              {activeRun.status === 'done' && (
                <Link
                  to={`/backtest?run_id=${activeRun.run_id}`}
                  className="inline-block text-sm text-blue-600 hover:underline"
                >
                  Run backtest →
                </Link>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Runs history table */}
      {jobs.length > 0 && (
        <div className="mt-8">
          <h2 className="text-base font-medium text-gray-900 mb-3">Recent runs</h2>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 text-gray-500 font-medium">Algorithm</th>
                  <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-gray-500 font-medium">Final Reward</th>
                  <th className="text-left px-4 py-3 text-gray-500 font-medium">Run ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {jobs.map((run) => (
                  <tr key={run.run_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium uppercase">{run.algorithm}</td>
                    <td className="px-4 py-3"><JobStatusBadge status={run.status} /></td>
                    <td className="px-4 py-3 text-gray-600">
                      {run.metrics?.final_reward?.toFixed(2) ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 font-mono">
                      {run.run_id?.slice(0, 8)}...
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
