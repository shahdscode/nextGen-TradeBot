const cards = [
  { key: 'sharpe',       label: 'Sharpe Ratio',   format: (v) => v?.toFixed(3) ?? '—' },
  { key: 'max_drawdown', label: 'Max Drawdown',    format: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—' },
  { key: 'cagr',         label: 'CAGR',            format: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—' },
  { key: 'total_return', label: 'Total Return',    format: (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—' },
]

export default function MetricsCard({ metrics }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map(({ key, label, format }) => (
        <div key={key} className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-1">{label}</p>
          <p className="text-2xl font-semibold text-gray-900">
            {format(metrics?.[key])}
          </p>
        </div>
      ))}
    </div>
  )
}
