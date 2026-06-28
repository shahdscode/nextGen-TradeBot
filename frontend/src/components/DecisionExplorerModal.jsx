import { useEffect, useState } from 'react'
import client from '../api/client'
import { voteClass } from '../utils/signalVotes'

function Section({ title, children }) {
  return (
    <div>
      <h3 className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-2">{title}</h3>
      {children}
    </div>
  )
}

function Row({ label, value, valueClass = 'text-white' }) {
  return (
    <div className="flex justify-between gap-4 text-sm py-1 border-b border-white/5 last:border-0">
      <span className="text-gray-500">{label}</span>
      <span className={`font-medium text-right ${valueClass}`}>{value}</span>
    </div>
  )
}

export default function DecisionExplorerModal({ tradeId, onClose }) {
  const [loading, setLoading] = useState(true)
  const [trace, setTrace] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!tradeId) return
    setLoading(true)
    setError(null)
    client.get(`/api/paper-trading/trade-log/${tradeId}`)
      .then((r) => setTrace(r.data))
      .catch(() => setError('Could not load decision trace.'))
      .finally(() => setLoading(false))
  }, [tradeId])

  if (!tradeId) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[#0d1117] border border-white/10 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-[#0d1117]/95 backdrop-blur border-b border-white/10 px-6 py-4 flex items-center justify-between">
          <div>
            <p className="text-[10px] text-teal-500 uppercase tracking-widest font-semibold">Decision Explorer</p>
            {trace && (
              <h2 className="text-xl font-bold text-white mt-0.5">
                <span className={trace.action === 'BUY' ? 'text-emerald-400' : 'text-red-400'}>{trace.action}</span>
                {' '}{trace.ticker}
              </h2>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-500 hover:text-white text-xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="p-6 space-y-6">
          {loading && <p className="text-sm text-gray-500">Loading decision trace…</p>}
          {error && <p className="text-sm text-red-400">{error}</p>}

          {trace && (
            <>
              {trace.meta_probability_pct != null && (
                <Section title="Meta Probability">
                  <p className="text-4xl font-bold text-teal-300">{trace.meta_probability_pct}%</p>
                </Section>
              )}

              {trace.model_votes?.length > 0 && (
                <Section title="Model Votes">
                  <div className="rounded-lg border border-white/10 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-white/5 text-[10px] text-gray-500 uppercase">
                          <th className="text-left py-2 px-3">Model</th>
                          <th className="text-right py-2 px-3">Signal</th>
                          <th className="text-right py-2 px-3">Vote</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trace.model_votes.map((m) => (
                          <tr key={m.key} className="border-t border-white/5">
                            <td className="py-2 px-3 text-gray-300">{m.model}</td>
                            <td className="py-2 px-3 text-right text-gray-500">{m.signal.toFixed(3)}</td>
                            <td className={`py-2 px-3 text-right font-medium ${voteClass(m.vote)}`}>{m.vote}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {trace.model_agreement && (
                    <p className="text-xs text-gray-500 mt-2">
                      {trace.model_agreement.agreement_pct}% model agreement · majority {trace.model_agreement.majority}
                    </p>
                  )}
                </Section>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <Section title="Market Regime">
                  <Row label="Regime" value={trace.regime?.market || '—'} />
                  <Row label="Volatility" value={trace.regime?.volatility || '—'} />
                </Section>

                {trace.technicals?.length > 0 && (
                  <Section title="Technical Indicators">
                    {trace.technicals.map((t) => (
                      <Row key={t.key} label={t.label} value={t.value} />
                    ))}
                  </Section>
                )}
              </div>

              {Object.keys(trace.fundamentals || {}).length > 0 && (
                <Section title="Fundamentals">
                  {trace.fundamentals.pe_ratio != null && (
                    <Row label="P/E" value={trace.fundamentals.pe_ratio} />
                  )}
                  {trace.fundamentals.roe_pct != null && (
                    <Row label="ROE" value={`${trace.fundamentals.roe_pct}%`} />
                  )}
                  {trace.fundamentals.revenue_growth_pct != null && (
                    <Row
                      label="Revenue Growth"
                      value={`${trace.fundamentals.revenue_growth_pct >= 0 ? '+' : ''}${trace.fundamentals.revenue_growth_pct}%`}
                    />
                  )}
                </Section>
              )}

              <Section title="Risk">
                {trace.risk?.position_size_pct != null && (
                  <Row label="Position Size" value={`${trace.risk.position_size_pct}%`} />
                )}
                {trace.risk?.stop_loss_pct != null && (
                  <Row label="Stop Loss" value={`${trace.risk.stop_loss_pct}%`} />
                )}
                {trace.risk?.target_pct != null && (
                  <Row label="Target" value={`${trace.risk.target_pct}%`} />
                )}
                {trace.risk?.risk_dollars != null && (
                  <Row label="Risk Capital" value={`$${Number(trace.risk.risk_dollars).toLocaleString()}`} />
                )}
                {trace.risk?.sizing_method && (
                  <Row label="Sizing Method" value={trace.risk.sizing_method} />
                )}
                {trace.execution?.price != null && (
                  <Row label="Fill Price" value={`$${Number(trace.execution.price).toFixed(2)}`} />
                )}
              </Section>

              <Section title="Final Explanation">
                <p className="text-sm text-gray-300 leading-relaxed bg-teal-500/5 border border-teal-500/20 rounded-lg p-4">
                  {trace.final_explanation}
                </p>
                {trace.summary_reason && (
                  <p className="text-xs text-gray-600 mt-2">{trace.summary_reason}</p>
                )}
              </Section>

              <p className="text-[10px] text-gray-600 text-right">
                {trace.venue} · {trace.market?.toUpperCase()}
                {trace.created_at && ` · ${new Date(trace.created_at).toLocaleString()}`}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
