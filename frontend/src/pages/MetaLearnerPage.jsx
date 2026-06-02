import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import client from '../api/client'

const MODEL_KEYS = ['xgboost', 'lstm', 'ppo', 'a2c', 'ddpg', 'td3', 'sac']
const MODEL_COLORS = {
  xgboost: '#6366f1', lstm: '#8b5cf6', ppo: '#ec4899',
  a2c: '#f59e0b', ddpg: '#10b981', td3: '#3b82f6', sac: '#ef4444',
}

export default function MetaLearnerPage() {
  const [runs,       setRuns]       = useState([])
  const [loading,    setLoading]    = useState(true)
  const [training,   setTraining]   = useState(false)
  const [oofStatus,  setOofStatus]  = useState(null)
  const [metaResult, setMetaResult] = useState(null)

  const fetchRuns = () => {
    setLoading(true)
    client.get('/api/train/runs')
      .then(r => setRuns(r.data.filter(r =>
        ['xgboost','lstm','ppo','a2c','ddpg','td3','sac'].includes(r.algorithm)
      )))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchRuns() }, [])

  const trainMetaLearner = async () => {
    setTraining(true)
    try {
      const r = await client.post('/api/ml/train/meta-learner', {})
      setMetaResult(r.data)
      toast.success('Meta-learner training queued!')
      setTimeout(fetchRuns, 2000)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to train meta-learner')
    } finally {
      setTraining(false)
    }
  }

  const collectOOF = async () => {
    try {
      const r = await client.post('/api/ml/oof/collect', {})
      setOofStatus(r.data)
      toast.success('OOF collection started!')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'OOF collection failed')
    }
  }

  // Parse meta-learner coefficients from the most recent meta run
  const metaRun = runs.find(r => r.algorithm === 'meta_learner')
  const coefficients = metaRun?.metrics?.coefficients || metaResult?.learned_weights || null
  const metaMetrics  = metaRun?.metrics || metaResult || null

  // RL runs summary
  const rlRuns = runs.filter(r => ['ppo','a2c','ddpg','td3','sac'].includes(r.algorithm))
  const xgbRuns = runs.filter(r => r.algorithm === 'xgboost')
  const lstmRuns = runs.filter(r => r.algorithm === 'lstm')

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Meta-Learner</h1>
        <p className="text-sm text-gray-500 mt-1">
          Stacking ensemble — logistic regression trained on OOF predictions from all 7 base models
        </p>
      </div>

      {/* Pipeline Status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'XGBoost Runs',  count: xgbRuns.length,  done: xgbRuns.length > 0,  color: '#6366f1' },
          { label: 'LSTM Runs',     count: lstmRuns.length,  done: lstmRuns.length > 0, color: '#8b5cf6' },
          { label: 'RL Runs',       count: rlRuns.length,    done: rlRuns.length >= 5,  color: '#ec4899' },
          { label: 'Meta-Learner',  count: metaRun ? 1 : 0,  done: !!metaRun,           color: '#10b981' },
        ].map(({ label, count, done, color }) => (
          <div key={label} className="bg-white border border-gray-200 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500">{label}</span>
              <span className={`w-2 h-2 rounded-full ${done ? 'bg-green-400' : 'bg-gray-300'}`} />
            </div>
            <div className="text-2xl font-bold" style={{ color }}>{count}</div>
            <div className="text-xs text-gray-400 mt-1">{done ? 'Ready' : 'Pending'}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Actions */}
        <div className="space-y-4">
          {/* OOF Collection */}
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-1">Step 1 — OOF Collection</h2>
            <p className="text-xs text-gray-400 mb-4">
              Collect out-of-fold predictions from all trained base models
            </p>
            <button onClick={collectOOF}
              className="w-full bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium py-2 rounded-lg transition">
              Collect OOF Predictions
            </button>
            {oofStatus && (
              <p className="text-xs text-gray-500 mt-2">
                Job: {oofStatus.job_id || oofStatus.status}
              </p>
            )}
          </div>

          {/* Train Meta-Learner */}
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-1">Step 2 — Train Meta-Learner</h2>
            <p className="text-xs text-gray-400 mb-4">
              Logistic regression on merged OOF predictions with 5-day return as ground truth
            </p>
            <button onClick={trainMetaLearner} disabled={training}
              className="w-full bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition">
              {training ? 'Training…' : 'Train Meta-Learner'}
            </button>
          </div>

          {/* Academic References */}
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
            <h3 className="text-xs font-semibold text-gray-600 mb-2">Academic References</h3>
            <ul className="text-xs text-gray-500 space-y-1">
              <li>• Wolpert (1992) Stacked Generalization</li>
              <li>• Breiman (1996) Stacked Regressions</li>
              <li>• Platt (1999) Probabilistic SVM Outputs</li>
            </ul>
          </div>
        </div>

        {/* Right: Learned Weights & Metrics */}
        <div className="lg:col-span-2 space-y-4">
          {/* Learned Coefficients */}
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">
              Learned Model Weights
              <span className="ml-2 text-xs font-normal text-gray-400">
                (logistic regression coefficients, normalised to sum = 1)
              </span>
            </h2>
            {coefficients ? (
              <div className="space-y-2">
                {Object.entries(coefficients)
                  .sort(([,a],[,b]) => b - a)
                  .map(([key, val]) => {
                    const pct = (val * 100).toFixed(1)
                    return (
                      <div key={key} className="flex items-center gap-3">
                        <span className="w-16 text-xs font-medium uppercase text-right"
                          style={{ color: MODEL_COLORS[key.replace('_signal','')] || '#6b7280' }}>
                          {key.replace('_signal','').replace('_score','').replace('vix_zscore','VIX')}
                        </span>
                        <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
                          <div className="h-full rounded-full"
                            style={{
                              width: `${Math.max(parseFloat(pct), 2)}%`,
                              backgroundColor: MODEL_COLORS[key.replace('_signal','')] || '#94a3b8'
                            }} />
                        </div>
                        <span className="text-xs tabular-nums text-gray-600 w-12 text-right">
                          {pct}%
                        </span>
                      </div>
                    )
                  })}
              </div>
            ) : (
              <div className="text-center py-10 text-gray-400">
                <div className="text-4xl mb-3">🧠</div>
                <p className="text-sm">Meta-learner not trained yet</p>
                <p className="text-xs mt-1 text-gray-300">
                  Run Step 4 (RL) → Step 5 (Meta-Learner)
                </p>
              </div>
            )}
          </div>

          {/* Performance Metrics */}
          {metaMetrics && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Validation Metrics</h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {[
                  { label: 'AUC', value: metaMetrics.auc, fmt: v => v?.toFixed(4) },
                  { label: 'Accuracy', value: metaMetrics.accuracy, fmt: v => (v*100)?.toFixed(1)+'%' },
                  { label: 'Brier Score', value: metaMetrics.brier_score, fmt: v => v?.toFixed(4) },
                  { label: 'Train Samples', value: metaMetrics.n_train, fmt: v => v?.toLocaleString() },
                ].map(({ label, value, fmt }) => (
                  <div key={label} className="bg-gray-50 rounded-lg p-3">
                    <div className="text-xs text-gray-500 mb-1">{label}</div>
                    <div className="text-lg font-bold text-gray-900">
                      {value != null ? fmt(value) : '—'}
                    </div>
                  </div>
                ))}
              </div>

              {/* vs Fixed Weights Comparison */}
              {metaMetrics.improvement && (
                <div className="mt-4 border-t border-gray-100 pt-4">
                  <h3 className="text-xs font-semibold text-gray-600 mb-3">
                    Meta-Learner vs Fixed Weights
                  </h3>
                  <div className="grid grid-cols-3 gap-3">
                    {Object.entries(metaMetrics.improvement).map(([key, delta]) => (
                      <div key={key} className="text-center">
                        <div className={`text-sm font-bold ${delta > 0 ? 'text-green-600' : 'text-red-500'}`}>
                          {delta > 0 ? '+' : ''}{typeof delta === 'number' ? delta.toFixed(4) : delta}
                        </div>
                        <div className="text-xs text-gray-400">{key.replace(/_/g,' ')}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Base Model Runs Table */}
          <div className="bg-white border border-gray-200 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">Base Model Runs</h2>
            {loading ? (
              <div className="space-y-2">
                {[1,2,3].map(i => <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />)}
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-2 text-gray-400">Algorithm</th>
                    <th className="text-left py-2 text-gray-400">Checkpoint</th>
                    <th className="text-right py-2 text-gray-400">Sharpe</th>
                    <th className="text-right py-2 text-gray-400">Return</th>
                    <th className="text-right py-2 text-gray-400">Trained</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.filter(r => r.algorithm !== 'meta_learner').map((r, i) => {
                    const m = r.metrics || {}
                    const ckpt = r.data_job_id?.match(/ckpt(\d)/)?.[1]
                    return (
                      <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                        <td className="py-2 font-medium uppercase"
                          style={{ color: MODEL_COLORS[r.algorithm] || '#6b7280' }}>
                          {r.algorithm}
                        </td>
                        <td className="py-2 text-gray-500">
                          {ckpt ? `Checkpoint ${ckpt}` : 'Full'}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {m.sharpe_ratio != null ? m.sharpe_ratio.toFixed(3) : '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {m.total_return != null
                            ? `${(m.total_return * 100).toFixed(1)}%`
                            : '—'}
                        </td>
                        <td className="py-2 text-right text-gray-400">
                          {r.created_at ? new Date(r.created_at).toLocaleDateString() : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
