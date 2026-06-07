import { useState } from 'react'
import { View, Text, StyleSheet } from 'react-native'
import Svg, { Rect, Line, Text as SvgText, G } from 'react-native-svg'
import { COLORS } from '../constants/theme'

/**
 * Tappable candlestick chart from OHLC rows.
 * data: [{ date, open, high, low, close, volume? }]
 * Tap/drag on the chart to inspect a candle's O/H/L/C via a crosshair + tooltip.
 */
export default function CandleChart({
  data = [],
  width = 340,
  height = 240,
  padding = { top: 14, right: 10, bottom: 28, left: 54 },
}) {
  const [active, setActive] = useState(null)   // index of inspected candle

  if (!data || data.length < 2) return <View style={{ width, height }} />

  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  let max = Math.max(...data.map((d) => d.high))
  let min = Math.min(...data.map((d) => d.low))
  const pad = (max - min) * 0.06 || 1
  max += pad; min -= pad
  const span = max - min || 1

  const n = data.length
  const slot = chartW / n
  // Body width scales with density: wide for few candles, thin for many.
  const bodyW = Math.max(1.5, Math.min(slot * 0.7, 14))

  const x = (i) => padding.left + slot * i + slot / 2
  const y = (v) => padding.top + chartH - ((v - min) / span) * chartH

  const levels = 4
  const yLabels = Array.from({ length: levels + 1 }, (_, i) => min + (span * i) / levels)
  const fmt = (v) => (Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2))

  // Date labels (skip when very dense to avoid overlap)
  const xIdxs = [0, Math.floor(n / 2), n - 1]

  // Last close → reference line
  const last = data[n - 1]
  const lastUp = last.close >= data[Math.max(0, n - 2)].close

  // Touch → nearest candle index
  const pickIndex = (locationX) => {
    const i = Math.round((locationX - padding.left - slot / 2) / slot)
    return Math.max(0, Math.min(n - 1, i))
  }
  const onTouch = (e) => setActive(pickIndex(e.nativeEvent.locationX))

  const sel = active != null ? data[active] : null
  // Tooltip horizontal placement (keep on-screen)
  const tipW = 132
  let tipX = sel != null ? x(active) - tipW / 2 : 0
  tipX = Math.max(4, Math.min(width - tipW - 4, tipX))

  return (
    <View style={{ width, height }}>
      <Svg width={width} height={height}>
        {/* gridlines + price axis */}
        {yLabels.map((v, i) => (
          <G key={`y-${i}`}>
            <Line x1={padding.left} y1={y(v)} x2={width - padding.right} y2={y(v)}
                  stroke={COLORS.cardBorder} strokeWidth={0.5} />
            <SvgText x={padding.left - 6} y={y(v) + 3} fontSize="9"
                     fill={COLORS.textMuted} textAnchor="end">{fmt(v)}</SvgText>
          </G>
        ))}

        {/* last-close reference line */}
        <Line x1={padding.left} y1={y(last.close)} x2={width - padding.right} y2={y(last.close)}
              stroke={lastUp ? COLORS.green : COLORS.red} strokeWidth={0.8}
              strokeDasharray="3,3" opacity={0.6} />

        {/* candles */}
        {data.map((d, i) => {
          const up = d.close >= d.open
          const color = up ? COLORS.green : COLORS.red
          const cx = x(i)
          const bodyTop = y(Math.max(d.open, d.close))
          const bodyH = Math.max(1, y(Math.min(d.open, d.close)) - bodyTop)
          const dim = active != null && active !== i ? 0.55 : 1
          return (
            <G key={`c-${i}`} opacity={dim}>
              <Line x1={cx} y1={y(d.high)} x2={cx} y2={y(d.low)} stroke={color} strokeWidth={1} />
              <Rect x={cx - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={color} rx={0.5} />
            </G>
          )
        })}

        {/* crosshair on the selected candle */}
        {sel != null && (
          <Line x1={x(active)} y1={padding.top} x2={x(active)} y2={padding.top + chartH}
                stroke={COLORS.textSecondary} strokeWidth={0.8} strokeDasharray="2,2" />
        )}

        {/* date labels (only when not inspecting) */}
        {sel == null && xIdxs.map((idx, i) => (
          <SvgText key={`d-${i}`} x={x(idx)} y={height - 9} fontSize="9" fill={COLORS.textMuted}
                   textAnchor={i === 0 ? 'start' : i === xIdxs.length - 1 ? 'end' : 'middle'}>
            {(data[idx]?.date || '').slice(5)}
          </SvgText>
        ))}
      </Svg>

      {/* Transparent touch layer */}
      <View
        style={StyleSheet.absoluteFill}
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderGrant={onTouch}
        onResponderMove={onTouch}
        onResponderRelease={() => { /* keep selection visible */ }}
      />

      {/* OHLC tooltip */}
      {sel != null && (
        <View style={[styles.tip, { left: tipX, top: padding.top }]}>
          <Text style={styles.tipDate}>{sel.date}</Text>
          <View style={styles.tipRow}><Text style={styles.tipLbl}>O</Text><Text style={styles.tipVal}>{fmt(sel.open)}</Text></View>
          <View style={styles.tipRow}><Text style={styles.tipLbl}>H</Text><Text style={[styles.tipVal, { color: COLORS.green }]}>{fmt(sel.high)}</Text></View>
          <View style={styles.tipRow}><Text style={styles.tipLbl}>L</Text><Text style={[styles.tipVal, { color: COLORS.red }]}>{fmt(sel.low)}</Text></View>
          <View style={styles.tipRow}><Text style={styles.tipLbl}>C</Text>
            <Text style={[styles.tipVal, { color: sel.close >= sel.open ? COLORS.green : COLORS.red }]}>{fmt(sel.close)}</Text>
          </View>
        </View>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  tip: {
    position: 'absolute', width: 132, backgroundColor: COLORS.bg,
    borderWidth: 1, borderColor: COLORS.cardBorder, borderRadius: 8, padding: 8,
  },
  tipDate: { color: COLORS.textPrimary, fontSize: 11, fontWeight: '700', marginBottom: 4 },
  tipRow: { flexDirection: 'row', justifyContent: 'space-between' },
  tipLbl: { color: COLORS.textMuted, fontSize: 11, width: 14 },
  tipVal: { color: COLORS.textPrimary, fontSize: 11, fontWeight: '600', fontVariant: ['tabular-nums'] },
})
