const actionStyle = {
  BUY:  { bg: 'bg-emerald-500/10 border-emerald-500/30', badge: 'bg-emerald-500 text-white', text: 'text-emerald-400' },
  SELL: { bg: 'bg-red-500/10 border-red-500/30',         badge: 'bg-red-500 text-white',     text: 'text-red-400'     },
  HOLD: { bg: 'bg-amber-500/10 border-amber-500/30',     badge: 'bg-amber-500 text-white',   text: 'text-amber-400'   },
}

const riskColor = { LOW: 'text-emerald-400', MEDIUM: 'text-amber-400', HIGH: 'text-red-400' }

export default function SignalCard({ signal }) {
  const style = actionStyle[signal.action] || actionStyle.HOLD
  const reasons = signal.shap_reasons || []
  const mb = signal.model_breakdown || {}

  return (
    <div className={`rounded-2xl border p-5 ${style.bg} transition-all hover:scale-[1.01]`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-white">{signal.ticker}</span>
            {signal.regime && (
              <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">
                {signal.regime}
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-0.5">
            {signal.generated_at ? new Date(signal.generated_at).toLocaleString() : ''}
          </p>
        </div>
        <span className={`${style.badge} text-xs font-bold px-3 py-1 rounded-full`}>
          {signal.action}
        </span>
      </div>

      {/* Confidence bar */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Confidence</span>
          <span className={`text-sm font-bold ${style.text}`}>{signal.confidence_pct ?? Math.round((signal.confidence || 0) * 100)}%</span>
        </div>
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${signal.action === 'BUY' ? 'bg-emerald-500' : signal.action === 'SELL' ? 'bg-red-500' : 'bg-amber-500'}`}
            style={{ width: `${signal.confidence_pct ?? Math.round((signal.confidence || 0) * 100)}%` }}
          />
        </div>
      </div>

      {/* Model breakdown */}
      {mb.xgboost && (
        <div className="mb-4 space-y-1.5">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Model Signals</p>
          {[
            { label: 'XGBoost', val: mb.xgboost?.probability, weight: mb.xgboost?.weight },
            { label: 'LSTM', val: mb.lstm?.probability, weight: mb.lstm?.weight },
            { label: 'PPO', val: mb.ppo?.signal ?? mb.ppo?.probability, weight: mb.ppo?.weight },
          ].map(({ label, val, weight }) => (
            <div key={label} className="flex items-center gap-2">
              <span className="text-xs text-gray-400 w-14">{label}</span>
              <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                <div className="h-full bg-gray-500 rounded-full" style={{ width: `${Math.round((val || 0) * 100)}%` }} />
              </div>
              <span className="text-xs text-gray-300 w-8 text-right">{val != null ? Math.round(val * 100) : '—'}%</span>
              {weight != null && <span className="text-xs text-gray-600">({Math.round(weight * 100)}%)</span>}
            </div>
          ))}
        </div>
      )}

      {/* SHAP reasons */}
      {reasons.length > 0 && (
        <div className="mb-4">
          <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Why</p>
          <div className="space-y-1.5">
            {reasons.map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-xs text-gray-300 flex-1 truncate">{r.name?.replace(/_/g, ' ')}</span>
                <div className="w-24 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <div className="h-full bg-teal-500 rounded-full" style={{ width: `${r.contribution}%` }} />
                </div>
                <span className="text-xs text-gray-400 w-8 text-right">{r.contribution}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between pt-3 border-t border-gray-800">
        <div className="flex items-center gap-3">
          <span className={`text-xs font-medium ${riskColor[signal.risk_level] || 'text-gray-400'}`}>
            {signal.risk_level || '—'} RISK
          </span>
          {signal.stop_loss_pct && (
            <span className="text-xs text-gray-500">Stop-loss {signal.stop_loss_pct}%</span>
          )}
        </div>
        {signal.sentiment?.score != null && (
          <span className="text-xs text-gray-500">
            Sentiment {signal.sentiment.score > 0 ? '+' : ''}{signal.sentiment.score?.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  )
}
