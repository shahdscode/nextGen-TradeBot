import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, ScrollView, StyleSheet, RefreshControl, ActivityIndicator,
  TouchableOpacity, Modal, Pressable, Alert,
} from 'react-native'
import Svg, { Polyline } from 'react-native-svg'
import { Ionicons } from '@expo/vector-icons'

import client from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

function Sparkline({ data, width = 320, height = 90 }) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const span = max - min || 1
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width
    const y = height - ((v - min) / span) * height
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const up = data[data.length - 1] >= data[0]
  return (
    <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      <Polyline points={pts} fill="none"
        stroke={up ? COLORS.green : COLORS.red} strokeWidth="2" />
    </Svg>
  )
}

export default function PortfolioScreen({ navigation }) {
  const [pf, setPf] = useState(null)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [err, setErr] = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)
  const [runs, setRuns] = useState([])
  const [picker, setPicker] = useState(false)
  const [rebalancing, setRebalancing] = useState(false)

  const load = useCallback(() => {
    return Promise.all([
      client.get('/api/paper-trading/alpaca/portfolio').catch(e => { throw e }),
      client.get('/api/paper-trading/alpaca/status').catch(() => null),
      client.get('/api/train/runs/published').catch(() => null),
    ]).then(([p, s, r]) => {
      setPf(p.data); setStatus(s?.data); setErr(null)
      const rl = (r?.data || []).filter(x => ['ppo','a2c','ddpg','td3','sac'].includes(x.algorithm))
      setRuns(rl)
      setUpdatedAt(new Date())
    }).catch(e => setErr(e.response?.data?.detail || 'Could not load Alpaca portfolio'))
  }, [])

  useEffect(() => { load().finally(() => setLoading(false)) }, [load])
  const onRefresh = () => { setRefreshing(true); load().finally(() => setRefreshing(false)) }

  // Run a model on live data and rebalance the Alpaca account
  const rebalance = async ({ mode, run_id }) => {
    setPicker(false)
    setRebalancing(true)
    try {
      const params = mode === 'meta' ? { mode: 'meta' } : { mode: 'rl', run_id }
      const { data } = await client.post('/api/paper-trading/alpaca/rebalance', null, {
        params, timeout: 300000,
      })
      Alert.alert('Rebalanced', `${data.model_message || 'Done'}\n${data.n_orders} orders submitted.`)
      await load()
    } catch (e) {
      Alert.alert('Rebalance failed', e.response?.data?.detail || 'Could not rebalance')
    } finally {
      setRebalancing(false)
    }
  }

  const confirmRebalance = (opt) => Alert.alert(
    'Run model & rebalance?',
    'This places real orders on your Alpaca paper account to match the model\'s target allocation.',
    [{ text: 'Cancel', style: 'cancel' }, { text: 'Rebalance', onPress: () => rebalance(opt) }],
  )

  const fmt = (v, d = 2) => Number(v ?? 0).toLocaleString(undefined,
    { minimumFractionDigits: d, maximumFractionDigits: d })
  const pct = (v) => `${(v ?? 0) >= 0 ? '+' : ''}${((v ?? 0) * 100).toFixed(2)}%`
  const tot = pf?.total_return ?? 0
  const totColor = tot >= 0 ? COLORS.green : COLORS.red

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Portfolio</Text>
          <Text style={styles.sub}>Alpaca paper account · live · auto-rebalanced weekly</Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          {status?.market_open != null && (
            <View style={[styles.pill, { backgroundColor: status.market_open ? COLORS.greenBg : COLORS.amberBg }]}>
              <Text style={[styles.pillText, { color: status.market_open ? COLORS.green : COLORS.amber }]}>
                {status.market_open ? 'MARKET OPEN' : 'MARKET CLOSED'}
              </Text>
            </View>
          )}
          <TouchableOpacity onPress={() => navigation?.navigate('TradeJournal')}
            hitSlop={8} accessibilityLabel="Trade journal">
            <Ionicons name="reader-outline" size={22} color={COLORS.teal} />
          </TouchableOpacity>
        </View>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={COLORS.teal} size="large" /></View>
      ) : err ? (
        <View style={styles.center}>
          <Text style={styles.errText}>{err}</Text>
          <Text style={styles.hint}>Configure Alpaca keys in .env, then pull to refresh.</Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.teal} />}
        >
          {/* Equity + total return hero */}
          <View style={styles.hero}>
            <Text style={styles.heroLabel}>Portfolio Value</Text>
            <Text style={styles.heroValue}>${fmt(pf?.portfolio_value)}</Text>
            <Text style={[styles.heroReturn, { color: totColor }]}>
              {pct(tot)}  ({tot >= 0 ? '+' : ''}${fmt(pf?.total_pl)})  since start
            </Text>
            {pf?.equity_curve?.length > 1 && (
              <View style={{ marginTop: 14 }}>
                <Sparkline data={pf.equity_curve} />
              </View>
            )}
          </View>

          {/* Stat tiles */}
          <View style={styles.tiles}>
            {[
              ['Cash', `$${fmt(pf?.cash, 0)}`, COLORS.textPrimary],
              ['Buying Power', `$${fmt(status?.buying_power ?? pf?.buying_power, 0)}`, COLORS.textPrimary],
              ['Drawdown', `${((pf?.drawdown ?? 0) * 100).toFixed(1)}%`,
                pf?.drawdown_breached ? COLORS.red : COLORS.textSecondary],
              ['Positions', `${pf?.positions?.length ?? 0}`, COLORS.textPrimary],
            ].map(([l, v, c]) => (
              <View key={l} style={styles.tile}>
                <Text style={styles.tileLabel}>{l}</Text>
                <Text style={[styles.tileValue, { color: c }]}>{v}</Text>
              </View>
            ))}
          </View>

          {pf?.drawdown_breached && (
            <View style={styles.riskBanner}>
              <Text style={styles.riskText}>⚠ Drawdown limit breached — risk kill-switch active</Text>
            </View>
          )}

          {/* Run model / rebalance */}
          {pf?.configured !== false && (
            <TouchableOpacity
              style={[styles.rebalanceBtn, rebalancing && { opacity: 0.6 }]}
              onPress={() => setPicker(true)}
              disabled={rebalancing}
            >
              {rebalancing ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.rebalanceText}>Run Model · Rebalance</Text>
              )}
            </TouchableOpacity>
          )}
          <Text style={styles.rebalanceHint}>
            Runs the model on live data and places orders on your Alpaca account.
          </Text>

          {/* Positions */}
          <Text style={styles.sectionTitle}>Holdings</Text>
          {(!pf?.positions || pf.positions.length === 0) ? (
            <Text style={styles.hint}>No open positions. Rebalance from the web app or Alpaca card.</Text>
          ) : (
            pf.positions.map(p => (
              <View key={p.symbol} style={styles.posRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.posSym}>{p.symbol}</Text>
                  <Text style={styles.posQty}>{fmt(p.qty, 2)} sh @ ${fmt(p.current_price)}</Text>
                </View>
                <View style={{ alignItems: 'flex-end' }}>
                  <Text style={styles.posVal}>${fmt(p.market_value, 0)}</Text>
                  <Text style={[styles.posPl, { color: p.unrealized_pl >= 0 ? COLORS.green : COLORS.red }]}>
                    {p.unrealized_pl >= 0 ? '+' : ''}${fmt(p.unrealized_pl)} ({pct(p.unrealized_plpc)})
                  </Text>
                </View>
              </View>
            ))
          )}
          <Text style={styles.footer}>{pf?.message}</Text>
          {updatedAt && (
            <Text style={styles.footer}>Updated {updatedAt.toLocaleTimeString()} · pull to refresh</Text>
          )}
        </ScrollView>
      )}

      {/* Model picker modal */}
      <Modal visible={picker} transparent animationType="fade" onRequestClose={() => setPicker(false)}>
        <Pressable style={styles.modalBg} onPress={() => setPicker(false)}>
          <Pressable style={styles.modalCard} onPress={() => {}}>
            <Text style={styles.modalTitle}>Choose a model</Text>
            <TouchableOpacity style={styles.modalOpt} onPress={() => confirmRebalance({ mode: 'meta' })}>
              <Text style={styles.modalOptTitle}>Meta-Learner ensemble</Text>
              <Text style={styles.modalOptSub}>All 7 models combined (slower, ~3–5 min)</Text>
            </TouchableOpacity>
            {runs.slice(0, 6).map((r) => {
              const ck = r.data_job_id?.match(/ckpt(\d)/)?.[1]
              const sh = r.metrics?.sharpe_ratio
              return (
                <TouchableOpacity key={r.run_id} style={styles.modalOpt}
                  onPress={() => confirmRebalance({ mode: 'rl', run_id: r.run_id })}>
                  <Text style={styles.modalOptTitle}>
                    {r.algorithm?.toUpperCase()}{ck ? ` · ckpt${ck}` : ''}
                  </Text>
                  <Text style={styles.modalOptSub}>
                    {sh != null ? `Sharpe ${sh.toFixed(2)} · ` : ''}{r.run_id.slice(0, 8)}
                  </Text>
                </TouchableOpacity>
              )
            })}
            {runs.length === 0 && (
              <Text style={styles.hint}>No published RL models — use Meta-Learner or publish a run.</Text>
            )}
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  )
}

