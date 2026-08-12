import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts'
import { CHART_TOOLTIP_STYLE } from '../chartTheme'

const COLORS = [
  '#14b8a6', '#6366f1', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#64748b',
]

export function AllocationDonut({ title, data, emptyHint }) {
  const rows = (data || []).filter((d) => d.value > 0)
  if (!rows.length) {
    return (
      <div className="bg-gray-950/50 rounded-lg border border-white/5 p-4 h-full min-h-[220px] flex flex-col">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">{title}</h4>
        <p className="text-xs text-gray-600 m-auto text-center px-4">{emptyHint}</p>
      </div>
    )
  }

  return (
    <div className="bg-gray-950/50 rounded-lg border border-white/5 p-4">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">{title}</h4>
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={rows}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={48}
            outerRadius={72}
            paddingAngle={2}
          >
            {rows.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip
            formatter={(v) => [`${Number(v).toFixed(1)}%`, 'Allocation']}
            contentStyle={CHART_TOOLTIP_STYLE}
          />
          <Legend
            layout="vertical"
            align="right"
            verticalAlign="middle"
            iconSize={8}
            wrapperStyle={{ fontSize: 10, color: '#9ca3af' }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

function Metric({ label, value, sub }) {
  return (
    <div className="bg-gray-950/50 rounded-lg border border-white/5 px-3 py-2.5">
      <p className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-sm font-semibold text-white mt-0.5">{value}</p>
      {sub && <p className="text-[10px] text-gray-500 mt-0.5">{sub}</p>}
    </div>
  )
}

const concentrationLevel = (pct) =>
  pct == null ? null : pct >= 50 ? 'High' : pct >= 30 ? 'Moderate' : 'Low'

// Interpretation of the effective-holdings (inverse-HHI) score. Bounded by the
// number of invested holdings, so the buckets read relative to a small universe.
const diversificationText = (n) => {
  if (n == null) return ''
  if (n < 2) return 'highly concentrated'
  if (n < 4) return 'concentrated'
  if (n < 7) return 'moderately diversified'
  return 'well diversified'
}

export default function PortfolioIntelligence({ analytics, source, onSourceChange }) {
  const data = analytics?.[source]
  const hasData = data?.has_positions || (data?.holdings_count > 0) || (data?.cash_pct < 100 && data?.portfolio_value > 0)
  const conc = concentrationLevel(data?.largest_position?.pct)

  return (
    <div className="bg-gray-900/60 border border-white/10 rounded-xl p-6 mb-8">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Portfolio Intelligence</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Viewing the <span className="text-teal-300 font-medium">
              {source === 'sim' ? 'Internal Simulator' : 'Alpaca paper'}</span> portfolio ·
            allocation, diversification &amp; risk
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide">Portfolio</span>
          <div className="flex rounded-lg border border-white/10 overflow-hidden text-xs">
            {['sim', 'alpaca'].map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => onSourceChange(key)}
                className={`px-3 py-1.5 transition-colors ${
                  source === key
                    ? 'bg-teal-600/30 text-teal-200'
                    : 'bg-gray-950/40 text-gray-500 hover:text-gray-300'
                }`}
              >
                {key === 'sim' ? 'Simulator' : 'Alpaca'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {conc === 'High' && data.largest_position && (
        <div className="mb-4 text-xs rounded-lg px-3 py-2 bg-amber-500/10 border border-amber-500/30 text-amber-300">
          ⚠️ High concentration — {data.largest_position.symbol} is {data.largest_position.pct}% of the portfolio.
        </div>
      )}

      {!data ? (
        <p className="text-sm text-gray-500">Loading portfolio analytics…</p>
      ) : !hasData && data.cash_pct >= 99.9 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-8 text-center">
          <p className="text-sm text-gray-400 mb-1">No invested positions yet</p>
          <p className="text-xs text-gray-500">
            Run a meta rebalance on the {source === 'sim' ? 'simulator' : 'Alpaca broker'} below to build a portfolio.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2 mb-4">
            <Metric label="Holdings" value={data.holdings_count ?? 0} />
            <Metric
              label="Largest Position"
              value={data.largest_position ? `${data.largest_position.symbol}` : '—'}
              sub={data.largest_position ? `${data.largest_position.pct}% · ${conc} conc.` : undefined}
            />
            <Metric
              label="Top Sector"
              value={data.largest_sector?.name ?? '—'}
              sub={data.largest_sector ? `${data.largest_sector.value}%` : undefined}
            />
            <Metric label="Cash" value={`${data.cash_pct ?? 0}%`} />
            <Metric
              label="Diversification"
              value={data.diversification_score ?? '—'}
              sub={data.diversification_score != null
                ? `effective names — ${diversificationText(data.diversification_score)}`
                : 'effective # names'}
            />
            <Metric
              label="Avg Holding"
              value={data.avg_holding_days != null ? `${data.avg_holding_days}d` : '—'}
            />
            <Metric
              label="Portfolio Beta"
              value={data.portfolio_beta != null ? data.portfolio_beta : '—'}
              sub={data.portfolio_beta != null ? 'vs SPY (60d)' : 'needs US holdings'}
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AllocationDonut
              title="Sector Allocation"
              data={data.sector_allocation}
              emptyHint="Sector breakdown appears once you hold US equities."
            />
            <AllocationDonut
              title="Symbol Allocation"
              data={data.symbol_allocation}
              emptyHint="Symbol weights appear after your first rebalance."
            />
          </div>

          {data.portfolio_value > 0 && (
            <p className="text-[10px] text-gray-600 mt-3 text-right">
              Portfolio value ${Number(data.portfolio_value).toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </p>
          )}
        </>
      )}
    </div>
  )
}
