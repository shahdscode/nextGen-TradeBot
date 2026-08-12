import { useState } from 'react'
import { Link } from 'react-router-dom'
import DecisionExplorerModal from './DecisionExplorerModal'
import { computeAIConfidence, computeMarketSummary } from '../utils/signalVotes'

const BASE_MODELS = ['ppo', 'sac', 'xgboost', 'lstm', 'a2c', 'ddpg', 'td3']

function Check({ ok }) {
  return <span className={ok ? 'text-emerald-400' : 'text-gray-600'}>{ok ? '✓' : '○'}</span>
}

export function ActiveStrategyCard({ metaStatus, weights }) {
  const metaLive = metaStatus?.loaded
  const ewma = metaStatus?.ewma_initialized
  const fusionLabel = ewma ? 'EWMA Adaptive' : metaLive ? 'Meta-Learner Stack' : 'Fixed Regime Weights'
  const healthy = metaLive || ewma

  return (
    <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Active Strategy</h3>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-white font-medium">Meta-Learner</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${metaLive ? 'bg-emerald-500/20 text-emerald-300' : 'bg-gray-700 text-gray-400'}`}>
            {metaLive ? '✓ Live' : 'Not loaded'}
          </span>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase tracking-wide mb-1.5">Base Models</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {BASE_MODELS.map((m) => (
              <div key={m} className="flex items-center gap-1.5 text-gray-300">
                <Check ok={metaLive || weights?.[m] != null} />
                {m === 'xgboost' ? 'XGBoost' : m.toUpperCase()}
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between text-xs border-t border-white/5 pt-2">
          <span className="text-gray-500 cursor-help"
            title="How the 7 base models are combined. EWMA Adaptive dynamically weights each model by its recent accuracy — models that have been right lately count more.">
            Fusion ⓘ
          </span>
          <span className="text-teal-300">{fusionLabel}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500">Status</span>
          <span className={healthy ? 'text-emerald-400' : 'text-amber-400'}>{healthy ? 'Healthy' : 'Fallback mode'}</span>
        </div>
      </div>
    </div>
  )
}

export function AIConfidenceCard({ signals }) {
  const { pct, label, detail } = computeAIConfidence(signals)
  const color = label === 'HIGH' ? 'text-emerald-400' : label === 'MEDIUM' ? 'text-amber-400' : 'text-red-400'
  const ring = label === 'HIGH' ? 'border-emerald-500/40' : label === 'MEDIUM' ? 'border-amber-500/40' : 'border-red-500/40'

  return (
    <div className={`bg-gray-900/60 border rounded-xl p-5 ${ring}`}>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Today&apos;s AI Confidence</h3>
      {pct != null ? (
        <>
          <div className={`text-4xl font-bold ${color}`}>{pct}%</div>
          <div className={`text-sm font-semibold mt-1 ${color}`}>{label}</div>
          <p className="text-xs text-gray-500 mt-2">{detail}</p>
        </>
      ) : (
        <p className="text-sm text-gray-500">{detail}</p>
      )}
    </div>
  )
}

export function AIMarketSummaryCard({ signals, regime }) {
  const summary = computeMarketSummary(signals, regime)

  return (
    <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Current Market State</h3>
      <ul className="space-y-1.5 text-sm text-gray-300">
        <li className="flex justify-between gap-2">
          <span className="text-gray-500 cursor-help"
            title="The market regime is detected from price action and exists whether or not the AI has generated trading signals — they are separate things.">
            Market regime ⓘ
          </span>
          <span className="font-medium text-white">{summary.regime}</span>
        </li>
        <li className="flex justify-between gap-2">
          <span className="text-gray-500">Signal mix</span>
          <span>
            <span className="text-emerald-400">{summary.counts.BUY} BUY</span>
            {' · '}
            <span className="text-amber-400">{summary.counts.HOLD} HOLD</span>
            {' · '}
            <span className="text-red-400">{summary.counts.SELL} SELL</span>
          </span>
        </li>
        <li className="flex justify-between gap-2">
          <span className="text-gray-500">Est. portfolio risk</span>
          <span className="text-white">{summary.estRisk}</span>
        </li>
        {summary.opportunities.length > 0 && (
          <li className="pt-1 border-t border-white/5">
            <span className="text-gray-500 text-xs block mb-1">Largest opportunities</span>
            <span className="text-teal-300 text-xs font-medium">{summary.opportunities.join(', ')}</span>
          </li>
        )}
      </ul>
    </div>
  )
}

