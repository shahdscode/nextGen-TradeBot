import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts'
import { CHART_GRID_STROKE, CHART_TICK_FILL, CHART_TOOLTIP_STYLE } from '../chartTheme'

export default function RewardCurveChart({ rewardCurve = [] }) {
  if (!rewardCurve?.length) {
    return (
      <div className="h-48 flex items-center justify-center text-gray-400 text-sm">
        No reward data yet
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={rewardCurve} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID_STROKE} />
        <XAxis
          dataKey="step"
          tick={{ fontSize: 11, fill: CHART_TICK_FILL }}
          tickLine={false}
          tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
        />
        <YAxis tick={{ fontSize: 11, fill: CHART_TICK_FILL }} tickLine={false} axisLine={false} />
        <Tooltip
          formatter={(v) => [v?.toFixed(2), 'Reward']}
          contentStyle={CHART_TOOLTIP_STYLE}
        />
        <Line
          type="monotone"
          dataKey="reward"
          stroke="#2dd4bf"
          dot={false}
          strokeWidth={2}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
