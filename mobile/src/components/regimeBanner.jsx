import { View, Text, StyleSheet } from 'react-native'
import { COLORS, RADIUS } from '../constants/theme'

const regimeConfig = {
  BULL:     { color: COLORS.green,  bg: COLORS.greenBg,  icon: '↑' },
  BEAR:     { color: COLORS.red,    bg: COLORS.redBg,    icon: '↓' },
  SIDEWAYS: { color: COLORS.amber,  bg: COLORS.amberBg,  icon: '→' },
}

export default function RegimeBanner({ regime, weights, source }) {
  if (!regime) return null
  const cfg = regimeConfig[regime] || regimeConfig.SIDEWAYS

  return (
    <View style={[styles.container, { backgroundColor: cfg.bg, borderColor: cfg.color + '40' }]}>
      <View style={styles.left}>
        <Text style={[styles.icon, { color: cfg.color }]}>{cfg.icon}</Text>
        <View>
          <Text style={[styles.label, { color: cfg.color }]}>{regime} REGIME</Text>
          <Text style={styles.sub}>
            {source === 'live' ? 'From live index data' : source === 'unavailable' ? 'Data unavailable' : 'Current market context'}
          </Text>
        </View>
      </View>
      {weights && (
        <View style={styles.weights}>
          {[['XGB', weights.xgb], ['LSTM', weights.lstm], ['PPO', weights.ppo]].map(([k, v]) => (
            <View key={k} style={styles.weightItem}>
              <Text style={styles.weightLabel}>{k}</Text>
              <Text style={styles.weightVal}>{Math.round((v || 0) * 100)}%</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderRadius: RADIUS.md,
    paddingVertical: 12,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  left: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  icon: { fontSize: 20, fontWeight: '700', marginRight: 4 },
  label: { fontSize: 13, fontWeight: '700', letterSpacing: 0.5 },
  sub: { fontSize: 11, color: COLORS.textMuted, marginTop: 1 },
  weights: { flexDirection: 'row', gap: 10 },
  weightItem: { alignItems: 'center' },
  weightLabel: { fontSize: 9, color: COLORS.textMuted, textTransform: 'uppercase' },
  weightVal: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '600' },
})
