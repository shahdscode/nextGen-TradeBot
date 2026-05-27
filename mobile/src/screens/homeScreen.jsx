import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity,
  RefreshControl, StyleSheet, ActivityIndicator,
} from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { useAuth } from '../context/authContext'
import RegimeBanner from '../components/regimeBanner'
import SignalCard from '../components/signalCard'
import client from '../api/client'
import DataSourceBadge from '../components/dataSourceBadge'
import { COLORS, RADIUS } from '../constants/theme'

const changeColor = (pct) => (pct > 0 ? COLORS.green : pct < 0 ? COLORS.red : COLORS.textMuted)

/** Home briefing: show any priced row except explicit unavailable (matches original mobile home). */
function moversForHome(items) {
  return (items || [])
    .filter((item) => item?.ticker != null && item.price != null && item.source !== 'unavailable')
    .slice(0, 5)
}

export default function HomeScreen({ navigation }) {
  const { user, logout } = useAuth()
  const [regime, setRegime] = useState(null)
  const [topSignals, setTopSignals] = useState([])
  const [movers, setMovers] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchAll = useCallback(async () => {
    try {
      const [regR, sigR, mktR] = await Promise.allSettled([
        client.get('/api/market/regime'),
        client.get('/api/signals/top', { params: { limit: 3, market: 'us' } }),
        client.get('/api/market/overview', { params: { market: 'us' } }),
      ])
      if (regR.status === 'fulfilled') setRegime(regR.value.data)
      if (sigR.status === 'fulfilled') setTopSignals(sigR.value.data || [])
      if (mktR.status === 'fulfilled') setMovers(moversForHome(mktR.value.data))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const onRefresh = () => { setRefreshing(true); fetchAll() }

  const moverSource = movers[0]?.source || 'live'

  return (
    <View style={styles.root}>
      <StatusBar style="light" />

      <View style={styles.header}>
        <View>
          <Text style={styles.greeting}>Hello, {user?.username} 👋</Text>
          <Text style={styles.subGreeting}>Here's your market briefing</Text>
        </View>
        <TouchableOpacity onPress={logout} style={styles.logoutBtn}>
          <Text style={styles.logoutText}>Sign out</Text>
        </TouchableOpacity>
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.teal} />}
        showsVerticalScrollIndicator={false}
      >
        {loading ? (
          <ActivityIndicator color={COLORS.teal} style={{ marginTop: 40 }} />
        ) : (
          <>
            <RegimeBanner
              regime={regime?.current_regime || 'SIDEWAYS'}
              weights={regime?.weights}
              source={regime?.source}
            />

            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <View style={styles.sectionTitleRow}>
                  <Text style={styles.sectionTitle}>Top Movers</Text>
                  {movers.length > 0 && <DataSourceBadge source={moverSource} />}
                </View>
                <TouchableOpacity onPress={() => navigation.navigate('Market')}>
                  <Text style={styles.seeAll}>See all →</Text>
                </TouchableOpacity>
              </View>
              {movers.length > 0 ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                  <View style={styles.moversRow}>
                    {movers.map((m) => (
                      <View key={m.ticker} style={styles.moverCard}>
                        <Text style={styles.moverTicker}>{m.ticker}</Text>
                        <Text style={styles.moverPrice}>${m.price?.toLocaleString()}</Text>
                        <Text style={[styles.moverChange, { color: changeColor(m.change_pct) }]}>
                          {m.change_pct > 0 ? '+' : ''}{m.change_pct}%
                        </Text>
                      </View>
                    ))}
                  </View>
                </ScrollView>
              ) : (
                <View style={styles.emptyBox}>
                  <Text style={styles.emptyText}>Market data loading…</Text>
                  <Text style={styles.emptyHint}>Pull to refresh or open Market tab</Text>
                </View>
              )}
            </View>

            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Today's Top Signals</Text>
                <TouchableOpacity onPress={() => navigation.navigate('Signals')}>
                  <Text style={styles.seeAll}>See all →</Text>
                </TouchableOpacity>
              </View>
              {topSignals.length === 0 ? (
                <View style={styles.emptyBox}>
                  <Text style={styles.emptyText}>No signals generated yet</Text>
                  <Text style={styles.emptyHint}>An admin needs to generate signals first</Text>
                </View>
              ) : (
                topSignals.map((s) => (
                  <SignalCard key={s.id} signal={s} compact={false} />
                ))
              )}
            </View>
          </>
        )}
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.cardBorder,
  },
  greeting: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  subGreeting: { fontSize: 13, color: COLORS.textMuted, marginTop: 2 },
  logoutBtn: { paddingHorizontal: 12, paddingVertical: 6, borderWidth: 1, borderColor: COLORS.cardBorder, borderRadius: RADIUS.md },
  logoutText: { fontSize: 12, color: COLORS.textMuted },
  scroll: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 40 },
  section: { marginBottom: 24 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  sectionTitle: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary, textTransform: 'uppercase', letterSpacing: 0.5 },
  seeAll: { fontSize: 12, color: COLORS.teal },
  moversRow: { flexDirection: 'row', gap: 10 },
  moverCard: {
    backgroundColor: COLORS.card,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md,
    padding: 14,
    minWidth: 90,
    alignItems: 'center',
  },
  moverTicker: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 4 },
  moverPrice: { fontSize: 12, color: COLORS.textSecondary, marginBottom: 4 },
  moverChange: { fontSize: 13, fontWeight: '600' },
  emptyBox: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    padding: 24,
    alignItems: 'center',
  },
  emptyText: { color: COLORS.textSecondary, fontSize: 14, fontWeight: '500' },
  emptyHint: { color: COLORS.textMuted, fontSize: 12, marginTop: 4, textAlign: 'center' },
})
