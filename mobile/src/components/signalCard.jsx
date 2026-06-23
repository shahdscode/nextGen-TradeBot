import { View, Text, StyleSheet } from 'react-native'
import { COLORS, RADIUS } from '../constants/theme'

const actionConfig = {
  BUY:  { color: COLORS.green, bg: COLORS.greenBg, border: COLORS.green + '40', label: 'Bullish confidence' },
  SELL: { color: COLORS.red,   bg: COLORS.redBg,   border: COLORS.red + '40',   label: 'Bearish conviction' },
  HOLD: { color: COLORS.amber, bg: COLORS.amberBg, border: COLORS.amber + '40', label: 'Neutral confidence' },
}

function displayPct(signal) {
  const conf = signal.confidence_pct ?? Math.round((signal.confidence || 0) * 100)
  return signal.action === 'SELL' ? 100 - conf : conf
}

export default function SignalCard({ signal, compact = false }) {
  const cfg = actionConfig[signal.action] || actionConfig.HOLD
  const pct = displayPct(signal)
  const mb = signal.model_breakdown || {}
  const reasons = signal.shap_reasons || []
  const market = (signal.market || 'us').toUpperCase()

  return (
    <View style={[styles.card, { backgroundColor: cfg.bg, borderColor: cfg.border }]}>
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.signalLabel}>SIGNAL</Text>
          <View style={styles.titleRow}>
            <Text style={styles.ticker}>{signal.ticker}</Text>
            <View style={styles.marketChip}><Text style={styles.marketText}>{market}</Text></View>
          </View>
        </View>
        <View style={[styles.actionBadge, { backgroundColor: cfg.color }]}>
          <Text style={styles.actionText}>{signal.action}</Text>
        </View>
      </View>

      <View style={styles.confRow}>
        <Text style={styles.confLabel}>{cfg.label}</Text>
        <Text style={[styles.confValue, { color: cfg.color }]}>{pct}%</Text>
      </View>
      <View style={styles.barBg}>
        <View style={[styles.barFill, { width: `${pct}%`, backgroundColor: cfg.color }]} />
      </View>
      <Text style={styles.fusedNote}>
        Fused score {Math.round((signal.confidence || 0) * 100)}% · XGB + LSTM + RL
      </Text>

      {!compact && (
        <>
          {mb.xgboost && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>MODEL SIGNALS</Text>
              {[
                { label: 'XGB', val: mb.xgboost?.probability },
                { label: 'LSTM', val: mb.lstm?.probability },
                { label: 'PPO', val: mb.ppo?.signal ?? mb.ppo?.probability },
              ].map(({ label, val }) => (
                <View key={label} style={styles.modelRow}>
                  <Text style={styles.modelLabel}>{label}</Text>
                  <View style={styles.modelBarBg}>
                    <View style={[styles.modelBarFill, {
                      width: `${Math.round((val || 0) * 100)}%`,
                      backgroundColor: (val || 0) >= 0.5 ? COLORS.green : COLORS.red,
                    }]} />
                  </View>
                  <Text style={styles.modelVal}>{val != null ? Math.round(val * 100) : '—'}%</Text>
                </View>
              ))}
            </View>
          )}

          {reasons.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>WHY (XGB SHAP)</Text>
              {reasons.slice(0, 3).map((r, i) => (
                <View key={i} style={styles.shapRow}>
                  <Text style={styles.shapName} numberOfLines={1}>{r.name?.replace(/_/g, ' ')}</Text>
                  <Text style={styles.shapPct}>{r.contribution}%</Text>
                </View>
              ))}
            </View>
          )}
        </>
      )}

      <View style={styles.footer}>
        <View style={styles.footerLeft}>
          {signal.regime ? <Text style={styles.meta}>{signal.regime} · </Text> : null}
          {signal.risk_level ? (
            <Text style={[styles.riskText, { color: cfg.color }]}>{signal.risk_level} RISK</Text>
          ) : null}
          {signal.stop_loss_pct ? (
            <Text style={styles.stopLoss}>  Stop {signal.stop_loss_pct}%</Text>
          ) : null}
        </View>
        {signal.sentiment?.score != null && (
          <Text style={styles.sentiment}>
            Sent {signal.sentiment.score > 0 ? '+' : ''}{signal.sentiment.score?.toFixed(2)}
          </Text>
        )}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: RADIUS.lg, padding: 16, marginBottom: 12 },
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 },
  headerLeft: { flex: 1 },
  signalLabel: { fontSize: 10, color: COLORS.textMuted, letterSpacing: 1, marginBottom: 4 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  ticker: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  marketChip: { backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, paddingHorizontal: 8, paddingVertical: 2 },
  marketText: { fontSize: 10, color: COLORS.textMuted },
  actionBadge: { borderRadius: RADIUS.md, paddingHorizontal: 12, paddingVertical: 4 },
  actionText: { fontSize: 12, fontWeight: '800', color: '#fff', letterSpacing: 0.5 },
  confRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 },
  confLabel: { fontSize: 12, color: COLORS.textMuted },
  confValue: { fontSize: 14, fontWeight: '700' },
  barBg: { height: 6, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, marginBottom: 6, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: RADIUS.full },
  fusedNote: { fontSize: 10, color: COLORS.textMuted, marginBottom: 12 },
  section: { marginBottom: 12 },
  sectionTitle: { fontSize: 10, color: COLORS.textMuted, letterSpacing: 1, marginBottom: 8 },
  modelRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 6, gap: 8 },
  modelLabel: { fontSize: 12, color: COLORS.textSecondary, width: 36 },
  modelBarBg: { flex: 1, height: 4, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, overflow: 'hidden' },
  modelBarFill: { height: '100%', borderRadius: RADIUS.full },
  modelVal: { fontSize: 12, color: COLORS.textSecondary, width: 32, textAlign: 'right' },
  shapRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 },
  shapName: { fontSize: 12, color: COLORS.textSecondary, flex: 1 },
  shapPct: { fontSize: 11, color: COLORS.textMuted },
  footer: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingTop: 10, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.06)' },
  footerLeft: { flexDirection: 'row', alignItems: 'center', flex: 1 },
  meta: { fontSize: 11, color: COLORS.textMuted },
  riskText: { fontSize: 11, fontWeight: '600' },
  stopLoss: { fontSize: 11, color: COLORS.textMuted },
  sentiment: { fontSize: 11, color: COLORS.textMuted },
})
