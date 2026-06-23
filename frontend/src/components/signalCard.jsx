const actionStyle = {
  BUY: {
    bg: 'border-emerald-500/25 bg-emerald-500/5',
    badge: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
    bar: 'bg-gradient-to-r from-teal-500 to-emerald-400',
    text: 'text-emerald-400',
    label: 'Bullish confidence',
  },
  SELL: {
    bg: 'border-red-500/25 bg-red-500/5',
    badge: 'bg-red-500/20 text-red-300 border border-red-500/30',
    bar: 'bg-gradient-to-r from-red-600 to-red-400',
    text: 'text-red-400',
    label: 'Bearish conviction',
  },
  HOLD: {
    bg: 'border-amber-500/25 bg-amber-500/5',
    badge: 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
    bar: 'bg-gradient-to-r from-amber-600 to-amber-400',
    text: 'text-amber-400',
    label: 'Neutral confidence',
  },
  SUPPRESSED: {
    bg: 'border-gray-500/25 bg-gray-500/5',
    badge: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
    bar: 'bg-gray-500',
    text: 'text-gray-400',
    label: 'Low conviction (hidden from feed)',
  },
}

const riskColor = { LOW: 'text-emerald-400', MEDIUM: 'text-amber-400', HIGH: 'text-red-400' }
const regimeChip = {
  BULL: 'bg-teal-500/10 text-teal-300 border-teal-500/20',
  BEAR: 'bg-red-500/10 text-red-300 border-red-500/20',
  SIDEWAYS: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
}

function displayPct(signal) {
  const conf = signal.confidence_pct ?? Math.round((signal.confidence || 0) * 100)
  if (signal.action === 'SELL') return Math.round(100 - conf)
  return conf
}

export default function SignalCard({ signal }) {
  const style = actionStyle[signal.action] || actionStyle.HOLD
  const reasons = signal.shap_reasons || []
  const mb = signal.model_breakdown || {}
  const pct = displayPct(signal)
  const market = (signal.market || 'us').toUpperCase()

  const models = [
    { key: 'xgboost', label: 'XGB', val: mb.xgboost?.probability, chip: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20' },
    { key: 'lstm', label: 'LSTM', val: mb.lstm?.probability, chip: 'bg-violet-500/10 text-violet-300 border-violet-500/20' },
    { key: 'ppo', label: 'PPO', val: mb.ppo?.signal ?? mb.ppo?.probability, chip: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20' },
  ].filter((m) => m.val != null)

  return (
    <div className={`rounded-2xl border border-white/10 bg-gray-900/80 backdrop-blur-xl p-5 shadow-xl shadow-black/30 ${style.bg}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-0.5">Signal</p>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-lg font-bold text-white">{signal.ticker}</span>
            <span className="text-[10px] px-2 py-0.5 rounded border border-white/10 text-gray-400">{market}</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {signal.generated_at ? new Date(signal.generated_at).toLocaleString() : ''}
          </p>
        </div>
        <span className={`${style.badge} text-xs font-bold px-3 py-1 rounded-lg`}>
          {signal.action}
        </span>
      </div>

      {/* Confidence */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">{style.label}</span>
          <span className={`text-sm font-bold ${style.text}`}>{pct}%</span>
        </div>
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${style.bar}`} style={{ width: `${pct}%` }} />
        </div>
        <p className="text-[10px] text-gray-600 mt-1">
          Fused score {Math.round((signal.confidence || 0) * 100)}% · ensemble of XGB + LSTM + RL
        </p>
      </div>

      {/* Quick chips */}
      <div className="flex gap-1.5 flex-wrap mb-4">
        {signal.regime && (
          <span className={`text-[10px] px-2 py-0.5 rounded border ${regimeChip[signal.regime] || 'bg-gray-500/10 text-gray-400 border-gray-500/20'}`}>
            {signal.regime} regime
          </span>
        )}
        {models.slice(0, 2).map((m) => (
          <span key={m.key} className={`text-[10px] px-2 py-0.5 rounded border ${m.chip}`}>
            {m.label} {(m.val >= 0.5 ? '+' : '')}{(m.val - 0.5).toFixed(2)}
          </span>
        ))}
        {reasons[0] && (
          <span className="text-[10px] px-2 py-0.5 rounded bg-teal-500/10 text-teal-300 border border-teal-500/20">
            SHAP: {reasons[0].name?.replace(/_/g, ' ').slice(0, 12)}
          </span>
        )}
        {signal.risk_level && (
          <span className={`text-[10px] px-2 py-0.5 rounded border ${
            signal.risk_level === 'LOW' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
            : signal.risk_level === 'MEDIUM' ? 'bg-amber-500/10 text-amber-300 border-amber-500/20'
            : 'bg-red-500/10 text-red-300 border-red-500/20'
          }`}>
            Risk: {signal.risk_level}
          </span>
        )}
      </div>

      {/* Model breakdown */}
      {models.length > 0 && (
        <div className="mb-4 space-y-1.5">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide mb-2">Model signals (0–100%)</p>
          {models.map(({ key, label, val }) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-xs text-gray-400 w-10">{label}</span>
              <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${val >= 0.5 ? 'bg-emerald-500' : 'bg-red-400'}`}
                  style={{ width: `${Math.round((val || 0) * 100)}%` }}
                />
              </div>
              <span className="text-xs text-gray-300 w-8 text-right">{Math.round((val || 0) * 100)}%</span>
            </div>
          ))}
        </div>
      )}

      {/* SHAP */}
      {reasons.length > 0 && (
        <div className="mb-4">
          <p className="text-[10px] text-gray-500 uppercase tracking-wide mb-2">Why (XGBoost SHAP)</p>
          <div className="space-y-1.5">
            {reasons.slice(0, 3).map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-xs text-gray-300 flex-1 truncate">{r.name?.replace(/_/g, ' ')}</span>
                <div className="w-20 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <div className="h-full bg-teal-500 rounded-full" style={{ width: `${r.contribution}%` }} />
                </div>
                <span className="text-xs text-gray-500 w-8 text-right">{r.contribution}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-3 border-t border-white/10 text-xs">
        <div className="flex items-center gap-3">
          {signal.stop_loss_pct != null && (
            <span className="text-gray-500">Stop-loss {signal.stop_loss_pct}%</span>
          )}
        </div>
        {signal.sentiment?.score != null && (
          <span className="text-gray-500">
            Sentiment {signal.sentiment.score > 0 ? '+' : ''}{signal.sentiment.score?.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  )
}
