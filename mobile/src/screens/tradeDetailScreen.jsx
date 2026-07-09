import { useState, useEffect } from 'react'
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator,
} from 'react-native'

import client from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

function Row({ label, value }) {
  if (value == null || value === '') return null
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  )
}

function Section({ title, children }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  )
}

export default function TradeDetailScreen({ route }) {
  const { id } = route.params || {}
  const [d, setD] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    client.get(`/api/paper-trading/trade-log/${id}`)
      .then(({ data }) => setD(data))
      .catch(() => setErr('Could not load this decision'))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return <View style={styles.center}><ActivityIndicator color={COLORS.teal} size="large" /></View>
  }
  if (err || !d) {
    return <View style={styles.center}><Text style={styles.err}>{err || 'Not found'}</Text></View>
  }

  const voteColor = (v) => v === 'BUY' ? COLORS.green : v === 'SELL' ? COLORS.red : COLORS.textMuted
  const ag = d.model_agreement || {}

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <View style={styles.headerRow}>
        <View style={[styles.actionBadge,
          { backgroundColor: d.action === 'BUY' ? COLORS.greenBg : COLORS.redBg }]}>
          <Text style={[styles.actionText,
            { color: d.action === 'BUY' ? COLORS.green : COLORS.red }]}>{d.action}</Text>
        </View>
        <Text style={styles.ticker}>{d.ticker}</Text>
        {d.meta_probability_pct != null && (
          <Text style={styles.metaBig}>{d.meta_probability_pct}%</Text>
        )}
      </View>
      {d.final_explanation && <Text style={styles.explanation}>{d.final_explanation}</Text>}

      <Section title={`Model Votes  ·  ${ag.agreement_pct ?? 0}% agree`}>
        {(d.model_votes || []).map((m) => (
          <View key={m.key} style={styles.row}>
            <Text style={styles.rowLabel}>{m.model}</Text>
            <Text style={[styles.rowValue, { color: voteColor(m.vote), fontWeight: '700' }]}>
              {m.vote}  ({m.signal})
            </Text>
          </View>
        ))}
      </Section>

      <Section title="Market Context">
        <Row label="Regime" value={d.regime?.market} />
        <Row label="Volatility" value={d.regime?.volatility} />
        {(d.technicals || []).map((t) => (
          <Row key={t.key} label={t.label} value={t.value} />
        ))}
      </Section>

      {Array.isArray(d.fundamentals) && d.fundamentals.length > 0 && (
        <Section title="Fundamentals">
          {d.fundamentals.map((f, i) => (
            <Row key={i} label={f.label || f.key} value={f.value} />
          ))}
        </Section>
      )}

      <Section title="Risk & Sizing">
        <Row label="Position size" value={d.risk?.position_size_pct != null ? `${d.risk.position_size_pct}%` : null} />
        <Row label="Stop" value={d.risk?.stop_price != null ? `$${d.risk.stop_price}` : null} />
        <Row label="Target" value={d.risk?.take_profit != null ? `$${d.risk.take_profit}` : null} />
        <Row label="Risk capital" value={d.risk?.risk_dollars != null ? `$${d.risk.risk_dollars}` : null} />
        <Row label="Method" value={d.risk?.sizing_method} />
      </Section>

      <Section title="Execution">
        <Row label="Shares" value={d.execution?.shares} />
        <Row label="Price" value={d.execution?.price != null ? `$${d.execution.price}` : null} />
        <Row label="Notional" value={d.execution?.notional != null ? `$${d.execution.notional}` : null} />
        <Row label="Venue" value={d.venue} />
      </Section>

      <Text style={styles.footer}>Descriptive record — explains the trade after execution.</Text>
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: 16, paddingBottom: 40 },
  center: { flex: 1, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  err: { color: COLORS.red, fontSize: 14 },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 8 },
  actionBadge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: RADIUS.sm },
  actionText: { fontSize: 13, fontWeight: '700' },
  ticker: { color: COLORS.textPrimary, fontSize: 20, fontWeight: '700' },
  metaBig: { color: COLORS.teal, fontSize: 20, fontWeight: '700', marginLeft: 'auto' },
  explanation: { color: COLORS.textSecondary, fontSize: 13, lineHeight: 19, marginBottom: 16 },
  section: { backgroundColor: COLORS.card, borderRadius: RADIUS.lg, borderWidth: 1,
    borderColor: COLORS.cardBorder, padding: 14, marginBottom: 12 },
  sectionTitle: { color: COLORS.textPrimary, fontSize: 13, fontWeight: '700', marginBottom: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  rowLabel: { color: COLORS.textMuted, fontSize: 12 },
  rowValue: { color: COLORS.textPrimary, fontSize: 12, fontWeight: '600' },
  footer: { color: COLORS.textMuted, fontSize: 11, textAlign: 'center', marginTop: 4 },
})
