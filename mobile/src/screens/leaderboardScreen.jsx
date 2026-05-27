import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity,
  RefreshControl, StyleSheet, ActivityIndicator,
} from 'react-native'
import client from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

const actionColor = { BUY: COLORS.green, SELL: COLORS.red, HOLD: COLORS.amber }
const riskColor = { LOW: COLORS.green, MEDIUM: COLORS.amber, HIGH: COLORS.red }
const MEDAL = ['🥇', '🥈', '🥉']

export default function LeaderboardScreen() {
  const [rows, setRows] = useState([])
  const [market, setMarket] = useState('us')
  const [hours, setHours] = useState(168)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const { data } = await client.get('/api/signals/leaderboard', { params: { market, hours } })
      setRows(data)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [market, hours])

  useEffect(() => { setLoading(true); fetchData() }, [fetchData])

  const onRefresh = () => { setRefreshing(true); fetchData() }

  const renderItem = ({ item, index }) => {
    const confPct = Math.round(item.latest_confidence * 100)
    return (
      <View style={styles.row}>
        <Text style={styles.rank}>{index < 3 ? MEDAL[index] : `${index + 1}`}</Text>
        <View style={styles.rowMain}>
          <View style={styles.rowTop}>
            <Text style={styles.ticker}>{item.ticker}</Text>
            <View style={[styles.actionBadge, { backgroundColor: (actionColor[item.latest_action] || COLORS.textMuted) + '20' }]}>
              <Text style={[styles.actionText, { color: actionColor[item.latest_action] || COLORS.textMuted }]}>
                {item.latest_action}
              </Text>
            </View>
          </View>
          <View style={styles.rowBottom}>
            <View style={styles.barBg}>
              <View style={[styles.barFill, { width: `${confPct}%`, backgroundColor: actionColor[item.latest_action] || COLORS.textMuted }]} />
            </View>
            <Text style={styles.confText}>{confPct}%</Text>
          </View>
          <View style={styles.rowMeta}>
            {item.regime && <Text style={styles.meta}>{item.regime}</Text>}
            {item.risk_level && (
              <Text style={[styles.meta, { color: riskColor[item.risk_level] || COLORS.textMuted }]}>{item.risk_level}</Text>
            )}
            <Text style={styles.meta}>{item.signal_count} signals</Text>
          </View>
        </View>
      </View>
    )
  }

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.title}>Leaderboard</Text>
      </View>

      {/* Controls */}
      <View style={styles.controls}>
        <View style={styles.tabs}>
          {['us', 'egx'].map((m) => (
            <TouchableOpacity key={m} onPress={() => setMarket(m)} style={[styles.tab, market === m && styles.tabActive]}>
              <Text style={[styles.tabText, market === m && styles.tabTextActive]}>{m === 'us' ? 'US' : 'EGX'}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={styles.tabs}>
          {[{ v: 24, l: '24h' }, { v: 168, l: '7d' }, { v: 720, l: '30d' }].map(({ v, l }) => (
            <TouchableOpacity key={v} onPress={() => setHours(v)} style={[styles.tab, hours === v && styles.tabActive]}>
              <Text style={[styles.tabText, hours === v && styles.tabTextActive]}>{l}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {loading ? (
        <ActivityIndicator color={COLORS.teal} style={{ marginTop: 60 }} />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(r) => r.ticker}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
          ListEmptyComponent={
            <View style={styles.emptyBox}>
              <Text style={styles.emptyText}>No signal data yet</Text>
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
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.cardBorder,
  },
  title: { fontSize: 20, fontWeight: '800', color: COLORS.textPrimary },
  controls: { paddingHorizontal: 20, paddingVertical: 12, gap: 8 },
  tabs: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  tab: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: RADIUS.full, backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.cardBorder },
  tabActive: { backgroundColor: COLORS.teal, borderColor: COLORS.teal },
  tabText: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '500' },
  tabTextActive: { color: '#fff', fontWeight: '700' },
  list: { paddingHorizontal: 20, paddingBottom: 40 },
  row: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.04)', gap: 14 },
  rank: { fontSize: 16, width: 28, textAlign: 'center', marginTop: 2 },
  rowMain: { flex: 1 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  ticker: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },
  actionBadge: { borderRadius: RADIUS.full, paddingHorizontal: 10, paddingVertical: 3 },
  actionText: { fontSize: 11, fontWeight: '700' },
  rowBottom: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 6 },
  barBg: { flex: 1, height: 5, backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: RADIUS.full, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: RADIUS.full },
  confText: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary, width: 36, textAlign: 'right' },
  rowMeta: { flexDirection: 'row', gap: 12 },
  meta: { fontSize: 11, color: COLORS.textMuted },
  emptyBox: { paddingTop: 60, alignItems: 'center' },
  emptyText: { color: COLORS.textMuted, fontSize: 15 },
})
