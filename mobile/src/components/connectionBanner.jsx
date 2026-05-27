import { View, Text, StyleSheet, Platform } from 'react-native'
import { COLORS, RADIUS } from '../constants/theme'
import { resolveApiBaseUrl } from '../api/client'

export default function ConnectionBanner({ marketStatus, error }) {
  const apiUrl = resolveApiBaseUrl()
  const liveOk = marketStatus?.live_market_ok
  const demoOn = marketStatus?.demo_fallback_enabled

  if (error) {
    return (
      <View style={[styles.box, styles.error]}>
        <Text style={styles.title}>Cannot reach API</Text>
        <Text style={styles.body}>{error}</Text>
        <Text style={styles.mono} numberOfLines={2}>{apiUrl}</Text>
        <Text style={styles.hint}>Same Wi‑Fi: cd mobile && npm run sync-api-ip</Text>
      </View>
    )
  }

  if (marketStatus && !liveOk) {
    return (
      <View style={[styles.box, demoOn ? styles.warn : styles.error]}>
        <Text style={styles.title}>
          {demoOn ? 'Using demo market data' : 'Live market data unavailable'}
        </Text>
        <Text style={styles.body}>{marketStatus.message}</Text>
      </View>
    )
  }

  return null
}

const styles = StyleSheet.create({
  box: {
    borderRadius: RADIUS.md,
    borderWidth: 1,
    padding: 12,
    marginBottom: 14,
  },
  error: { backgroundColor: COLORS.redBg, borderColor: COLORS.red + '55' },
  warn: { backgroundColor: COLORS.amberBg, borderColor: COLORS.amber + '55' },
  title: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 4 },
  body: { fontSize: 12, color: COLORS.textSecondary, lineHeight: 18 },
  mono: { fontSize: 10, color: COLORS.textMuted, marginTop: 6, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  hint: { fontSize: 11, color: COLORS.textMuted, marginTop: 6 },
})
