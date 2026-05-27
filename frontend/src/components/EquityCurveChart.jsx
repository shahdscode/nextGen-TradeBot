import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine,
  Scatter, ScatterChart,
} from 'recharts'

const agentColors = ['#2563eb', '#16a34a', '#dc2626', '#d97706']

const BuyDot = (props) => {
  const { cx, cy } = props
  if (!cx || !cy) return null
  return (
    <g>
      <polygon
        points={`${cx},${cy - 8} ${cx - 6},${cy + 4} ${cx + 6},${cy + 4}`}
        fill="#16a34a"
        stroke="#fff"
        strokeWidth={1}
      />
    </g>
  )
}

const SellDot = (props) => {
  const { cx, cy } = props
  if (!cx || !cy) return null
  return (
    <g>
      <polygon
        points={`${cx},${cy + 8} ${cx - 6},${cy - 4} ${cx + 6},${cy - 4}`}
        fill="#dc2626"
        stroke="#fff"
        strokeWidth={1}
      />
    </g>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: 'var(--color-background-primary)',
      border: '0.5px solid var(--color-border-secondary)',
      borderRadius: 8,
      padding: '10px 14px',
      fontSize: 12,
    }}>
      <p style={{ color: 'var(--color-text-secondary)', marginBottom: 6 }}>{label}</p>
      {payload.map((p) => (
        p.value != null && (
          <div key={p.name} style={{ display: 'flex', justifyContent: 'space-between', gap: 16, color: p.color }}>
            <span>{p.name}</span>
            <span style={{ fontWeight: 500 }}>{p.value}%</span>
          </div>
        )
      ))}
    </div>
  )
}

/**
 * curves: [{ label, accountValue, dates, trades }]
 * benchmark: { account_value, dates }
 * showTrades: boolean
 */
export default function EquityCurveChart({ curves = [], benchmark = null, showTrades = true }) {
  if (!curves.length || !curves[0]?.accountValue?.length) {
    return (
      <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
        No data to display
      </div>
    )
  }

  const len = Math.max(...curves.map((c) => c.accountValue?.length ?? 0))
  const dates = curves[0].dates ?? []

  // Build a map of date → buy/sell signals from trades
  const tradeMap = {}
  if (showTrades && curves.length === 1) {
    const trades = curves[0].trades ?? []
    trades.forEach((t) => {
      if (!tradeMap[t.date]) tradeMap[t.date] = []
      tradeMap[t.date].push(t.action)
    })
  }

  // Align benchmark dates to agent dates for overlay
  const benchMap = {}
  if (benchmark?.account_value?.length && benchmark?.dates?.length) {
    const bStart = benchmark.account_value[0]
    benchmark.dates.forEach((d, i) => {
      benchMap[d] = benchmark.account_value[i] != null
        ? +((benchmark.account_value[i] / bStart) * 100).toFixed(2)
        : null
    })
  }

  const data = Array.from({ length: len }, (_, i) => {
    const date = dates[i] ?? `T+${i}`
    const row = { date }

    curves.forEach((c) => {
      const start = c.accountValue[0] || 1
      row[c.label] = c.accountValue[i] != null
        ? +((c.accountValue[i] / start) * 100).toFixed(2)
        : null
    })

    // Benchmark value on same date
    if (benchmark?.account_value?.length) {
      row['S&P 500'] = benchMap[date] ?? null
    }

    // Trade signals — store the normalized portfolio value at that point so dots appear on the line
    const actions = tradeMap[date] || []
    if (actions.includes('buy')) {
      const start = curves[0].accountValue[0] || 1
      row['_buy'] = +((curves[0].accountValue[i] / start) * 100).toFixed(2)
    }
    if (actions.includes('sell')) {
      const start = curves[0].accountValue[0] || 1
      row['_sell'] = +((curves[0].accountValue[i] / start) * 100).toFixed(2)
    }

    return row
  })

  const tickInterval = Math.floor(len / 6)

  return (
    <div>
      {/* Legend for markers */}
      {showTrades && curves.length === 1 && (
        <div className="flex items-center gap-5 mb-3 text-xs text-gray-500">
          <div className="flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12">
              <polygon points="6,0 0,12 12,12" fill="#16a34a" />
            </svg>
            Buy
          </div>
          <div className="flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12">
              <polygon points="6,12 0,0 12,0" fill="#dc2626" />
            </svg>
            Sell
          </div>
          {benchmark?.account_value?.length > 0 && (
            <div className="flex items-center gap-1.5">
              <div className="w-5 border-t-2 border-dashed border-gray-400" />
              S&P 500
            </div>
          )}
        </div>
      )}

      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={data} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11 }}
            tickLine={false}
            interval={tickInterval}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />

          {/* Agent equity curves */}
          {curves.map((c, i) => (
            <Line
              key={c.label}
              type="monotone"
              dataKey={c.label}
              stroke={agentColors[i % agentColors.length]}
              dot={false}
              strokeWidth={2}
              connectNulls
            />
          ))}

          {/* S&P 500 benchmark */}
          {benchmark?.account_value?.length > 0 && (
            <Line
              type="monotone"
              dataKey="S&P 500"
              stroke="#9ca3af"
              dot={false}
              strokeWidth={1.5}
              strokeDasharray="5 5"
              connectNulls
            />
          )}

          {/* Buy markers — green upward triangles */}
          {showTrades && curves.length === 1 && (
            <Line
              dataKey="_buy"
              dot={<BuyDot />}
              activeDot={false}
              stroke="none"
              legendType="none"
              name="Buy signal"
              connectNulls={false}
            />
          )}

          {/* Sell markers — red downward triangles */}
          {showTrades && curves.length === 1 && (
            <Line
              dataKey="_sell"
              dot={<SellDot />}
              activeDot={false}
              stroke="none"
              legendType="none"
              name="Sell signal"
              connectNulls={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
