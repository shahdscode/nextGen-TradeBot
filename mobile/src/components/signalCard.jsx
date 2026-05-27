import { View, Text, StyleSheet } from 'react-native'
import { COLORS, RADIUS } from '../constants/theme'

const actionConfig = {
  BUY:  { color: COLORS.green, bg: COLORS.greenBg, border: COLORS.green + '40' },
  SELL: { color: COLORS.red,   bg: COLORS.redBg,   border: COLORS.red + '40'   },
  HOLD: { color: COLORS.amber, bg: COLORS.amberBg, border: COLORS.amber + '40' },
}

const riskColor = {
  LOW:    COLORS.green,
  MEDIUM: COLORS.amber,
  HIGH:   COLORS.red,
}

export default function SignalCard({ signal, compact = false }) {
  const cfg = actionConfig[signal.action] || actionConfig.HOLD
  const confPct = signal.confidence_pct ?? Math.round((signal.confidence || 0) * 100)
  const mb = signal.model_breakdown || {}
  const reasons = signal.shap_reasons || []

  return (
    <View style={[styles.card, { backgroundColor: cfg.bg, borderColor: cfg.border }]}>
      {/* Header row */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.ticker}>{signal.ticker}</Text>
          {signal.regime ? (
            <View style={styles.regimeChip}>
              <Text style={styles.regimeText}>{signal.regime}</Text>
            </View>
          ) : null}
        </View>
        <View style={[styles.actionBadge, { backgroundColor: cfg.color }]}>
          <Text style={styles.actionText}>{signal.action}</Text>
        </View>
      </View>

      {/* Confidence bar */}
      <View style={styles.confRow}>
        <Text style={styles.confLabel}>Confidence</Text>
        <Text style={[styles.confValue, { color: cfg.color }]}>{confPct}%</Text>
      </View>
      <View style={styles.barBg}>
        <View style={[styles.barFill, { width: `${confPct}%`, backgroundColor: cfg.color }]} />
      </View>

      {!compact && (
        <>
          {/* Model breakdown */}
          {mb.xgboost && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>MODEL SIGNALS</Text>
              {[
                { label: 'XGBoost', val: mb.xgboost?.probability },
                { label: 'LSTM',    val: mb.lstm?.probability },
                { label: 'PPO',     val: mb.ppo?.signal ?? mb.ppo?.probability },
              ].map(({ label, val }) => (
                <View key={label} style={styles.modelRow}>
                  <Text style={styles.modelLabel}>{label}</Text>
                  <View style={styles.modelBarBg}>
                    <View style={[styles.modelBarFill, { width: `${Math.round((val || 0) * 100)}%` }]} />
                  </View>
                  <Text style={styles.modelVal}>{val != null ? Math.round(val * 100) : '—'}%</Text>
                </View>
              ))}
            </View>
          )}

          {/* SHAP reasons */}
          {reasons.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>WHY</Text>
              {reasons.slice(0, 4).map((r, i) => (
                <View key={i} style={styles.shapRow}>
                  <Text style={styles.shapName} numberOfLines={1}>{r.name?.replace(/_/g, ' ')}</Text>
                  <View style={styles.shapBarBg}>
                    <View style={[styles.shapBarFill, { width: `${r.contribution}%`, backgroundColor: COLORS.teal }]} />
                  </View>
                  <Text style={styles.shapPct}>{r.contribution}%</Text>
                </View>
              ))}
            </View>
          )}
        </>
      )}

      {/* Footer */}
      <View style={styles.footer}>
        <View style={styles.footerLeft}>
          {signal.risk_level && (
            <Text style={[styles.riskText, { color: riskColor[signal.risk_level] || COLORS.textMuted }]}>
              {signal.risk_level} RISK
            </Text>
          )}
          {signal.stop_loss_pct && (
            <Text style={styles.stopLoss}>  Stop {signal.stop_loss_pct}%</Text>
          )}
        </View>
        {signal.sentiment?.score != null && (
          <Text style={styles.sentiment}>
            Sentiment {signal.sentiment.score > 0 ? '+' : ''}{signal.sentiment.score?.toFixed(2)}
          </Text>
        )}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: RADIUS.lg,
    padding: 16,
    marginBottom: 12,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 },
  ticker: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  regimeChip: { backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, paddingHorizontal: 8, paddingVertical: 2 },
  regimeText: { fontSize: 11, color: COLORS.textSecondary },
  actionBadge: { borderRadius: RADIUS.full, paddingHorizontal: 12, paddingVertical: 4 },
  actionText: { fontSize: 12, fontWeight: '800', color: '#fff', letterSpacing: 0.5 },
  confRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  confLabel: { fontSize: 12, color: COLORS.textMuted },
  confValue: { fontSize: 14, fontWeight: '700' },
  barBg: { height: 6, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, marginBottom: 14, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: RADIUS.full },
  section: { marginBottom: 12 },
  sectionTitle: { fontSize: 10, color: COLORS.textMuted, letterSpacing: 1, marginBottom: 8, textTransform: 'uppercase' },
  modelRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 6, gap: 8 },
  modelLabel: { fontSize: 12, color: COLORS.textSecondary, width: 50 },
  modelBarBg: { flex: 1, height: 4, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, overflow: 'hidden' },
  modelBarFill: { height: '100%', backgroundColor: COLORS.textMuted, borderRadius: RADIUS.full },
  modelVal: { fontSize: 12, color: COLORS.textSecondary, width: 32, textAlign: 'right' },
  shapRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 5, gap: 8 },
  shapName: { fontSize: 12, color: COLORS.textSecondary, width: 100 },
  shapBarBg: { flex: 1, height: 4, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, overflow: 'hidden' },
  shapBarFill: { height: '100%', borderRadius: RADIUS.full },
  shapPct: { fontSize: 11, color: COLORS.textMuted, width: 32, textAlign: 'right' },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingTop: 10, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.06)' },
  footerLeft: { flexDirection: 'row', alignItems: 'center' },
  riskText: { fontSize: 11, fontWeight: '600' },
  stopLoss: { fontSize: 11, color: COLORS.textMuted },
  sentiment: { fontSize: 11, color: COLORS.textMuted },
})