const styles = StyleSheet.create({
  rebalanceBtn: {
    backgroundColor: COLORS.teal, borderRadius: RADIUS.md, paddingVertical: 14,
    alignItems: 'center', marginTop: 4, marginBottom: 6,
  },
  rebalanceText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  rebalanceHint: { color: COLORS.textMuted, fontSize: 11, textAlign: 'center', marginBottom: 18 },
  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: COLORS.card, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 20, paddingBottom: 36,
  },
  modalTitle: { color: COLORS.textPrimary, fontSize: 16, fontWeight: '700', marginBottom: 14 },
  modalOpt: {
    backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md, padding: 14, marginBottom: 10,
  },
  modalOptTitle: { color: COLORS.textPrimary, fontSize: 14, fontWeight: '600' },
  modalOptSub: { color: COLORS.textMuted, fontSize: 12, marginTop: 2 },
  root: { flex: 1, backgroundColor: COLORS.bg },
  header: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start',
    paddingHorizontal: 20, paddingTop: 56, paddingBottom: 16,
    borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder,
  },
  title: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  sub: { fontSize: 13, color: COLORS.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: RADIUS.full },
  pillText: { fontSize: 10, fontWeight: '700' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  errText: { color: COLORS.red, fontSize: 14, textAlign: 'center' },
  hint: { color: COLORS.textMuted, fontSize: 12, textAlign: 'center', marginTop: 8 },
  content: { padding: 20, paddingBottom: 40 },
  hero: {
    backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.lg, padding: 20, marginBottom: 16,
  },
  heroLabel: { fontSize: 12, color: COLORS.textMuted, textTransform: 'uppercase', letterSpacing: 0.5 },
  heroValue: { fontSize: 34, fontWeight: '800', color: COLORS.textPrimary, marginTop: 4 },
  heroReturn: { fontSize: 14, fontWeight: '600', marginTop: 4 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 16 },
  tile: {
    flexGrow: 1, flexBasis: '47%', backgroundColor: COLORS.card,
    borderWidth: 1, borderColor: COLORS.cardBorder, borderRadius: RADIUS.md, padding: 14,
  },
  tileLabel: { fontSize: 11, color: COLORS.textMuted },
  tileValue: { fontSize: 18, fontWeight: '700', marginTop: 4 },
  riskBanner: {
    backgroundColor: COLORS.redBg, borderRadius: RADIUS.md, padding: 12, marginBottom: 16,
  },
  riskText: { color: COLORS.red, fontSize: 13, fontWeight: '600' },
  sectionTitle: {
    fontSize: 14, fontWeight: '700', color: COLORS.textPrimary,
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10,
  },
  posRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.card,
    borderWidth: 1, borderColor: COLORS.cardBorder, borderRadius: RADIUS.md,
    padding: 14, marginBottom: 8,
  },
  posSym: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },
  posQty: { fontSize: 12, color: COLORS.textMuted, marginTop: 2 },
  posVal: { fontSize: 14, fontWeight: '600', color: COLORS.textPrimary },
  posPl: { fontSize: 12, fontWeight: '600', marginTop: 2 },
  footer: { fontSize: 11, color: COLORS.textMuted, marginTop: 16, textAlign: 'center' },
})
