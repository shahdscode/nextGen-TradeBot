/** Map a model probability (0–1) or string vote to BUY / HOLD / SELL. */
export function signalVote(value) {
  if (value == null) return '—'
  if (typeof value === 'string') {
    const u = value.toUpperCase()
    if (u === 'BUY' || u === 'SELL' || u === 'HOLD') return u
    return value
  }
  const v = Number(value)
  if (Number.isNaN(v)) return '—'
  if (v > 0.55) return 'BUY'
  if (v < 0.45) return 'SELL'
  return 'HOLD'
}

export function voteClass(vote) {
  if (vote === 'BUY') return 'text-emerald-400'
  if (vote === 'SELL') return 'text-red-400'
  if (vote === 'HOLD') return 'text-amber-400/90'
  return 'text-gray-500'
}

const MODEL_LABELS = {
  xgb: 'XGBoost',
  lstm: 'LSTM',
  ppo: 'PPO',
  a2c: 'A2C',
  ddpg: 'DDPG',
  td3: 'TD3',
  sac: 'SAC',
}

export function modelLabel(key) {
  return MODEL_LABELS[key] || key.toUpperCase()
}

export function computeAIConfidence(signals) {
  if (!signals?.length) {
    return { pct: null, label: 'UNKNOWN', detail: 'No recent signals — run signal generation or check back later.' }
  }

  const avgConf = signals.reduce((a, s) => a + (s.confidence || 0), 0) / signals.length
  const spreads = []
  for (const s of signals) {
    const mb = s.model_breakdown || {}
    const vals = [mb.xgboost?.probability, mb.lstm?.probability, mb.ppo?.signal].filter((v) => v != null)
    if (vals.length >= 2) spreads.push(Math.max(...vals) - Math.min(...vals))
  }
  const disagreement = spreads.length ? spreads.reduce((a, b) => a + b, 0) / spreads.length : 0
  const pct = Math.round(avgConf * 100)

  let label = 'LOW'
  if (disagreement > 0.22) label = 'LOW'
  else if (pct >= 68) label = 'HIGH'
  else if (pct >= 52) label = 'MEDIUM'

  const detail = disagreement > 0.22
    ? 'High disagreement between base models'
    : `Based on ${signals.length} evaluated stocks`

  return { pct, label, detail, disagreement }
}

export function computeMarketSummary(signals, regime) {
  const counts = { BUY: 0, HOLD: 0, SELL: 0 }
  for (const s of signals || []) {
    if (counts[s.action] != null) counts[s.action] += 1
  }
  const opportunities = (signals || []).filter((s) => s.action === 'BUY').slice(0, 5).map((s) => s.ticker)
  const highRisk = (signals || []).filter((s) => s.risk_level === 'HIGH').length
  const n = signals?.length || 0
  const estRisk = n && highRisk > n * 0.3 ? 'High' : highRisk > 0 ? 'Medium' : 'Low'

  return {
    counts,
    opportunities,
    regime: regime?.current_regime || '—',
    estRisk,
    source: regime?.source,
  }
}