export function ModelHealthCard({ metaStatus }) {
  return (
    <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Model Health</h3>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">Meta loaded</span>
          <span className={metaStatus?.loaded ? 'text-emerald-400' : 'text-gray-500'}>
            {metaStatus?.loaded ? '✓' : '—'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">EWMA tracker</span>
          <span className={metaStatus?.ewma_initialized ? 'text-emerald-400' : 'text-gray-500'}>
            {metaStatus?.ewma_initialized ? 'Initialized' : 'Pending'}
          </span>
        </div>
        {metaStatus?.calibrator_path && (
          <div className="flex justify-between">
            <span className="text-gray-500">Calibrator</span>
            <span className="text-emerald-400 text-xs">Active</span>
          </div>
        )}
      </div>
    </div>
  )
}

export function RecentSignalsPanel({ signals, market }) {
  const top = (signals || []).slice(0, 8)
  return (
    <div className="bg-gray-900/60 border border-white/10 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Latest AI Signals</h3>
        <Link to="/app/signals" className="text-[10px] text-teal-400 hover:text-teal-300">View all →</Link>
      </div>
      {top.length === 0 ? (
        <p className="text-xs text-gray-500">No signals in the last 48h for {market.toUpperCase()}.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {top.map((s) => (
            <span
              key={s.id || s.ticker}
              className={`text-xs px-2.5 py-1 rounded-lg border ${
                s.action === 'BUY'
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  : s.action === 'SELL'
                  ? 'bg-red-500/10 border-red-500/30 text-red-300'
                  : 'bg-amber-500/10 border-amber-500/30 text-amber-200'
              }`}
            >
              {s.action} {s.ticker}
              {s.confidence_pct != null && (
                <span className="opacity-70 ml-1">{s.confidence_pct}%</span>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function TradeJournalRow({ trade, onExplore }) {
  return (
    <div className="border border-white/10 rounded-lg overflow-hidden bg-gray-950/40">
      <div className="w-full p-3 flex items-center gap-2">
        <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${
          trade.action === 'BUY' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-red-500/20 text-red-300'
        }`}>
          {trade.action}
        </span>
        <span className="font-medium text-sm text-white">{trade.ticker}</span>
        {trade.meta_prob != null && (
          <span className="text-[10px] text-gray-400">meta {(trade.meta_prob * 100).toFixed(0)}%</span>
        )}
        <span className="ml-auto text-[10px] text-gray-500">
          {trade.created_at ? new Date(trade.created_at).toLocaleString() : ''}
        </span>
        <button
          type="button"
          onClick={() => onExplore(trade.id)}
          className="text-[10px] px-2 py-1 rounded border border-teal-500/30 text-teal-400 hover:bg-teal-500/10"
        >
          Explore
        </button>
      </div>
    </div>
  )
}

export function RichTradeJournal({ tradeLog, onRefresh }) {
  const [exploreId, setExploreId] = useState(null)

  return (
    <div className="bg-gray-900/60 border border-white/10 rounded-xl p-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-white">Trade Journal — why each trade happened</h2>
        <button
          type="button"
          onClick={onRefresh}
          className="px-3 py-1.5 text-xs rounded-lg border border-white/10 text-gray-400 hover:text-white hover:bg-white/5"
        >
          Refresh
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Populates after your first meta rebalance. Click <strong className="text-gray-400">Explore</strong> for the full decision trace.
      </p>
      {tradeLog.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-6 text-center">
          <p className="text-sm text-gray-400 mb-1">No trades logged yet</p>
          <p className="text-xs text-gray-500">
            Run <strong className="text-gray-300">Rebalance (execute)</strong> on the simulator or{' '}
            <strong className="text-gray-300">Rebalance Alpaca with Model</strong> using meta-learner mode.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {tradeLog.map((t) => (
            <TradeJournalRow key={t.id} trade={t} onExplore={setExploreId} />
          ))}
        </div>
      )}
      <DecisionExplorerModal tradeId={exploreId} onClose={() => setExploreId(null)} />
    </div>
  )
}

export function InsightsDashboard({ signals, regime, metaStatus, weights, market }) {
  return (
    <div className="mb-8 space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <ActiveStrategyCard metaStatus={metaStatus} weights={weights} />
        <AIConfidenceCard signals={signals} />
        <AIMarketSummaryCard signals={signals} regime={regime} />
        <ModelHealthCard metaStatus={metaStatus} />
      </div>
      <RecentSignalsPanel signals={signals} market={market} />
    </div>
  )
}
