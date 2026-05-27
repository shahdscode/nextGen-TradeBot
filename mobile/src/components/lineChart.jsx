import { View } from 'react-native'
import Svg, { Path, Line, Text as SvgText, Circle } from 'react-native-svg'
import { COLORS } from '../constants/theme'

export default function LineChart({
  data = [],          // [{ date, value }]
  benchmark = [],     // [{ date, value }]
  width = 340,
  height = 160,
  color = COLORS.teal,
  benchmarkColor = COLORS.textMuted,
  padding = { top: 10, right: 10, bottom: 30, left: 46 },
}) {
  if (data.length < 2) return <View style={{ width, height }} />

  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  const allValues = [
    ...data.map((d) => d.value),
    ...benchmark.map((d) => d.value),
  ]
  const minVal = Math.min(...allValues)
  const maxVal = Math.max(...allValues)
  const range = maxVal - minVal || 1

  const toX = (i, len) => (i / (len - 1)) * chartW
  const toY = (v) => chartH - ((v - minVal) / range) * chartH

  const makePath = (pts) =>
    pts
      .map((d, i) => `${i === 0 ? 'M' : 'L'}${toX(i, pts.length).toFixed(1)},${toY(d.value).toFixed(1)}`)
      .join(' ')

  // Y axis labels
  const yLabels = [minVal, (minVal + maxVal) / 2, maxVal].map((v) => ({
    y: toY(v),
    label: v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v.toFixed(0)}`,
  }))

  // X axis labels (first + last + 2 in between)
  const xIndices = [0, Math.floor(data.length / 3), Math.floor((data.length * 2) / 3), data.length - 1]
  const xLabels = [...new Set(xIndices)].map((i) => ({
    x: toX(i, data.length),
    label: data[i]?.date?.slice(5) || '',
  }))

  return (
    <Svg width={width} height={height}>
      {/* Y grid lines */}
      {yLabels.map((yl, i) => (
        <Line
          key={i}
          x1={padding.left}
          y1={yl.y + padding.top}
          x2={padding.left + chartW}
          y2={yl.y + padding.top}
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={1}
        />
      ))}

      {/* Y labels */}
      {yLabels.map((yl, i) => (
        <SvgText
          key={i}
          x={padding.left - 6}
          y={yl.y + padding.top + 4}
          textAnchor="end"
          fontSize={10}
          fill={COLORS.textMuted}
        >
          {yl.label}
        </SvgText>
      ))}

      {/* X labels */}
      {xLabels.map((xl, i) => (
        <SvgText
          key={i}
          x={xl.x + padding.left}
          y={height - 6}
          textAnchor="middle"
          fontSize={10}
          fill={COLORS.textMuted}
        >
          {xl.label}
        </SvgText>
      ))}

      {/* Benchmark line */}
      {benchmark.length > 1 && (
        <Path
          d={makePath(benchmark)}
          stroke={benchmarkColor}
          strokeWidth={1.5}
          fill="none"
          strokeDasharray="4,3"
          transform={`translate(${padding.left},${padding.top})`}
        />
      )}

      {/* Main line */}
      <Path
        d={makePath(data)}
        stroke={color}
        strokeWidth={2}
        fill="none"
        transform={`translate(${padding.left},${padding.top})`}
      />

      {/* Last point dot */}
      <Circle
        cx={toX(data.length - 1, data.length) + padding.left}
        cy={toY(data[data.length - 1].value) + padding.top}
        r={4}
        fill={color}
      />
    </Svg>
  )
}
