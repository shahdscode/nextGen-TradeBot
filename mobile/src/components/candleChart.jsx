import { View } from 'react-native'
import Svg, { Rect, Line, Text as SvgText, G } from 'react-native-svg'
import { COLORS } from '../constants/theme'

/**
 * Candlestick chart from OHLC rows.
 * data: [{ date, open, high, low, close }]
 */
export default function CandleChart({
  data = [],
  width = 340,
  height = 220,
  padding = { top: 12, right: 8, bottom: 26, left: 52 },
}) {
  if (!data || data.length < 2) return <View style={{ width, height }} />

  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  let max = Math.max(...data.map((d) => d.high))
  let min = Math.min(...data.map((d) => d.low))
  const pad = (max - min) * 0.05 || 1
  max += pad; min -= pad
  const span = max - min || 1

  const n = data.length
  const slot = chartW / n
  const bodyW = Math.max(1, Math.min(slot * 0.65, 12))

  const x = (i) => padding.left + slot * i + slot / 2
  const y = (v) => padding.top + chartH - ((v - min) / span) * chartH

  const levels = 4
  const yLabels = Array.from({ length: levels + 1 }, (_, i) => min + (span * i) / levels)
  const xIdxs = [0, Math.floor(n / 2), n - 1]
  const fmt = (v) => (v >= 1000 ? v.toFixed(0) : v.toFixed(2))

  return (
    <Svg width={width} height={height}>
      {/* gridlines + price labels */}
      {yLabels.map((v, i) => (
        <G key={`y-${i}`}>
          <Line x1={padding.left} y1={y(v)} x2={width - padding.right} y2={y(v)}
                stroke={COLORS.cardBorder} strokeWidth={0.5} />
          <SvgText x={padding.left - 6} y={y(v) + 3} fontSize="9"
                   fill={COLORS.textMuted} textAnchor="end">{fmt(v)}</SvgText>
        </G>
      ))}

      {/* candles: wick + body */}
      {data.map((d, i) => {
        const up = d.close >= d.open
        const color = up ? COLORS.green : COLORS.red
        const cx = x(i)
        const bodyTop = y(Math.max(d.open, d.close))
        const bodyH = Math.max(1, y(Math.min(d.open, d.close)) - bodyTop)
        return (
          <G key={`c-${i}`}>
            <Line x1={cx} y1={y(d.high)} x2={cx} y2={y(d.low)} stroke={color} strokeWidth={1} />
            <Rect x={cx - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={color} rx={0.5} />
          </G>
        )
      })}

      {/* date labels */}
      {xIdxs.map((idx, i) => (
        <SvgText key={`d-${i}`} x={x(idx)} y={height - 8} fontSize="9" fill={COLORS.textMuted}
                 textAnchor={i === 0 ? 'start' : i === xIdxs.length - 1 ? 'end' : 'middle'}>
          {(data[idx]?.date || '').slice(5)}
        </SvgText>
      ))}
    </Svg>
  )
}
