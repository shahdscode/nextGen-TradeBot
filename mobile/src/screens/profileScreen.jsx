import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView,
  ActivityIndicator, Alert, RefreshControl, Modal, Pressable,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'
import Constants from 'expo-constants'

import client from '../api/client'
import { useAuth } from '../context/authContext'
import ProfileSparkline from '../components/profileSparkline'
import { COLORS, RADIUS } from '../constants/theme'

const ACCENT = COLORS.purple
const MAX_DRAWDOWN_PCT = 15
const CASH_RESERVE_PCT = 2
const MAX_POSITION_PCT = 10
const MODEL_LABELS = { xgboost: 'XGBoost', lstm: 'LSTM', ppo: 'PPO', sac: 'SAC', meta_learner: 'Meta-Learner' }

function fmtMoney(v) {
  return `$${Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function fmtPct(v, digits = 2) {
  const n = (v ?? 0) * 100
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function displayName(username) {
  if (!username) return 'Trader'
  return username
    .replace(/[_.-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function memberSince(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
}

function monthReturnFromEquity(equity) {
  if (!equity || equity.length < 2) return null
  const lookback = Math.min(21, equity.length - 1)
  const start = equity[equity.length - 1 - lookback]
  const end = equity[equity.length - 1]
  return start > 0 ? end / start - 1 : null
}

function monthlyReturnBands(equity) {
  if (!equity || equity.length < 14) return null
  const step = Math.max(5, Math.floor(equity.length / 6))
  const rets = []
  for (let i = step; i < equity.length; i += step) {
    const prev = equity[i - step]
    const cur = equity[i]
    if (prev > 0) rets.push(cur / prev - 1)
  }
  if (!rets.length) return null
  return { best: Math.max(...rets), worst: Math.min(...rets) }
}

function nextRebalanceLabel() {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const now = new Date()
  const target = 0
  let diff = (target - now.getDay() + 7) % 7
  if (diff === 0) diff = 7
  const next = new Date(now)
  next.setDate(now.getDate() + diff)
  return `${days[next.getDay()]}, 9 PM`
}

function Card({ children, style }) {
  return <View style={[styles.card, style]}>{children}</View>
}

function SectionHeader({ icon, title, actionLabel, onAction }) {
  return (
    <View style={styles.sectionHead}>
      <View style={styles.sectionTitleRow}>
        <Ionicons name={icon} size={18} color={ACCENT} />
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      {actionLabel ? (
        <TouchableOpacity onPress={onAction} disabled={!onAction}>
          <Text style={styles.sectionAction}>{actionLabel}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  )
}

function RiskTile({ icon, value, label, sub }) {
  return (
    <View style={styles.riskTile}>
      <Ionicons name={icon} size={20} color={ACCENT} style={{ marginBottom: 6 }} />
      <Text style={styles.riskValue}>{value}</Text>
      <Text style={styles.riskLabel}>{label}</Text>
      {sub ? <Text style={styles.riskSub}>{sub}</Text> : null}
    </View>
  )
}

function SettingsRow({ icon, title, subtitle, onPress, danger }) {
  return (
    <TouchableOpacity style={styles.settingsRow} onPress={onPress} activeOpacity={0.7}>
      <View style={[styles.settingsIcon, danger && styles.settingsIconDanger]}>
        <Ionicons name={icon} size={20} color={danger ? COLORS.red : ACCENT} />
      </View>
      <View style={styles.settingsText}>
        <Text style={[styles.settingsTitle, danger && { color: COLORS.red }]}>{title}</Text>
        {subtitle ? <Text style={styles.settingsSub}>{subtitle}</Text> : null}
      </View>
      {!danger && <Ionicons name="chevron-forward" size={18} color={COLORS.textMuted} />}
    </TouchableOpacity>
  )
}

export default function ProfileScreen() {
  const { user, logout } = useAuth()
  const [profile, setProfile] = useState(null)
  const [cfg, setCfg] = useState(null)
  const [portfolio, setPortfolio] = useState(null)
  const [publishedRuns, setPublishedRuns] = useState([])
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [brokerModal, setBrokerModal] = useState(false)
  const [lastSync, setLastSync] = useState(null)

  const loadAll = useCallback(async () => {
    const [meR, cfgR, runsR, pfR] = await Promise.allSettled([
      client.get('/api/auth/me'),
      client.get('/api/auth/alpaca-config'),
      client.get('/api/train/runs/published'),
      client.get('/api/paper-trading/alpaca/portfolio'),
    ])
    if (meR.status === 'fulfilled') setProfile(meR.value.data)
    if (cfgR.status === 'fulfilled') setCfg(cfgR.value.data)
    if (runsR.status === 'fulfilled') setPublishedRuns(runsR.value.data || [])
    if (pfR.status === 'fulfilled') {
      setPortfolio(pfR.value.data)
      setLastSync(new Date())
    } else setPortfolio(null)
  }, [])

  useEffect(() => {
    loadAll().finally(() => setLoading(false))
  }, [loadAll])

  const onRefresh = () => {
    setRefreshing(true)
    loadAll().finally(() => setRefreshing(false))
  }

  const saveAlpaca = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      Alert.alert('Missing keys', 'Enter both your Alpaca API key and secret.')
      return
    }
    setSaving(true)
    try {
      await client.put('/api/auth/alpaca-config', {
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
      })
      setApiKey('')
      setApiSecret('')
      setBrokerModal(false)
      await loadAll()
      Alert.alert('Connected', 'Alpaca paper trading is linked.')
    } catch (e) {
      Alert.alert('Error', e.response?.data?.detail || 'Could not save keys')
    } finally {
      setSaving(false)
    }
  }

  const clearAlpaca = () => {
    Alert.alert('Disconnect broker?', 'Your Alpaca keys will be removed from this device.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Disconnect',
        style: 'destructive',
        onPress: async () => {
          setSaving(true)
          try {
            await client.delete('/api/auth/alpaca-config')
            setPortfolio(null)
            await loadAll()
          } catch (e) {
            Alert.alert('Error', e.response?.data?.detail || 'Could not disconnect')
          } finally {
            setSaving(false)
          }
        },
      },
    ])
  }

  const comingSoon = (title) => () => Alert.alert(title, 'This screen is coming in a future update.')

  const displayUser = profile || user
  const connected = cfg?.configured
  const syncLabel = lastSync
    ? `Last sync: ${Math.max(1, Math.round((Date.now() - lastSync.getTime()) / 60000))} min ago`
    : null

  const aiMeta = useMemo(() => {
    const runs = publishedRuns || []
    const metaRun = runs.find((r) => (r.algorithm || '').toLowerCase().includes('meta'))
    const primary = metaRun || runs[0]
    const algos = [...new Set(runs.map((r) => (r.algorithm || '').toLowerCase()).filter(Boolean))]
    const chips = algos.slice(0, 5).map((a) => MODEL_LABELS[a] || a.toUpperCase())
    const m = primary?.metrics || {}
    const sharpe = m.sharpe ?? m.Sharpe ?? m.val_sharpe ?? m.meta_learner?.sharpe
    const conf = m.confidence ?? m.auc ?? m.accuracy
    const confPct = conf != null ? (conf <= 1 ? Math.round(conf * 100) : Math.round(conf)) : null
    const updated = primary?.created_at
      ? new Date(primary.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
      : '—'
    return {
      mode: metaRun ? 'Meta-Learner Ensemble' : (primary?.algorithm || 'No published model'),
      chips,
      sharpe,
      confPct,
      updated,
      hasModels: runs.length > 0,
    }
  }, [publishedRuns])

  const perf = useMemo(() => {
    const bands = monthlyReturnBands(portfolio?.equity_curve)
    const runs = publishedRuns || []
    let trades = null
    let winRate = null
    for (const r of runs) {
      const m = r.metrics || {}
      if (trades == null && m.total_trades != null) trades = m.total_trades
      if (winRate == null && m.win_rate != null) winRate = m.win_rate
    }
    return {
      totalReturn: portfolio?.total_return,
      monthReturn: monthReturnFromEquity(portfolio?.equity_curve) ?? portfolio?.daily_return,
      bestMonth: bands?.best,
      worstMonth: bands?.worst,
      trades,
      winRate,
    }
  }, [portfolio, publishedRuns])

  const memberLabel = memberSince(displayUser?.created_at)
  const monthReturnColor = (perf.monthReturn ?? 0) >= 0 ? COLORS.green : COLORS.red
  const totalReturnColor = (perf.totalReturn ?? 0) >= 0 ? COLORS.green : COLORS.red

  return (
    <View style={styles.root}>
      <View style={styles.topBar}>
        <View style={styles.topBarSide} />
        <Text style={styles.topTitle}>Profile</Text>
        <TouchableOpacity style={styles.topBarSide} onPress={comingSoon('Settings')}>
          <Ionicons name="settings-outline" size={22} color={COLORS.textSecondary} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={ACCENT} size="large" />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={ACCENT} />
          }
          showsVerticalScrollIndicator={false}
        >
          {/* Hero user card */}
          <View style={styles.heroCard}>
            <View style={styles.heroGlow} />
            <View style={styles.heroRow}>
              <View style={styles.avatarWrap}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>
                    {(displayUser?.username || '?')[0].toUpperCase()}
                  </Text>
                </View>
                <View style={styles.cameraBadge}>
                  <Ionicons name="camera" size={12} color="#fff" />
                </View>
              </View>
              <View style={styles.heroMeta}>
                <Text style={styles.heroName}>{displayName(displayUser?.username)}</Text>
                <Text style={styles.heroEmail}>{displayUser?.email || 'No email on file'}</Text>
                <View style={styles.accountPill}>
                  <Text style={styles.accountPillText}>Paper Trading Account</Text>
                </View>
                {memberLabel ? (
                  <View style={styles.memberRow}>
                    <Ionicons name="calendar-outline" size={12} color={COLORS.textMuted} />
                    <Text style={styles.memberText}>Member since {memberLabel}</Text>
                  </View>
                ) : null}
              </View>
            </View>
          </View>

          {/* Broker + Account overview */}
          <View style={styles.twoCol}>
            <Card style={styles.halfCard}>
              <View style={styles.brokerHead}>
                <Text style={styles.cardTitle}>Broker Connection</Text>
                <View style={[styles.connectedPill, !connected && styles.disconnectedPill]}>
                  <View style={[styles.statusDot, { backgroundColor: connected ? COLORS.green : COLORS.amber }]} />
                  <Text style={[styles.connectedText, !connected && { color: COLORS.amber }]}>
                    {connected ? 'Connected' : 'Offline'}
                  </Text>
                </View>
              </View>
              <View style={styles.brokerBrand}>
                <View style={styles.alpacaLogo}>
                  <Text style={styles.alpacaEmoji}>🦙</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.brokerName}>Alpaca Markets</Text>
                  <Text style={styles.brokerSub}>Paper · US equities</Text>
                </View>
              </View>
              <Text style={styles.statLabel}>Account ID</Text>
              <Text style={styles.statValue}>{cfg?.key_preview || '—'}</Text>
              <Text style={styles.statLabel}>Buying Power</Text>
              <Text style={styles.statValue}>
                {connected && portfolio ? fmtMoney(portfolio.buying_power) : '—'}
              </Text>
              {connected && syncLabel ? (
                <Text style={styles.syncText}>{syncLabel}</Text>
              ) : null}
              <View style={styles.brokerActions}>
                <TouchableOpacity
                  style={styles.purpleBtn}
                  onPress={() => setBrokerModal(true)}
                  disabled={saving}
                >
                  <Text style={styles.purpleBtnText}>{connected ? 'Reconnect' : 'Connect'}</Text>
                </TouchableOpacity>
                {connected && (
                  <TouchableOpacity style={styles.outlineBtn} onPress={clearAlpaca} disabled={saving}>
                    <Text style={styles.outlineBtnText}>Disconnect</Text>
                  </TouchableOpacity>
                )}
              </View>
            </Card>

            <Card style={styles.halfCard}>
              <View style={styles.brokerHead}>
                <Text style={styles.cardTitle}>Account Overview</Text>
                <Text style={styles.periodChip}>This Month</Text>
              </View>
              <Text style={styles.statLabel}>Total Equity</Text>
              <Text style={styles.equityValue}>
                {portfolio ? fmtMoney(portfolio.portfolio_value) : '—'}
              </Text>
              <Text style={styles.statLabel}>Total Return</Text>
              <Text style={[styles.returnValue, { color: monthReturnColor }]}>
                {portfolio ? fmtPct(perf.monthReturn) : '—'}
              </Text>
              {portfolio?.equity_curve?.length > 1 && (
                <View style={styles.sparkWrap}>
                  <ProfileSparkline data={portfolio.equity_curve.slice(-40)} width={140} height={44} />
                </View>
              )}
              <View style={styles.allTimeRow}>
                <Text style={styles.statLabel}>All Time Return</Text>
                <Text style={[styles.allTimeVal, { color: totalReturnColor }]}>
                  {portfolio ? fmtPct(perf.totalReturn) : '—'}
                </Text>
              </View>
            </Card>
          </View>

          {/* Risk management */}
          <Card>
            <SectionHeader
              icon="shield-checkmark"
              title="Risk Management"
              actionLabel="Edit Settings ›"
              onAction={comingSoon('Risk settings')}
            />
            <View style={styles.riskGrid}>
              <RiskTile
                icon="trending-down"
                value={`${MAX_DRAWDOWN_PCT}%`}
                label="Max Drawdown"
                sub="Kill Switch"
              />
              <RiskTile
                icon="cash-outline"
                value={`${CASH_RESERVE_PCT}%`}
                label="Cash Reserve"
                sub="Minimum"
              />
              <RiskTile
                icon="pie-chart-outline"
                value={`${MAX_POSITION_PCT}%`}
                label="Max Position"
                sub="Per Position"
              />
              <RiskTile
                icon="refresh-outline"
                value="Weekly"
                label="Auto Rebalancing"
                sub={`Next: ${nextRebalanceLabel()}`}
              />
            </View>
            {connected && portfolio?.drawdown_breached && (
              <View style={styles.warnBox}>
                <Text style={styles.warnText}>
                  Drawdown limit reached ({((portfolio.drawdown ?? 0) * 100).toFixed(1)}%). Review Portfolio.
                </Text>
              </View>
            )}
          </Card>

          {/* AI Strategy */}
          <Card>
            <SectionHeader
              icon="hardware-chip-outline"
              title="AI Strategy"
              actionLabel="View Details ›"
              onAction={comingSoon('AI Strategy')}
            />
            {!aiMeta.hasModels ? (
              <Text style={styles.muted}>Publish a model from the web dashboard to see strategy stats.</Text>
            ) : (
              <View style={styles.aiRow}>
                <View style={styles.aiLeft}>
                  <Text style={styles.aiLabel}>Current Mode</Text>
                  <Text style={styles.aiMode}>{aiMeta.mode}</Text>
                  <Text style={[styles.aiLabel, { marginTop: 10 }]}>Models Used</Text>
                  <View style={styles.chipRow}>
                    {aiMeta.chips.map((c) => (
                      <View key={c} style={styles.modelChip}>
                        <Ionicons name="checkmark-circle" size={12} color={COLORS.green} />
                        <Text style={styles.chipText}>{c}</Text>
                      </View>
                    ))}
                  </View>
                </View>
                <View style={styles.aiRight}>
                  <Text style={styles.aiStatLabel}>Model Update</Text>
                  <Text style={styles.aiStatVal}>{aiMeta.updated}</Text>
                  {aiMeta.sharpe != null && (
                    <>
                      <Text style={[styles.aiStatLabel, { marginTop: 8 }]}>Meta-Learner Sharpe</Text>
                      <Text style={[styles.aiStatVal, { color: COLORS.green }]}>
                        {Number(aiMeta.sharpe).toFixed(2)}
                      </Text>
                    </>
                  )}
                  {aiMeta.confPct != null && (
                    <>
                      <Text style={[styles.aiStatLabel, { marginTop: 8 }]}>Model Confidence</Text>
                      <Text style={[styles.aiStatVal, { color: COLORS.blue }]}>{aiMeta.confPct}%</Text>
                    </>
                  )}
                </View>
              </View>
            )}
          </Card>

          {/* Performance summary */}
          <Card>
            <View style={styles.brokerHead}>
              <View style={styles.sectionTitleRow}>
                <Ionicons name="bar-chart-outline" size={18} color={ACCENT} />
                <Text style={styles.sectionTitle}>Performance Summary</Text>
              </View>
              <Text style={styles.periodChip}>This Year</Text>
            </View>
            <View style={styles.perfRow}>
              {[
                ['Total Return', perf.totalReturn, true],
                ['Best Month', perf.bestMonth, true],
                ['Worst Month', perf.worstMonth, false],
                ['Total Trades', perf.trades, null],
                ['Win Rate', perf.winRate, true],
              ].map(([label, val, isPct]) => {
                let display = '—'
                let color = COLORS.textPrimary
                if (val != null) {
                  if (isPct === true) {
                    display = fmtPct(val)
                    color = val >= 0 ? COLORS.green : COLORS.red
                  } else if (isPct === false) {
                    display = fmtPct(val)
                    color = COLORS.red
                  } else if (label === 'Win Rate') {
                    display = `${Math.round((val <= 1 ? val * 100 : val))}%`
                  } else {
                    display = String(val)
                  }
                }
                return (
                  <View key={label} style={styles.perfCell}>
                    <Text style={styles.perfLabel}>{label}</Text>
                    <Text style={[styles.perfVal, { color }]}>{display}</Text>
                  </View>
                )
              })}
            </View>
          </Card>

          {/* Settings */}
          <View style={styles.settingsBlock}>
            <Text style={styles.settingsHeading}>Settings & Security</Text>
            <SettingsRow
              icon="notifications-outline"
              title="Notifications"
              subtitle="Manage alerts and notifications"
              onPress={comingSoon('Notifications')}
            />
            <SettingsRow
              icon="lock-closed-outline"
              title="Security"
              subtitle="Password, 2FA, active sessions"
              onPress={comingSoon('Security')}
            />
            <SettingsRow
              icon="options-outline"
              title="App Settings"
              subtitle={`Preferences · v${Constants.expoConfig?.version || '1.0.0'}`}
              onPress={comingSoon('App Settings')}
            />
            <SettingsRow icon="log-out-outline" title="Sign out" onPress={logout} danger />
          </View>
        </ScrollView>
      )}

      <Modal visible={brokerModal} animationType="slide" transparent>
        <Pressable style={styles.modalBackdrop} onPress={() => setBrokerModal(false)}>
          <Pressable style={styles.modalSheet} onPress={(e) => e.stopPropagation()}>
            <Text style={styles.modalTitle}>Connect Alpaca Paper</Text>
            <Text style={styles.modalSub}>
              Get free API keys at alpaca.markets → Paper Trading → API Keys.
            </Text>
            <TextInput
              style={styles.input}
              placeholder="API Key ID"
              placeholderTextColor={COLORS.textMuted}
              value={apiKey}
              onChangeText={setApiKey}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <TextInput
              style={styles.input}
              placeholder="API Secret"
              placeholderTextColor={COLORS.textMuted}
              value={apiSecret}
              onChangeText={setApiSecret}
              autoCapitalize="none"
              secureTextEntry
            />
            <TouchableOpacity style={styles.purpleBtn} onPress={saveAlpaca} disabled={saving}>
              <Text style={styles.purpleBtnText}>{saving ? 'Saving…' : 'Save & Connect'}</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.modalCancel} onPress={() => setBrokerModal(false)}>
              <Text style={styles.outlineBtnText}>Cancel</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 56,
    paddingHorizontal: 20,
    paddingBottom: 12,
  },
  topBarSide: { width: 32, alignItems: 'flex-end' },
  topTitle: { fontSize: 17, fontWeight: '700', color: COLORS.textPrimary },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 16, paddingBottom: 32 },

  heroCard: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    padding: 18,
    marginBottom: 14,
    overflow: 'hidden',
  },
  heroGlow: {
    position: 'absolute',
    top: -40,
    right: -30,
    width: 180,
    height: 120,
    borderRadius: 90,
    backgroundColor: COLORS.purpleBg,
  },
  heroRow: { flexDirection: 'row', alignItems: 'center' },
  avatarWrap: { marginRight: 14 },
  avatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: COLORS.purpleDim,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: ACCENT,
  },
  avatarText: { fontSize: 26, fontWeight: '700', color: '#fff' },
  cameraBadge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: ACCENT,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: COLORS.card,
  },
  heroMeta: { flex: 1 },
  heroName: { fontSize: 20, fontWeight: '700', color: COLORS.textPrimary },
  heroEmail: { fontSize: 13, color: COLORS.textMuted, marginTop: 2 },
  accountPill: {
    alignSelf: 'flex-start',
    backgroundColor: COLORS.purpleBg,
    borderRadius: RADIUS.full,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginTop: 8,
    borderWidth: 1,
    borderColor: 'rgba(168,85,247,0.35)',
  },
  accountPillText: { fontSize: 11, fontWeight: '600', color: ACCENT },
  memberRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 8 },
  memberText: { fontSize: 12, color: COLORS.textMuted },

  twoCol: { gap: 12, marginBottom: 14 },
  card: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    padding: 14,
    marginBottom: 14,
  },
  halfCard: { marginBottom: 0 },
  cardTitle: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary },
  brokerHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  connectedPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: COLORS.greenBg,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: RADIUS.full,
  },
  disconnectedPill: { backgroundColor: COLORS.amberBg },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  connectedText: { fontSize: 10, fontWeight: '700', color: COLORS.green },
  brokerBrand: { flexDirection: 'row', alignItems: 'center', marginBottom: 10, gap: 10 },
  alpacaLogo: {
    width: 36,
    height: 36,
    borderRadius: 8,
    backgroundColor: '#FEF3C7',
    alignItems: 'center',
    justifyContent: 'center',
  },
  alpacaEmoji: { fontSize: 20 },
  brokerName: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary },
  brokerSub: { fontSize: 11, color: COLORS.textMuted },
  statLabel: { fontSize: 11, color: COLORS.textMuted, marginTop: 6 },
  statValue: { fontSize: 14, fontWeight: '600', color: COLORS.textPrimary },
  syncText: { fontSize: 11, color: COLORS.green, marginTop: 8 },
  brokerActions: { flexDirection: 'row', gap: 8, marginTop: 12 },
  purpleBtn: {
    flex: 1,
    backgroundColor: ACCENT,
    borderRadius: RADIUS.md,
    paddingVertical: 10,
    alignItems: 'center',
  },
  purpleBtnText: { color: '#fff', fontWeight: '700', fontSize: 12 },
  outlineBtn: {
    flex: 1,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md,
    paddingVertical: 10,
    alignItems: 'center',
  },
  outlineBtnText: { color: COLORS.textSecondary, fontWeight: '600', fontSize: 12 },

  periodChip: {
    fontSize: 11,
    color: COLORS.textMuted,
    backgroundColor: COLORS.bg,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: RADIUS.sm,
    overflow: 'hidden',
  },
  equityValue: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  returnValue: { fontSize: 15, fontWeight: '700' },
  sparkWrap: { marginVertical: 8 },
  allTimeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 4,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: COLORS.cardBorder,
  },
  allTimeVal: { fontSize: 13, fontWeight: '700' },

  sectionHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  sectionTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },
  sectionAction: { fontSize: 12, color: ACCENT, fontWeight: '600' },

  riskGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  riskTile: {
    width: '47%',
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.md,
    padding: 10,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
  },
  riskValue: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary },
  riskLabel: { fontSize: 11, fontWeight: '600', color: COLORS.textSecondary, marginTop: 2 },
  riskSub: { fontSize: 10, color: COLORS.textMuted, marginTop: 2 },

  warnBox: {
    backgroundColor: COLORS.redBg,
    borderRadius: RADIUS.md,
    padding: 10,
    marginTop: 10,
  },
  warnText: { color: COLORS.red, fontSize: 12, lineHeight: 18 },

  aiRow: { flexDirection: 'row', gap: 12 },
  aiLeft: { flex: 1.2 },
  aiRight: { flex: 0.9, alignItems: 'flex-end' },
  aiLabel: { fontSize: 11, color: COLORS.textMuted },
  aiMode: { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary, marginTop: 2 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 6 },
  modelChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: COLORS.bg,
    borderRadius: RADIUS.full,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
  },
  chipText: { fontSize: 10, fontWeight: '600', color: COLORS.textSecondary },
  aiStatLabel: { fontSize: 10, color: COLORS.textMuted, textAlign: 'right' },
  aiStatVal: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary, textAlign: 'right' },

  perfRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between' },
  perfCell: { width: '30%', marginBottom: 12 },
  perfLabel: { fontSize: 10, color: COLORS.textMuted },
  perfVal: { fontSize: 13, fontWeight: '700', marginTop: 4 },

  muted: { fontSize: 13, color: COLORS.textMuted, lineHeight: 20 },

  settingsBlock: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    overflow: 'hidden',
    marginBottom: 8,
  },
  settingsHeading: {
    fontSize: 13,
    fontWeight: '700',
    color: COLORS.textMuted,
    paddingHorizontal: 14,
    paddingTop: 14,
    paddingBottom: 6,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  settingsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 14,
    borderTopWidth: 1,
    borderTopColor: COLORS.cardBorder,
  },
  settingsIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    backgroundColor: COLORS.purpleBg,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  settingsIconDanger: { backgroundColor: COLORS.redBg },
  settingsText: { flex: 1 },
  settingsTitle: { fontSize: 15, fontWeight: '600', color: COLORS.textPrimary },
  settingsSub: { fontSize: 12, color: COLORS.textMuted, marginTop: 2 },

  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'flex-end',
  },
  modalSheet: {
    backgroundColor: COLORS.card,
    borderTopLeftRadius: RADIUS.xl,
    borderTopRightRadius: RADIUS.xl,
    padding: 24,
    paddingBottom: 36,
  },
  modalTitle: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  modalSub: { fontSize: 13, color: COLORS.textMuted, marginTop: 6, marginBottom: 16, lineHeight: 20 },
  input: {
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md,
    paddingHorizontal: 12,
    paddingVertical: 12,
    color: COLORS.textPrimary,
    fontSize: 14,
    marginBottom: 10,
  },
  modalCancel: { alignItems: 'center', marginTop: 12 },
})
