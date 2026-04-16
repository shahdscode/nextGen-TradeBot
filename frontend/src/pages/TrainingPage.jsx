import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import client from '../api/client'
import JobStatusBadge from '../components/JobStatusBadge'
import RewardCurveChart from '../components/RewardCurveChart'
import { ChartSkeleton } from '../components/Skeleton'

export default function TrainingPage() {
  const [agents, setAgents] = useState({})
  const [jobs, setJobs] = useState([])
  const [selectedAlgo, setSelectedAlgo] = useState('ppo')
  const [hyperparams, setHyperparams] = useState({})
  const [dataJobId, setDataJobId] = useState('')
  const [showHyperparams, setShowHyperparams] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [activeRun, setActiveRun] = useState(null)

  useEffect(() => {
    client.get('/api/info').then((r) => {
      setAgents(r.data.agents)
      const algo = Object.keys(r.data.agents)[0]
      setSelectedAlgo(algo)
      setHyperparams(r.data.agents[algo]?.default_hyperparams || {})
    })
    client.get('/api/train/runs').then((r) => setJobs(r.data))
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

  const handleSubmit = async () => {
    if (!dataJobId.trim()) return toast.error('Paste a Data Job ID first')
    setSubmitting(true)
    try {
      const r = await client.post('/api/train', {
        data_job_id: dataJobId.trim(),
        algorithm: selectedAlgo,
        hyperparams,
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
      <p className="text-sm text-gray-500 mb-6">Configure and launch a training run</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Config form */}
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
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
