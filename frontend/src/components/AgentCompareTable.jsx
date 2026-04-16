const METRICS = [
  { key: 'sharpe',       label: 'Sharpe Ratio',   format: (v) => v?.toFixed(3) ?? '—' },
  { key: 'max_drawdown', label: 'Max Drawdown',    format: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—' },
  { key: 'cagr',         label: 'CAGR',            format: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—' },
  { key: 'total_return', label: 'Total Return',    format: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—' },
  { key: 'final_value',  label: 'Final Value',     format: (v) => v != null ? `$${v.toLocaleString()}` : '—' },
]

export default function AgentCompareTable({ results = [] }) {
  if (!results.length) return null

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 pr-4 text-gray-500 font-medium">Metric</th>
            {results.map((r) => (
              <th key={r.label} className="text-right py-2 px-4 text-gray-900 font-semibold">
                {r.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRICS.map(({ key, label, format }) => {
            // Find best value for highlighting
            const values = results.map((r) => r.metrics?.[key] ?? null)
            const numericValues = values.filter((v) => v !== null)
            const best = key === 'max_drawdown'
              ? Math.min(...numericValues)
              : Math.max(...numericValues)

            return (
              <tr key={key} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2.5 pr-4 text-gray-500">{label}</td>
                {results.map((r, i) => {
                  const val = r.metrics?.[key] ?? null
                  const isBest = val !== null && val === best && numericValues.length > 1
                  return (
                    <td
                      key={r.label}
                      className={`py-2.5 px-4 text-right font-medium ${
                        isBest ? 'text-green-600' : 'text-gray-900'
                      }`}
                    >
                      {format(val)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
