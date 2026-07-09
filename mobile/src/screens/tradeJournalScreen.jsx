import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, ScrollView, StyleSheet, RefreshControl, ActivityIndicator,
  TouchableOpacity,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'

import client from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

function VoteChip({ label, vote }) {
  const color = vote === 'BUY' ? COLORS.green : vote === 'SELL' ? COLORS.red : COLORS.textMuted
  return (
    <View style={[styles.voteChip, { borderColor: color }]}>
      <Text style={[styles.voteChipText, { color }]}>{label} {vote?.[0] || '·'}</Text>
    </View>
  )
}

export default function TradeJournalScreen({ navigation }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [err, setErr] = useState(null)

  const load = useCallback(() => {
    return client.get('/api/paper-trading/trade-log', { params: { limit: 50 } })
      .then(({ data }) => { setRows(data || []); setErr(null) })
      .catch(() => setErr('Could not load trade journal'))
  }, [])

  useEffect(() => { load().finally(() => setLoading(false)) }, [load])

  const onRefresh = () => { setRefreshing(true); load().finally(() => setRefreshing(false)) }

  if (loading) {
    return <View style={styles.center}><ActivityIndicator color={COLORS.teal} size="large" /></View>
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.teal} />}
    >
      <Text style={styles.title}>Trade Journal</Text>
      <Text style={styles.subtitle}>Every trade with the reasoning behind it. Tap to see the full decision.</Text>

      {err && <Text style={styles.err}>{err}</Text>}
      {!err && rows.length === 0 && (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>No trades logged yet.</Text>
          <Text style={styles.emptyHint}>Run a meta rebalance from the Portfolio tab to populate it.</Text>
        </View>
      )}

      {rows.map((r) => (
        <TouchableOpacity key={r.id} style={styles.card} activeOpacity={0.7}
          onPress={() => navigation.navigate('TradeDetail', { id: r.id, ticker: r.ticker })}>
          <View style={styles.cardHeader}>
            <View style={[styles.actionBadge,
              { backgroundColor: r.action === 'BUY' ? COLORS.greenBg : COLORS.redBg }]}>
              <Text style={[styles.actionText,
                { color: r.action === 'BUY' ? COLORS.green : COLORS.red }]}>{r.action}</Text>
            </View>
            <Text style={styles.ticker}>{r.ticker}</Text>
            {r.meta_prob != null && (
              <Text style={styles.meta}>meta {(r.meta_prob).toFixed(2)}</Text>
            )}
            <View style={{ flex: 1 }} />
            <Ionicons name="chevron-forward" size={16} color={COLORS.textMuted} />
          </View>

          {(r.regime || r.vol_regime) && (
            <Text style={styles.regime}>{r.regime || '?'} · {r.vol_regime || '?'} vol</Text>
          )}
          {r.reason && <Text style={styles.reason} numberOfLines={2}>{r.reason}</Text>}

          {r.model_signals && (
            <View style={styles.votes}>
              {Object.entries(r.model_signals).slice(0, 4).map(([k, v]) => (
                <VoteChip key={k} label={k} vote={v > 0.55 ? 'BUY' : v < 0.45 ? 'SELL' : 'HOLD'} />
              ))}
            </View>
          )}
        </TouchableOpacity>
      ))}
    </ScrollView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  content: { padding: 16, paddingBottom: 40 },
  center: { flex: 1, backgroundColor: COLORS.bg, alignItems: 'center', justifyContent: 'center' },
  title: { color: COLORS.textPrimary, fontSize: 22, fontWeight: '700', marginBottom: 4 },
  subtitle: { color: COLORS.textSecondary, fontSize: 13, marginBottom: 16 },
  err: { color: COLORS.red, fontSize: 13, marginBottom: 12 },
  emptyCard: { backgroundColor: COLORS.card, borderRadius: RADIUS.lg, borderWidth: 1,
    borderColor: COLORS.cardBorder, padding: 20, alignItems: 'center' },
  emptyText: { color: COLORS.textPrimary, fontSize: 14, marginBottom: 4 },
  emptyHint: { color: COLORS.textMuted, fontSize: 12, textAlign: 'center' },
  card: { backgroundColor: COLORS.card, borderRadius: RADIUS.lg, borderWidth: 1,
    borderColor: COLORS.cardBorder, padding: 14, marginBottom: 10 },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  actionBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: RADIUS.sm },
  actionText: { fontSize: 11, fontWeight: '700' },
  ticker: { color: COLORS.textPrimary, fontSize: 15, fontWeight: '600' },
  meta: { color: COLORS.textSecondary, fontSize: 11 },
  regime: { color: COLORS.textMuted, fontSize: 11, marginTop: 6 },
  reason: { color: COLORS.textSecondary, fontSize: 12, marginTop: 4, lineHeight: 17 },
  votes: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 },
  voteChip: { borderWidth: 1, borderRadius: RADIUS.sm, paddingHorizontal: 6, paddingVertical: 2 },
  voteChipText: { fontSize: 10, fontWeight: '600' },
})
