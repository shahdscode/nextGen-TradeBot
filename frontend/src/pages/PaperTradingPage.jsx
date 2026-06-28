import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { LineChart, Line, ResponsiveContainer, YAxis, Tooltip } from 'recharts'
import client from '../api/client'
import { CardSkeleton } from '../components/Skeleton'
import { CHART_TOOLTIP_STYLE } from '../chartTheme'
import { InsightsDashboard, RichTradeJournal } from '../components/paperTradingInsights'
import PortfolioIntelligence from '../components/PortfolioIntelligence'
import { computeAIConfidence } from '../utils/signalVotes'

export default function PaperTradingPage() {
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [rlRuns, setRlRuns] = useState([])
  const [modelRunId, setModelRunId] = useState('')

  // ── Alpaca paper broker ──────────────────────────────────────────────────
  const [alpaca, setAlpaca] = useState(null)
  const [alpacaPf, setAlpacaPf] = useState(null)
  const [alpacaMode, setAlpacaMode] = useState('meta')
  const [alpacaResult, setAlpacaResult] = useState(null)

  // ── Simulated session (US + EGX, with market/ticker picker) ───────────────
  const [simMarket, setSimMarket] = useState('us')
  const [simTickers, setSimTickers] = useState('')   // optional CSV subset
  const [simResult, setSimResult] = useState(null)
  const [simPf, setSimPf] = useState(null)
  const [suggestions, setSuggestions] = useState(null)   // advisory mode
  const [autoEnabled, setAutoEnabled] = useState(false)  // automated mode

  // ── Risk & portfolio controls (#1–#3) ─────────────────────────────────────
  const [sizingMethod, setSizingMethod] = useState('risk')
  const [riskPerTrade, setRiskPerTrade] = useState('1')   // % of equity per trade
  const [maxPosition, setMaxPosition] = useState('20')    // % of equity per name
  const [useBrackets, setUseBrackets] = useState(false)   // Alpaca bracket orders
  const [tradeLog, setTradeLog] = useState([])
  const [alpacaConfigured, setAlpacaConfigured] = useState(true)
  const [signals, setSignals] = useState([])
  const [regime, setRegime] = useState(null)
  const [metaStatus, setMetaStatus] = useState(null)
  const [weights, setWeights] = useState(null)
  const [insightMarket, setInsightMarket] = useState('us')
  const [portfolioAnalytics, setPortfolioAnalytics] = useState(null)
  const [portfolioSource, setPortfolioSource] = useState('sim')

  const aiConfidence = computeAIConfidence(signals)

  const loadPortfolioAnalytics = () =>
    client.get('/api/paper-trading/analytics')
      .then(r => setPortfolioAnalytics(r.data))
      .catch(() => setPortfolioAnalytics(null))

  const loadInsights = (market = insightMarket) => Promise.all([
    client.get('/api/signals/top', { params: { market, limit: 30 } })
      .then(r => setSignals(r.data || [])).catch(() => setSignals([])),
    client.get('/api/market/regime', { params: { market } })
      .then(r => setRegime(r.data)).catch(() => {}),
    client.get('/api/ml/meta/status')
      .then(r => setMetaStatus(r.data)).catch(() => {}),
    client.get('/api/ml/weights/current')
      .then(r => setWeights(r.data)).catch(() => {}),
  ])

  const riskParams = () => {
    const p = { sizing_method: sizingMethod }
    if (riskPerTrade) p.risk_per_trade_pct = Number(riskPerTrade) / 100
    if (maxPosition) p.max_position_pct = Number(maxPosition) / 100
    return p
  }

  const loadTradeLog = () =>
    client.get('/api/paper-trading/trade-log', { params: { limit: 25 } })
      .then(r => setTradeLog(r.data || [])).catch(() => {})

  const refreshSim = () => Promise.all([
    client.get('/api/paper-trading/portfolio').then(r => setSimPf(r.data)).catch(() => {}),
    client.get('/api/paper-trading/status').then(r => setAutoEnabled(!!r.data.auto_enabled)).catch(() => {}),
    loadTradeLog(),
    loadPortfolioAnalytics(),
  ])

  const handleSuggest = async () => {
    setBusy(true); setSuggestions(null)
    try {
      const params = { market: simMarket, ...riskParams() }
      if (simTickers.trim()) params.tickers = simTickers.trim()
      const r = await client.post('/api/paper-trading/suggest', null, { params })
      setSuggestions(r.data)
    } catch (e) {
      setSuggestions({ ok: false, note: e.response?.data?.detail || 'Suggestion failed' })
    } finally { setBusy(false) }
  }

  const toggleAuto = async () => {
    const next = !autoEnabled
    try {
      await client.post('/api/paper-trading/auto', null, { params: { enabled: next } })
      setAutoEnabled(next)
    } catch (e) { /* ignore */ }
  }

  const handleSimRebalance = async () => {
    setBusy(true); setSimResult(null)
    try {
      const params = { mode: 'meta', market: simMarket, ...riskParams() }
      if (simTickers.trim()) params.tickers = simTickers.trim()
      const r = await client.post('/api/paper-trading/rebalance', null, { params })
      setSimResult(r.data)
      await Promise.all([refreshSim(), loadInsights(simMarket)])
    } catch (e) {
      setSimResult({ ok: false, note: e.response?.data?.detail || 'Rebalance failed' })
    } finally { setBusy(false) }
  }

  const refreshAlpaca = () => Promise.all([
    client.get('/api/paper-trading/alpaca/status').then(r => setAlpaca(r.data)).catch(() => {}),
    client.get('/api/paper-trading/alpaca/portfolio').then(r => setAlpacaPf(r.data)).catch(() => {}),
    loadPortfolioAnalytics(),
  ])

  useEffect(() => {
    Promise.all([refreshAlpaca(), refreshSim(), loadInsights(), loadPortfolioAnalytics()])
      .finally(() => setLoading(false))
    client.get('/api/auth/me')
      .then(r => setAlpacaConfigured(!!r.data.alpaca_configured))
      .catch(() => {})
    client.get('/api/train/runs').then(r => {
      const rl = r.data.filter(x => ['ppo','a2c','ddpg','td3','sac'].includes(x.algorithm)
                                    && x.status === 'done')
      setRlRuns(rl)
      if (rl.length) setModelRunId(rl[0].run_id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    loadInsights(insightMarket)
  }, [insightMarket])

  const handleAlpacaRebalance = async () => {
    setBusy(true); setAlpacaResult(null)
    try {
      const params = alpacaMode === 'meta'
        ? { mode: 'meta', sizing_method: sizingMethod, use_brackets: useBrackets }
        : { mode: 'rl', run_id: modelRunId }
      const r = await client.post('/api/paper-trading/alpaca/rebalance', null, { params })
      setAlpacaResult(r.data)
      await Promise.all([refreshAlpaca(), loadTradeLog(), loadInsights()])
    } catch (e) {
      setAlpacaResult({ ok: false, note: e.response?.data?.detail || 'Alpaca rebalance failed' })
    } finally { setBusy(false) }
  }

  if (loading) return (
    <div className="space-y-4">
      <CardSkeleton /><CardSkeleton />
    </div>
  )

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-1">Paper Trading</h1>
          <p className="text-sm text-gray-400">
            Your simulator and Alpaca paper account are private. AI signals are shared across users.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={insightMarket}
            onChange={(e) => setInsightMarket(e.target.value)}
            className="bg-gray-900/80 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-gray-300"
          >
            <option value="us">Insights: US</option>
            <option value="egx">Insights: EGX</option>
          </select>
          {aiConfidence.pct != null && (
            <div className="text-right px-3 py-1.5 rounded-lg border border-white/10 bg-gray-900/60">
              <p className="text-[10px] text-gray-500 uppercase">AI Confidence</p>
              <p className={`text-sm font-bold ${
                aiConfidence.label === 'HIGH' ? 'text-emerald-400' : aiConfidence.label === 'MEDIUM' ? 'text-amber-400' : 'text-red-400'
              }`}>
                {aiConfidence.pct}% · {aiConfidence.label}
              </p>
            </div>
          )}
        </div>
      </div>

      <InsightsDashboard
        signals={signals}
        regime={regime}
        metaStatus={metaStatus}
        weights={weights}
        market={insightMarket}
      />

      <PortfolioIntelligence
        analytics={portfolioAnalytics}
        source={portfolioSource}
        onSourceChange={setPortfolioSource}
      />

      {!alpacaConfigured && (
        <div className="mb-6 p-4 rounded-xl border border-amber-200 bg-amber-50 text-amber-900 text-sm">
          Alpaca paper keys are not set for your account.{' '}
          <Link to="/app/settings" className="font-medium text-amber-800 underline">
            Add keys in Settings
          </Link>{' '}
          to rebalance a real Alpaca paper portfolio.
        </div>
      )}

      <p className="text-sm text-gray-500 mb-6">US (DOW 30) via Alpaca real fills · Egyptian market (EGX) via simulated session</p>

      {/* Simulated session — market + ticker picker (US & EGX) */}
      <div className="bg-white border border-indigo-200 rounded-xl p-6 mb-6 max-w-3xl">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="text-sm font-semibold text-gray-900">Simulated Session — pick market &amp; tickers</h2>
          {simResult?.regime && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              simResult.defensive ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}`}>
              {simResult.regime}{simResult.defensive ? ' · defensive (no new buys)' : ''}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Meta-learner allocation on live data into a simulated account. Risk controls run every
          rebalance: sell any name down &gt; 8%, go to cash in a BEAR regime, liquidate on &gt; 15% drawdown.
          EGX uses XGBoost + LSTM (RL is US-only).
        </p>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <select value={simMarket} onChange={e => setSimMarket(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
            <option value="us">US — DOW 30</option>
            <option value="egx">Egypt — EGX</option>
          </select>
          <input value={simTickers} onChange={e => setSimTickers(e.target.value)}
            placeholder={simMarket === 'egx' ? 'COMI.CA, HRHO.CA (optional)' : 'AAPL, MSFT (optional)'}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm flex-1 min-w-[180px]" />
          <button onClick={handleSuggest} disabled={busy}
            className="px-4 py-2 text-sm rounded-lg border border-indigo-300 text-indigo-700 hover:bg-indigo-50 disabled:opacity-50">
            {busy ? 'Working…' : 'Suggest (review)'}
          </button>
          <button onClick={handleSimRebalance} disabled={busy}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50">
            {busy ? 'Running…' : 'Rebalance (execute)'}
          </button>
          <button onClick={toggleAuto}
            className={`px-3 py-2 text-sm rounded-lg border ${autoEnabled
              ? 'bg-emerald-600 text-white border-emerald-600 hover:bg-emerald-700'
              : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
            Auto-trade: {autoEnabled ? 'ON' : 'OFF'}
          </button>
        </div>

        {/* Risk & portfolio controls (#1 sizing · #2 optimization · #3 regime) */}
        <div className="flex flex-wrap items-end gap-3 mb-3 p-3 rounded-lg bg-gray-50 border border-gray-100">
          <label className="text-[11px] text-gray-500">
            Allocation
            <select value={sizingMethod} onChange={e => setSizingMethod(e.target.value)}
              className="block mt-0.5 border border-gray-300 rounded-lg px-2 py-1.5 text-sm">
              <option value="risk">ATR risk-based</option>
              <option value="risk_parity">Risk parity</option>
              <option value="min_variance">Min variance</option>
              <option value="max_sharpe">Max Sharpe</option>
              <option value="inverse_vol">Inverse vol</option>
              <option value="conviction">Conviction</option>
            </select>
          </label>
          <label className="text-[11px] text-gray-500">
            Risk / trade %
            <input type="number" step="0.25" min="0.1" max="5" value={riskPerTrade}
              onChange={e => setRiskPerTrade(e.target.value)}
              className="block mt-0.5 w-20 border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />
          </label>
          <label className="text-[11px] text-gray-500">
            Max position %
            <input type="number" step="5" min="5" max="100" value={maxPosition}
              onChange={e => setMaxPosition(e.target.value)}
              className="block mt-0.5 w-20 border border-gray-300 rounded-lg px-2 py-1.5 text-sm" />
          </label>
          <span className="text-[11px] text-gray-400 max-w-[220px]">
            Positions sized by volatility (ATR stop) with per-name, sector &amp; leverage caps.
          </span>
        </div>
        {autoEnabled && (
          <p className="text-[11px] text-emerald-700 mb-2">
            Automated: the scheduler will rebalance this session weekly with the same risk controls.
          </p>
        )}
        {suggestions && (
          <div className={`text-xs rounded-lg p-3 mb-2 ${suggestions.ok ? 'bg-violet-50' : 'bg-red-50 text-red-700'}`}>
            {suggestions.ok ? (
              <>
                <div className="font-medium text-violet-800 mb-1">
                  Advisory · {suggestions.regime} regime — review and click Rebalance to apply
                </div>
                <div className="flex flex-wrap gap-2 mb-2 text-[10px] text-violet-700">
                  {suggestions.sizing_method && <span className="px-1.5 py-0.5 rounded bg-violet-100 border border-violet-200">method: {suggestions.sizing_method}</span>}
                  {suggestions.vol_regime?.vol_regime && <span className="px-1.5 py-0.5 rounded bg-violet-100 border border-violet-200">vol: {suggestions.vol_regime.vol_regime} (×{suggestions.vol_regime.risk_scale})</span>}
                  {suggestions.gross_exposure != null && <span className="px-1.5 py-0.5 rounded bg-violet-100 border border-violet-200">invested: {(suggestions.gross_exposure*100).toFixed(0)}%</span>}
                  {suggestions.avg_correlation != null && <span className="px-1.5 py-0.5 rounded bg-violet-100 border border-violet-200">avg corr: {suggestions.avg_correlation}</span>}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {suggestions.recommendations.map((r) => (
                    <span key={r.ticker}
                      title={r.stop_price ? `entry $${r.entry} · stop $${r.stop_price} · target $${r.take_profit}` : undefined}
                      className={`px-2 py-0.5 rounded border text-[11px] ${
                      r.action === 'BUY' ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
                      : r.action === 'SELL' ? 'bg-red-100 text-red-700 border-red-200'
                      : 'bg-gray-100 text-gray-600 border-gray-200'}`}>
                      {r.ticker} {r.action}{r.target_weight > 0 ? ` ${(r.target_weight * 100).toFixed(0)}%` : ''}{r.stop_price ? ' 🛡' : ''}{r.stop_loss ? ' ⛔' : ''}
                    </span>
                  ))}
                </div>
              </>
            ) : `✗ ${suggestions.note}`}
          </div>
        )}
        {simResult && (
          <div className={`text-xs rounded-lg p-3 mb-2 ${simResult.ok ? 'bg-indigo-50 text-indigo-800' : 'bg-red-50 text-red-700'}`}>
            {simResult.ok ? (
              simResult.risk_action === 'KILL_SWITCH'
                ? `⚠ Kill-switch: ${simResult.message}`
                : `✓ ${simResult.message} · ${simResult.positions_held} positions · $${Number(simResult.cash).toLocaleString()} cash`
            ) : `✗ ${simResult.note}`}
          </div>
        )}
        {simResult?.stopped_out && Object.keys(simResult.stopped_out).length > 0 && (
          <div className="text-[11px] text-red-600 mb-2">
            Stopped out (down &gt; 8%): {Object.entries(simResult.stopped_out)
              .map(([t, pl]) => `${t} ${(pl * 100).toFixed(1)}%`).join(', ')}
          </div>
        )}
        {simPf?.positions?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-gray-100 text-gray-400">
                <th className="text-left py-1">Symbol</th><th className="text-right">Qty</th>
                <th className="text-right">Price</th><th className="text-right">Mkt Val</th><th className="text-right">P&L</th>
              </tr></thead>
              <tbody>
                {simPf.positions.map(p => (
                  <tr key={p.symbol} className="border-b border-gray-50">
                    <td className="py-1 font-medium">{p.symbol}</td>
                    <td className="text-right">{p.qty.toFixed(2)}</td>
                    <td className="text-right">${p.current_price.toFixed(2)}</td>
                    <td className="text-right">${p.market_value.toFixed(0)}</td>
                    <td className={`text-right ${p.unrealized_pl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      ${p.unrealized_pl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Alpaca paper broker — real US-equity fills */}
      <div className="bg-white border border-emerald-200 rounded-xl p-6 mb-6 max-w-3xl">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="text-sm font-semibold text-gray-900">Alpaca Paper Broker — real fills</h2>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
            alpaca?.configured ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
            {alpaca?.configured ? (alpaca?.market_open ? 'market open' : 'market closed') : 'not configured'}
          </span>
          {alpacaPf?.drawdown != null && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              alpacaPf.drawdown_breached ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'}`}>
              {alpacaPf.drawdown_breached ? '⚠ risk halt' : `drawdown ${(alpacaPf.drawdown*100).toFixed(1)}%`}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Submits real orders to your free Alpaca paper account (US equities = DOW30).
          The model picks the allocation; Alpaca executes and tracks positions + P&L.
        </p>
        {alpaca?.configured && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Equity</div>
              <div className="text-lg font-bold text-gray-900">
                ${Number(alpaca.equity).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Total Return</div>
              <div className={`text-lg font-bold ${(alpacaPf?.total_return ?? 0) >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                {alpacaPf?.total_return != null
                  ? `${alpacaPf.total_return >= 0 ? '+' : ''}${(alpacaPf.total_return * 100).toFixed(2)}%`
                  : '—'}
              </div>
              <div className="text-[10px] text-gray-400">
                {alpacaPf?.total_pl != null
                  ? `${alpacaPf.total_pl >= 0 ? '+' : ''}$${alpacaPf.total_pl.toLocaleString(undefined,{maximumFractionDigits:0})} since start`
                  : ''}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Cash</div>
              <div className="text-lg font-bold text-gray-900">
                ${Number(alpaca.cash).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Buying Power</div>
              <div className="text-lg font-bold text-gray-900">
                ${Number(alpaca.buying_power).toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <select value={alpacaMode} onChange={e => setAlpacaMode(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
            <option value="meta">Meta-learner ensemble (recommended)</option>
            <option value="rl">Advanced: single RL model</option>
          </select>
          {alpacaMode === 'rl' && (
            <select value={modelRunId} onChange={e => setModelRunId(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm">
              {rlRuns.length === 0 && <option value="">No RL runs</option>}
              {rlRuns.map((r) => {
                const ck = r.data_job_id?.match(/ckpt(\d)/)?.[1]
                const sh = r.metrics?.sharpe_ratio
                return (
                  <option key={r.run_id} value={r.run_id}>
                    {r.algorithm.toUpperCase()}{ck ? ` · ckpt${ck}` : ''}
                    {sh != null ? ` · Sharpe ${sh.toFixed(2)}` : ''}
                  </option>
                )
              })}
            </select>
          )}
          {alpacaMode === 'meta' && (
            <label className="flex items-center gap-1.5 text-xs text-gray-600">
              <input type="checkbox" checked={useBrackets}
                onChange={e => setUseBrackets(e.target.checked)} />
              Bracket orders (auto stop + target)
            </label>
          )}
          <button onClick={handleAlpacaRebalance}
            disabled={busy || !alpaca?.configured || (alpacaMode === 'rl' && !modelRunId)}
            className="px-4 py-2 text-sm rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
            {busy ? 'Submitting…' : 'Rebalance Alpaca with Model'}
          </button>
          <button onClick={refreshAlpaca}
            className="px-3 py-2 text-xs rounded-lg border border-gray-300 hover:bg-gray-50">Refresh</button>
        </div>
        {alpacaResult && (
          <div className={`text-xs rounded-lg p-3 mb-3 ${alpacaResult.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>
            {alpacaResult.ok
              ? `✓ ${alpacaResult.model_message} — ${alpacaResult.n_orders} orders submitted. ${alpacaResult.note}`
              : `✗ ${alpacaResult.note}`}
          </div>
        )}
        {alpacaPf?.equity_curve?.length > 2 && (
          <div className="mb-4">
            <div className="text-xs text-gray-500 mb-1">Equity curve (since inception)</div>
            <ResponsiveContainer width="100%" height={140}>
              <LineChart data={alpacaPf.equity_curve.map((v, i) => ({ i, equity: v }))}>
                <YAxis domain={['dataMin', 'dataMax']} hide />
                <Tooltip
                  formatter={(v) => `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`}
                  labelFormatter={() => ''}
                  contentStyle={CHART_TOOLTIP_STYLE}
                />
                <Line type="monotone" dataKey="equity" stroke="#059669" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {alpacaPf?.positions?.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-gray-100 text-gray-400">
                <th className="text-left py-1">Symbol</th><th className="text-right">Qty</th>
                <th className="text-right">Price</th><th className="text-right">Mkt Val</th><th className="text-right">P&L</th>
              </tr></thead>
              <tbody>
                {alpacaPf.positions.map(p => (
                  <tr key={p.symbol} className="border-b border-gray-50">
                    <td className="py-1 font-medium">{p.symbol}</td>
                    <td className="text-right">{p.qty.toFixed(2)}</td>
                    <td className="text-right">${p.current_price.toFixed(2)}</td>
                    <td className="text-right">${p.market_value.toFixed(0)}</td>
                    <td className={`text-right ${p.unrealized_pl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                      ${p.unrealized_pl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <RichTradeJournal tradeLog={tradeLog} onRefresh={loadTradeLog} />

    </div>
  )
}
