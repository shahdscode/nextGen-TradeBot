const fmtPct   = (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—'
const fmtNum   = (v, dp = 3) => v != null ? Number(v).toFixed(dp) : '—'
const fmtRatio = (v) => v != null ? Number(v).toFixed(3) : '—'

const metricDefs = [
  // Row 1 — risk-adjusted performance
  { key: 'sharpe',        label: 'Sharpe Ratio',      format: fmtRatio,  good: v => v >= 1  },
  { key: 'sortino',       label: 'Sortino Ratio',     format: fmtRatio,  good: v => v >= 1  },
  { key: 'calmar',        label: 'Calmar Ratio',      format: fmtRatio,  good: v => v >= 1  },
  { key: 'profit_factor', label: 'Profit Factor',     format: (v) => fmtNum(v, 2), good: v => v >= 1.2 },
  // Row 2 — returns
  { key: 'cagr',          label: 'CAGR',              format: fmtPct,    good: v => v > 0   },
  { key: 'total_return',  label: 'Total Return',      format: fmtPct,    good: v => v > 0   },
  { key: 'win_rate',      label: 'Win Rate',          format: fmtPct,    good: v => v >= 0.5},
  { key: 'max_drawdown',  label: 'Max Drawdown',      format: fmtPct,    good: v => v < 0.2, invert: true },
  // Row 3 — trade characteristics
  { key: 'avg_trade_return', label: 'Avg Trade Return', format: fmtPct,  good: v => v > 0   },
  { key: 'exposure_pct',     label: 'Exposure',         format: fmtPct,  good: () => true   },
  { key: 'turnover',         label: 'Turnover',         format: (v) => fmtNum(v, 2) + '×', good: v => v < 5 },
  { key: 'win_days',         label: 'Win Days',         format: (v) => v ?? '—', good: () => true },
]

function MetricTile({ label, value, good, invert }) {
  const isGood = good ? good(value) : null
  const color = value == null
    ? 'text-gray-400'
    : invert
      ? (value < 0.2 ? 'text-green-600' : value < 0.35 ? 'text-amber-500' : 'text-red-500')
      : (isGood ? 'text-green-600' : 'text-gray-800')

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <p className="text-xs text-gray-500 mb-1 truncate">{label}</p>
      <p className={`text-xl font-semibold ${color}`}>
        {value != null ? (typeof value === 'function' ? value() : value) : '—'}
      </p>
    </div>
  )
}

export default function MetricsCard({ metrics }) {
  return (
    <div className="space-y-2">
      {/* 4-column grid — 12 tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {metricDefs.map(({ key, label, format, good, invert }) => {
          const raw = metrics?.[key]
          const displayed = raw != null ? format(raw) : null
          return (
            <MetricTile
              key={key}
              label={label}
              value={displayed}
              good={raw != null ? () => good(raw) : null}
              invert={invert}
            />
          )
        })}
      </div>
    </div>
  )
}
