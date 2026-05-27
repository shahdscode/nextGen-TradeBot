import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity,
  RefreshControl, StyleSheet, ActivityIndicator,
} from 'react-native'
import RegimeBanner from '../components/regimeBanner'
import SignalCard from '../components/signalCard'
import client from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

const MARKETS = [
  { value: 'us', label: 'US' },
  { value: 'egx', label: 'EGX' },
  { value: 'all', label: 'All' },
]

const ACTIONS = [
  { value: '', label: 'All' },
  { value: 'BUY', label: 'Buy' },
  { value: 'SELL', label: 'Sell' },
  { value: 'HOLD', label: 'Hold' },
]

export default function SignalsScreen() {
  const [signals, setSignals] = useState([])
  const [regime, setRegime] = useState(null)
  const [market, setMarket] = useState('us')
  const [actionFilter, setActionFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const [sigR, regR] = await Promise.allSettled([
        client.get('/api/signals/top', { params: { market, limit: 50, ...(actionFilter ? { action: actionFilter } : {}) } }),
        client.get('/api/market/regime', { params: { market } }),
      ])
      if (sigR.status === 'fulfilled') setSignals(sigR.value.data)
      if (regR.status === 'fulfilled') setRegime(regR.value.data)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [market, actionFilter])

  useEffect(() => { setLoading(true); fetchData() }, [fetchData])

  const onRefresh = () => { setRefreshing(true); fetchData() }

  return (
    <View style={styles.root}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>Signals</Text>
        <Text style={styles.count}>{signals.length} active</Text>
      </View>

      {/* Filters */}
      <View style={styles.filtersContainer}>
        <View style={styles.filterRow}>
          {MARKETS.map((m) => (
            <TouchableOpacity key={m.value} onPress={() => setMarket(m.value)} style={[styles.chip, market === m.value && styles.chipActive]}>
              <Text style={[styles.chipText, market === m.value && styles.chipTextActive]}>{m.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={styles.filterRow}>
          {ACTIONS.map((a) => (
            <TouchableOpacity key={a.value} onPress={() => setActionFilter(a.value)} style={[styles.chip, actionFilter === a.value && styles.chipActive]}>
              <Text style={[styles.chipText, actionFilter === a.value && styles.chipTextActive]}>{a.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {loading ? (
        <ActivityIndicator color={COLORS.teal} style={{ marginTop: 60 }} />
      ) : (
        <FlatList
          data={signals}
          keyExtractor={(s) => s.id}
          renderItem={({ item }) => <SignalCard signal={item} />}
          contentContainerStyle={styles.listContent}
          ListHeaderComponent={
            <RegimeBanner regime={regime?.current_regime} weights={regime?.weights} source={regime?.source} />
          }
          ListEmptyComponent={
            <View style={styles.emptyBox}>
              <Text style={styles.emptyText}>No signals available yet</Text>
              <Text style={styles.emptyHint}>Admin needs to generate signals first</Text>
            </View>
          }
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.teal} />}
          showsVerticalScrollIndicator={false}
        />
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.cardBorder,
  },
  title: { fontSize: 20, fontWeight: '800', color: COLORS.textPrimary },
  count: { fontSize: 13, color: COLORS.textMuted },
  filtersContainer: { paddingHorizontal: 20, paddingVertical: 12, gap: 8 },
  filterRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: RADIUS.full,
    backgroundColor: COLORS.card,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
  },
  chipActive: { backgroundColor: COLORS.teal, borderColor: COLORS.teal },
  chipText: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '500' },
  chipTextActive: { color: '#fff', fontWeight: '700' },
  listContent: { paddingHorizontal: 20, paddingBottom: 40, paddingTop: 8 },
  emptyBox: { backgroundColor: COLORS.card, borderRadius: RADIUS.lg, padding: 32, alignItems: 'center' },
  emptyText: { color: COLORS.textSecondary, fontSize: 15, fontWeight: '600' },
  emptyHint: { color: COLORS.textMuted, fontSize: 12, marginTop: 6 },
})
