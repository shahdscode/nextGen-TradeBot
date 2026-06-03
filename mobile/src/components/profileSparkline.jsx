import Svg, { Polyline } from 'react-native-svg'
import { COLORS } from '../constants/theme'

/** Compact equity sparkline for profile account overview card. */
export default function ProfileSparkline({
  data = [],
  width = 140,
  height = 48,
  color = COLORS.purple,
}) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width
      const y = height - ((v - min) / span) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <Svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <Polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
    </Svg>
  )
}
