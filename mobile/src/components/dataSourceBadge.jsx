import { View, Text, StyleSheet } from 'react-native'
import { COLORS } from '../constants/theme'

const LABELS = {
  live: { text: 'Live', color: COLORS.green, bg: COLORS.greenBg },
  dataset: { text: 'Training data', color: COLORS.amber, bg: 'rgba(245,158,11,0.15)' },
  synthetic: { text: 'Demo', color: COLORS.amber, bg: 'rgba(245,158,11,0.15)' },
  demo: { text: 'Demo', color: COLORS.amber, bg: 'rgba(245,158,11,0.15)' },
  unavailable: { text: 'Unavailable', color: COLORS.red, bg: COLORS.redBg },
}

export default function DataSourceBadge({ source }) {
  if (!source) return null
  const cfg = LABELS[source] || { text: source, color: COLORS.textMuted, bg: 'rgba(255,255,255,0.06)' }
  return (
    <View style={[styles.badge, { backgroundColor: cfg.bg }]}>
      <Text style={[styles.text, { color: cfg.color }]}>{cfg.text}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  badge: { borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2 },
  text: { fontSize: 10, fontWeight: '600' },
})
