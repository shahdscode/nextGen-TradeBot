import { useState, useEffect, useRef } from 'react'
import {
  View, Text, ScrollView, TouchableOpacity,
  TextInput, StyleSheet, ActivityIndicator,
  Dimensions, Alert, Switch,
} from 'react-native'
import LineChart from '../components/lineChart'
import client from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

const screenW = Dimensions.get('window').width
const chartW  = screenW - 40

// ── Formatters ────────────────────────────────────────────────────────────────
const fmtPct   = (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—'
const fmtMoney = (v) => v != null
  ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
  : '—'
const fmtRatio = (v) => v != null ? Number(v).toFixed(3) : '—'

// ── Metric tile ───────────────────────────────────────────────────────────────
function MetricBox({ label, value, good, bad }) {
  const color = bad ? COLORS.red : good ? COLORS.teal : COLORS.textPrimary
  return (
    <View style={styles.metricBox}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, { color }]}>{value ?? '—'}</Text>
    </View>
  )
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHeader({ title, sub }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {sub ? <Text style={styles.sectionSub}>{sub}</Text> : null}
    </View>
  )
}

// ── Baselines table ───────────────────────────────────────────────────────────
function BaselinesTable({ agentMetrics: am, baselines = {} }) {
  const cols = [
    { key: 'agent',        label: 'RL',        m: am },
    { key: 'buy_hold',     label: 'B&H',       m: baselines.buy_hold?.metrics },
    { key: 'sma',          label: 'SMA',       m: baselines.sma_crossover?.metrics },
    { key: 'momentum',     label: 'Mom',       m: baselines.momentum?.metrics },
    { key: 'equal_weight', label: 'EqWt',      m: baselines.equal_weight?.metrics },
    { key: 'random',       label: 'Rand',      m: baselines.random?.metrics },
  ]
  const rows = [
    { label: 'Return',  fns: cols.map(c => fmtPct(c.m?.total_return)),   better: 'higher', raws: cols.map(c => c.m?.total_return) },
    { label: 'Sharpe',  fns: cols.map(c => fmtRatio(c.m?.sharpe)),       better: 'higher', raws: cols.map(c => c.m?.sharpe) },
    { label: 'Sortino', fns: cols.map(c => fmtRatio(c.m?.sortino)),      better: 'higher', raws: cols.map(c => c.m?.sortino) },
    { label: 'Max DD',  fns: cols.map(c => fmtPct(c.m?.max_drawdown)),   better: 'lower',  raws: cols.map(c => c.m?.max_drawdown) },
    { label: 'Win %',   fns: cols.map(c => fmtPct(c.m?.win_rate)),       better: 'higher', raws: cols.map(c => c.m?.win_rate) },
  ]
  return (
    <View style={styles.card}>
      <SectionHeader title="Strategy Benchmarks" sub="RL vs Buy&Hold, SMA 20/50, Random" />
      {/* Column headers */}
      <View style={[styles.tableRow, styles.tableHead]}>
        <Text style={[styles.tableCell, styles.tableCellLeft, styles.tableHeadTxt]}>Metric</Text>
        {cols.map(c => (
          <Text key={c.key} style={[styles.tableCell, styles.tableHeadTxt,
            c.key === 'agent' && { color: COLORS.teal }]} numberOfLines={1}>
            {c.label}
          </Text>
        ))}
      </View>
      {rows.map(({ label, fns, better, raws }) => {
        const numRaw = raws.map(v => (v != null ? Number(v) : NaN))
        const bestIdx = numRaw.reduce((best, v, i) => {
          if (isNaN(v)) return best
          const isBetter = better === 'higher' ? v > (numRaw[best] ?? -Infinity) : v < (numRaw[best] ?? Infinity)
          return isBetter ? i : best
        }, 0)
        return (
          <View key={label} style={styles.tableRow}>
            <Text style={[styles.tableCell, styles.tableCellLeft, styles.tableRowLbl]}>{label}</Text>
            {fns.map((val, ci) => (
              <Text key={ci} style={[styles.tableCell,
                ci === bestIdx ? { fontWeight: '700', color: ci === 0 ? COLORS.teal : COLORS.textPrimary } : { color: COLORS.textMuted }
              ]}>
                {val}
              </Text>
            ))}
          </View>
        )
      })}
    </View>
  )
}

// ── Stress tests ──────────────────────────────────────────────────────────────
function StressTests({ base, stress }) {
  if (!stress) return null
  const scenarios = [
    { key: 'base',            label: 'Base',         m: base,                           color: COLORS.teal },
    { key: 'high_costs',      label: '2× Costs',     m: stress.high_costs?.metrics,     color: '#d97706' },
    { key: 'crash_scenario',  label: '−30% Crash',   m: stress.crash_scenario?.metrics, color: COLORS.red },
    { key: 'execution_delay', label: '1-Day Delay',  m: stress.execution_delay?.metrics, color: '#7c3aed' },
  ]
  return (
    <View style={styles.card}>
      <SectionHeader title="Stress Tests" sub="Adverse conditions" />
      {scenarios.map(({ key, label, m, color }) => (
        <View key={key} style={styles.stressRow}>
          <Text style={[styles.stressLabel, { color }]}>{label}</Text>
          <View style={styles.stressMets}>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>Ret </Text>
              <Text style={[{ fontWeight: '600' }, (m?.total_return ?? 0) >= 0 ? { color: COLORS.teal } : { color: COLORS.red }]}>
                {fmtPct(m?.total_return)}
              </Text>
            </Text>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>SR </Text>
              <Text style={styles.stressMetVal}>{fmtRatio(m?.sharpe)}</Text>
            </Text>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>DD </Text>
              <Text style={[(m?.max_drawdown ?? 0) > 0.3 ? { color: COLORS.red } : { color: COLORS.textMuted }]}>
                {fmtPct(m?.max_drawdown)}
              </Text>
            </Text>
          </View>
        </View>
      ))}
    </View>
  )
}

// ── Walk-forward ──────────────────────────────────────────────────────────────
function WalkForward({ periods }) {
  if (!periods?.length) return null
  return (
    <View style={styles.card}>
      <SectionHeader title="Walk-Forward Analysis" sub="Performance by quarter" />
      {periods.map(({ period, metrics: m }, i) => (
        <View key={i} style={styles.wfRow}>
          <Text style={styles.wfPeriod} numberOfLines={1}>{period}</Text>
          <View style={styles.wfMets}>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>Ret </Text>
              <Text style={[(m?.total_return ?? 0) >= 0 ? { color: COLORS.teal } : { color: COLORS.red }]}>
                {fmtPct(m?.total_return)}
              </Text>
            </Text>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>SR </Text>
              <Text style={styles.stressMetVal}>{fmtRatio(m?.sharpe)}</Text>
            </Text>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>DD </Text>
              <Text style={[(m?.max_drawdown ?? 0) > 0.2 ? { color: '#d97706' } : { color: COLORS.textMuted }]}>
                {fmtPct(m?.max_drawdown)}
              </Text>
            </Text>
          </View>
        </View>
      ))}
    </View>
  )
}

// ── RL sanity panel ───────────────────────────────────────────────────────────
function SanityPanel({ sanity }) {
  if (!sanity) return null
  const pass = !sanity.overtrading_flag && !sanity.action_bias_flag
  return (
    <View style={[styles.card, pass ? styles.sanityPass : styles.sanityWarn]}>
      <View style={styles.sanityHead}>
        <Text style={styles.sectionTitle}>RL Sanity Checks</Text>
        <View style={[styles.sanityBadge, pass ? styles.badgeGreen : styles.badgeAmber]}>
          <Text style={[styles.sanityBadgeTxt, pass ? { color: COLORS.teal } : { color: '#92400e' }]}>
            {pass ? '✓ Pass' : '⚠ Warning'}
          </Text>
        </View>
      </View>
      <View style={styles.metricsGrid}>
        <MetricBox label="Total Trades" value={sanity.n_trades} />
        <MetricBox label="Trades / Day"
          value={sanity.trades_per_day}
          bad={sanity.overtrading_flag} />
        <MetricBox label="Buy / Sell"
          value={`${sanity.buy_pct}% / ${sanity.sell_pct}%`}
          bad={sanity.action_bias_flag} />
        <MetricBox label="Turnover"
          value={sanity.turnover_rate != null ? `${sanity.turnover_rate}×` : '—'} />
        <MetricBox label="Avg Hold (d)"
          value={sanity.avg_hold_days ?? '—'} />
      </View>
      <Text style={styles.sanityVerdict}>{sanity.verdict}</Text>
    </View>
  )
}

// ── Confidence interval strip ─────────────────────────────────────────────────
function ConfidenceStrip({ metrics }) {
  if (!metrics?.sharpe_ci && metrics?.var_95 == null) return null
  const { sharpe_ci, var_95, cvar_95, return_skew } = metrics
  return (
    <View style={styles.card}>
      <SectionHeader title="Distribution & Confidence" sub="1000-resample bootstrap · 95% CI" />
      <View style={styles.metricsGrid}>
        {sharpe_ci && (
          <MetricBox label="Sharpe CI"
            value={`[${sharpe_ci.lower?.toFixed(2)}, ${sharpe_ci.upper?.toFixed(2)}]`} />
        )}
        {var_95 != null && (
          <MetricBox label="VaR 95% (daily)" value={fmtPct(var_95)} bad />
        )}
        {cvar_95 != null && (
          <MetricBox label="CVaR 95% (daily)" value={fmtPct(cvar_95)} bad />
        )}
        {return_skew != null && (
          <MetricBox label="Return Skew"
            value={return_skew?.toFixed(3)}
            bad={return_skew < -0.5} />
        )}
      </View>
    </View>
  )
}

// ── Regime analysis panel (mobile) ───────────────────────────────────────────
function RegimePanel({ regime }) {
  if (!regime?.regime_performance) return null
  const entries = Object.entries(regime.regime_performance)
  if (!entries.length) return null
  const regimeColors = {
    bull:            COLORS.teal,
    bear:            COLORS.red,
    high_volatility: '#d97706',
    low_volatility:  COLORS.blue,
  }
  return (
    <View style={styles.card}>
      <View style={styles.tradLogHead}>
        <SectionHeader title="Regime Analysis" sub="20-day rolling vol + trend" />
        {regime.trade_vol_correlation != null && (
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={styles.stressMetKey}>Trade–vol corr</Text>
            <Text style={[styles.metricValue, { fontSize: 14 },
              Math.abs(regime.trade_vol_correlation) > 0.3 ? { color: '#d97706' } : { color: COLORS.teal }]}>
              {regime.trade_vol_correlation.toFixed(3)}
            </Text>
          </View>
        )}
      </View>
      {entries.map(([key, r]) => (
        <View key={key} style={styles.stressRow}>
          <Text style={[styles.stressLabel, { color: regimeColors[key] || COLORS.textPrimary }]}>
            {r.label}
          </Text>
          <View style={styles.stressMets}>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>Ret </Text>
              <Text style={[{ fontWeight: '600' }, r.mean_daily_return >= 0 ? { color: COLORS.teal } : { color: COLORS.red }]}>
                {fmtPct(r.mean_daily_return)}
              </Text>
            </Text>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>SR </Text>
              <Text style={styles.stressMetVal}>{fmtRatio(r.sharpe_ann)}</Text>
            </Text>
            <Text style={styles.stressMet}>
              <Text style={styles.stressMetKey}>{r.n_days}d</Text>
            </Text>
          </View>
        </View>
      ))}
      {regime.trade_vol_note && (
        <Text style={styles.sanityVerdict}>{regime.trade_vol_note}</Text>
      )}
    </View>
  )
}

// ── Significance summary (mobile) ─────────────────────────────────────────────
function SignificanceSummary({ tests }) {
  if (!tests) return null
  const summary = tests._summary
  const entries = Object.entries(tests).filter(([k]) => k !== '_summary')
  if (!entries.length) return null
  const nBeats = summary?.beats_significantly ?? 0
  const pass = nBeats >= Math.max(1, entries.length * 0.6)
  return (
    <View style={[styles.card, pass ? styles.sanityPass : styles.sanityWarn]}>
      <View style={styles.sanityHead}>
        <Text style={styles.sectionTitle}>Diebold-Mariano Tests</Text>
        <View style={[styles.sanityBadge, pass ? styles.badgeGreen : styles.badgeAmber]}>
          <Text style={[styles.sanityBadgeTxt, pass ? { color: COLORS.teal } : { color: '#92400e' }]}>
            {nBeats}/{entries.length} beaten
          </Text>
        </View>
      </View>
      {entries.map(([name, r]) => (
        <View key={name} style={styles.ofGapRow}>
          <Text style={[styles.ofGapLabel, { width: 90, textTransform: 'capitalize' }]}>
            {name.replace(/_/g, ' ')}
          </Text>
          <Text style={[styles.ofGapVal, { width: 50, fontSize: 11 },
            r.dm_stat > 0 ? { color: COLORS.teal } : { color: COLORS.red }]}>
            {r.dm_stat?.toFixed(2)}
          </Text>
          <Text style={[styles.ofGapHint, { fontSize: 10 }]}>
            {r.significant ? (r.agent_beats ? '✓ p<.05' : '✗ p<.05') : `n.s. (${r.p_value?.toFixed(2)})`}
          </Text>
        </View>
      ))}
      {summary && <Text style={styles.sanityVerdict}>{summary.overall}</Text>}
    </View>
  )
}

// ── Overfitting report ────────────────────────────────────────────────────────
function OverfittingReport({ report }) {
  if (!report) return null
  const pass     = !report.verdict?.startsWith('⚠')
  const moderate = report.verdict?.startsWith('~')
  const cardStyle = pass && !moderate ? styles.ofPass : moderate ? styles.ofWarn : styles.ofFail

  const phases = [
    { key: 'train',      label: 'Train',      data: report.train      },
    { key: 'validation', label: 'Validation', data: report.validation },
    { key: 'test',       label: 'Test',        data: report.test       },
  ]

  return (
    <View style={[styles.card, cardStyle]}>
      <View style={styles.sanityHead}>
        <Text style={styles.sectionTitle}>Overfitting Report</Text>
        <View style={[styles.sanityBadge, pass && !moderate ? styles.badgeGreen : moderate ? styles.badgeAmber : styles.badgeRed]}>
          <Text style={[styles.sanityBadgeTxt,
            pass && !moderate ? { color: COLORS.teal } : moderate ? { color: '#92400e' } : { color: '#7f1d1d' }]}>
            {pass && !moderate ? '✓ OK' : moderate ? '~ Moderate' : '⚠ Risk'}
          </Text>
        </View>
      </View>

      {/* Three-phase cards */}
      <View style={styles.ofPhaseRow}>
        {phases.map(({ key, label, data }) => {
          const m = data?.metrics || {}
          return (
            <View key={key} style={styles.ofPhaseBox}>
              <Text style={styles.ofPhaseLabel}>{label}</Text>
              <Text style={styles.ofPhasePeriod} numberOfLines={1}>{data?.period || '—'}</Text>
              <Text style={[styles.ofPhaseValue, (m.total_return ?? 0) < 0 && { color: COLORS.red }]}>
                {m.total_return != null ? fmtPct(m.total_return) : '—'}
              </Text>
              <Text style={styles.ofPhaseSub}>
                SR {m.sharpe?.toFixed(2) ?? '—'} · DD {fmtPct(m.max_drawdown)}
              </Text>
            </View>
          )
        })}
      </View>

      {/* Gaps */}
      {report.gaps && Object.keys(report.gaps).length > 0 && (
        <View style={styles.ofGaps}>
          {[
            { k: 'train_to_val',  label: 'Train→Val'  },
            { k: 'val_to_test',   label: 'Val→Test'   },
            { k: 'train_to_test', label: 'Train→Test' },
          ].filter(({ k }) => report.gaps[k] != null).map(({ k, label }) => {
            const gap = report.gaps[k]
            const color = gap > 0.10 ? COLORS.red : gap > 0.02 ? '#d97706' : COLORS.teal
            return (
              <View key={k} style={styles.ofGapRow}>
                <Text style={styles.ofGapLabel}>{label}</Text>
                <Text style={[styles.ofGapVal, { color }]}>{fmtPct(gap)}</Text>
                <Text style={styles.ofGapHint}>
                  {gap > 0.20 ? 'Large ⚠' : gap > 0.10 ? 'Moderate' : gap > 0 ? 'Normal' : 'Improving ✓'}
                </Text>
              </View>
            )
          })}
        </View>
      )}

      <Text style={styles.sanityVerdict}>{report.verdict}</Text>
    </View>
  )
}

// ── Trade log ─────────────────────────────────────────────────────────────────
function TradeLog({ trades }) {
  const [filter, setFilter] = useState('all')
  if (!trades?.length) return null
  const filtered = filter === 'all' ? trades : trades.filter(t => t.action === filter)
  return (
    <View style={styles.card}>
      <View style={styles.tradLogHead}>
        <Text style={styles.sectionTitle}>Trade Log</Text>
        <Text style={styles.sectionSub}>{trades.length} trades</Text>
      </View>
      <View style={styles.tradeFilterRow}>
        {['all', 'buy', 'sell'].map(f => (
          <TouchableOpacity key={f} onPress={() => setFilter(f)}
            style={[styles.filterChip, filter === f && styles.filterChipActive]}>
            <Text style={[styles.filterChipTxt, filter === f && styles.filterChipTxtActive]}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {filtered.slice(0, 40).map((t, i) => (
        <View key={i} style={styles.tradeRow}>
          <View style={[styles.actionBadge,
            t.action === 'buy' ? styles.actionBuy : styles.actionSell]}>
            <Text style={[styles.actionTxt,
              t.action === 'buy' ? { color: '#065f46' } : { color: '#7f1d1d' }]}>
              {t.action.toUpperCase()}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.tradeTicker}>{t.ticker}</Text>
            <Text style={styles.tradeDate}>{t.date}</Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            {/* Exec Price (simulation) + Eff. Price (after friction) */}
            {t.price != null && (
              <Text style={styles.tradePrice}>
                Exec ${t.price.toFixed(2)}
                {t.effective_price != null && ` → $${t.effective_price.toFixed(2)}`}
              </Text>
            )}
            {/* Live reference price from Yahoo — shown in muted colour */}
            {t.live_price != null && (
              <Text style={styles.tradeLiveRef}>Live ref ${t.live_price.toFixed(2)}</Text>
            )}
            {t.slippage_pct != null && (
              <Text style={styles.tradeSlip}>Slip {t.slippage_pct.toFixed(3)}%</Text>
            )}
            {t.friction_cost != null && (
              <Text style={styles.tradeFriction}>−${t.friction_cost.toFixed(2)} friction</Text>
            )}
          </View>
        </View>
      ))}
      {filtered.length > 40 && (
        <Text style={styles.tradeMore}>…{filtered.length - 40} more trades</Text>
      )}
    </View>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────
export default function SimulatorScreen() {
  const [runs, setRuns]                   = useState([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [testStart, setTestStart]         = useState('2024-01-01')
  const [testEnd, setTestEnd]             = useState('2025-12-31')
  const [capital, setCapital]             = useState('100000')
  // Friction controls
  const [commissionPct, setCommissionPct] = useState('0.1')
  const [slippagePct, setSlippagePct]     = useState('0.1')
  const [maxPosPct, setMaxPosPct]         = useState('20')
  const [cooldown, setCooldown]           = useState('5')
  const [showFriction, setShowFriction]   = useState(false)

  const [submitting, setSubmitting]       = useState(false)
  const [polling, setPolling]             = useState(false)
  const [result, setResult]               = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    client.get('/api/train/runs')
      .then((r) => {
        const done = r.data.filter((x) => x.status === 'done')
        setRuns(done)
        setSelectedRunId((prev) => {
          if (prev) return prev
          const preferred = done.find((x) => x.algorithm === 'ppo') || done[0]
          return preferred?.run_id || ''
        })
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedRunId) return
    client.get('/api/mobile/latest-backtest', { params: { run_id: selectedRunId } })
      .then((r) => {
        if (r.data?.found && r.data.metrics) {
          const { found, backtest_id, run_id, status, test_start, test_end, ...payload } = r.data
          setResult({
            backtest_id,
            run_id,
            status,
            test_start,
            test_end,
            ...payload,
          })
        }
      })
      .catch(() => {})
  }, [selectedRunId])

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const handleRun = async () => {
    if (!selectedRunId) return Alert.alert('No model selected', 'Select a completed training run first.')
    const cap = parseFloat(capital.replace(/,/g, ''))
    if (isNaN(cap) || cap <= 0) return Alert.alert('Invalid capital', 'Enter a valid starting capital amount.')

    setSubmitting(true)
    setResult(null)
    try {
      const { data } = await client.post('/api/backtest', {
        run_id:           selectedRunId,
        test_start:       testStart,
        test_end:         testEnd,
        initial_capital:  cap,
        commission_pct:   parseFloat(commissionPct) / 100,
        slippage_pct:     parseFloat(slippagePct)   / 100,
        max_position_pct: parseFloat(maxPosPct)     / 100,
        cooldown_days:    parseInt(cooldown, 10),
      })

      setPolling(true)
      pollRef.current = setInterval(async () => {
        const r = await client.get(`/api/backtest/${data.backtest_id}`)
        if (r.data.status === 'done') {
          clearInterval(pollRef.current)
          setPolling(false)
          setResult(r.data)
        } else if (r.data.status === 'failed') {
          clearInterval(pollRef.current)
          setPolling(false)
          Alert.alert('Simulation failed', r.data.error || 'Unknown error')
        }
      }, 2000)
    } catch {
      // handled by client interceptor
    } finally {
      setSubmitting(false)
    }
  }

  const m            = result?.metrics || {}
  const roundTrip    = ((parseFloat(commissionPct || 0) + parseFloat(slippagePct || 0)) * 2).toFixed(2)

  const chartData = result?.dates?.map((d, i) => ({
    date: d, value: result.account_value?.[i] ?? 0,
  })) || []
  const benchmarkData = result?.benchmark?.dates?.map((d, i) => ({
    date: d, value: result.benchmark?.account_value?.[i] ?? 0,
  })) || []

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.title}>Simulator</Text>
        <Text style={styles.subtitle}>Historical backtest · not live trading</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>

        {/* Config card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Parameters</Text>

          <Text style={styles.label}>Model Run</Text>
          <View style={styles.pickerWrap}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              <View style={styles.pickerRow}>
                {runs.length === 0
                  ? <Text style={styles.noRuns}>No completed runs yet</Text>
                  : runs.map((r) => (
                    <TouchableOpacity key={r.run_id}
                      onPress={() => setSelectedRunId(r.run_id)}
                      style={[styles.runChip, selectedRunId === r.run_id && styles.runChipActive]}>
                      <Text style={[styles.runChipText, selectedRunId === r.run_id && styles.runChipTextActive]}>
                        {r.algorithm.toUpperCase()} · {r.run_id.slice(0, 6)}
                      </Text>
                    </TouchableOpacity>
                  ))}
              </View>
            </ScrollView>
          </View>

          <View style={styles.row}>
            <View style={styles.halfField}>
              <Text style={styles.label}>Start Date</Text>
              <TextInput style={styles.input} value={testStart} onChangeText={setTestStart}
                placeholder="YYYY-MM-DD" placeholderTextColor={COLORS.textMuted} />
            </View>
            <View style={styles.halfField}>
              <Text style={styles.label}>End Date</Text>
              <TextInput style={styles.input} value={testEnd} onChangeText={setTestEnd}
                placeholder="YYYY-MM-DD" placeholderTextColor={COLORS.textMuted} />
            </View>
          </View>

          <Text style={styles.label}>Starting Capital ($)</Text>
          <TextInput style={styles.input} value={capital} onChangeText={setCapital}
            keyboardType="numeric" placeholder="100000" placeholderTextColor={COLORS.textMuted} />
          <View style={styles.quickCapRow}>
            {[10000, 50000, 100000, 1000000].map(v => (
              <TouchableOpacity key={v} onPress={() => setCapital(String(v))} style={styles.quickCap}>
                <Text style={styles.quickCapTxt}>${(v / 1000).toFixed(0)}k</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Friction toggle */}
          <View style={styles.frictionToggleRow}>
            <Text style={styles.label}>Trading Friction</Text>
            <Switch
              value={showFriction}
              onValueChange={setShowFriction}
              trackColor={{ false: COLORS.cardBorder, true: COLORS.teal + '55' }}
              thumbColor={showFriction ? COLORS.teal : COLORS.textMuted}
            />
          </View>

          {showFriction && (
            <View style={styles.frictionGrid}>
              {[
                { label: 'Commission %', value: commissionPct, set: setCommissionPct },
                { label: 'Slippage %',   value: slippagePct,   set: setSlippagePct   },
                { label: 'Max Pos %',    value: maxPosPct,     set: setMaxPosPct     },
                { label: 'Cooldown d',   value: cooldown,      set: setCooldown      },
              ].map(({ label, value, set }) => (
                <View key={label} style={styles.frictionField}>
                  <Text style={styles.frictionLabel}>{label}</Text>
                  <TextInput style={styles.frictionInput} value={value}
                    onChangeText={set} keyboardType="decimal-pad"
                    placeholderTextColor={COLORS.textMuted} />
                </View>
              ))}
              <View style={styles.frictionHint}>
                <Text style={styles.frictionHintTxt}>
                  Round-trip ≈ {roundTrip}% per trade
                </Text>
              </View>
            </View>
          )}

          <TouchableOpacity
            style={[styles.btn, (submitting || polling) && styles.btnDisabled]}
            onPress={handleRun}
            disabled={submitting || polling}
            activeOpacity={0.8}
          >
            {polling ? (
              <View style={styles.btnInner}>
                <ActivityIndicator color="#fff" size="small" />
                <Text style={styles.btnText}>  Running…</Text>
              </View>
            ) : (
              <Text style={styles.btnText}>{submitting ? 'Starting…' : 'Run Simulation'}</Text>
            )}
          </TouchableOpacity>
        </View>

        {/* ── Results ────────────────────────────────────────────────────────── */}
        {result && (
          <>
            {result.data_source && (
              <View style={styles.loadedBanner}>
                <Text style={styles.loadedBannerTxt}>
                  Data: {result.data_source}
                  {result.test_start ? ` · ${result.test_start} → ${result.test_end}` : ''}
                </Text>
              </View>
            )}

            {/* Friction notice */}
            {result.transaction_costs && (
              <View style={styles.frictionNotice}>
                <Text style={styles.frictionNoticeTxt}>
                  {result.transaction_costs.note}
                </Text>
              </View>
            )}

            {/* Capital summary */}
            <View style={styles.capitalRow}>
              {[
                { label: 'Start',   value: fmtMoney(result.initial_capital) },
                { label: 'Final',   value: fmtMoney(m.final_value) },
                { label: 'P&L',     value: fmtMoney((m.final_value ?? 0) - (result.initial_capital ?? 0)),
                  color: (m.final_value ?? 0) >= (result.initial_capital ?? 0) ? COLORS.teal : COLORS.red },
              ].map(({ label, value, color }) => (
                <View key={label} style={styles.capitalBox}>
                  <Text style={styles.capitalLabel}>{label}</Text>
                  <Text style={[styles.capitalValue, color ? { color } : {}]} numberOfLines={1}>{value}</Text>
                </View>
              ))}
            </View>

            {/* Core metrics — 3 rows of 2 */}
            <View style={styles.metricsGrid}>
              <MetricBox label="Total Return"    value={fmtPct(m.total_return)}    good={m.total_return > 0} />
              <MetricBox label="CAGR"            value={fmtPct(m.cagr)}             good={m.cagr > 0} />
              <MetricBox label="Sharpe"          value={fmtRatio(m.sharpe)}         good={m.sharpe >= 1} />
              <MetricBox label="Sortino"         value={fmtRatio(m.sortino)}        good={m.sortino >= 1} />
              <MetricBox label="Calmar"          value={fmtRatio(m.calmar)}         good={m.calmar >= 1} />
              <MetricBox label="Profit Factor"   value={m.profit_factor?.toFixed(2)} good={m.profit_factor >= 1.2} />
              <MetricBox label="Win Rate"        value={fmtPct(m.win_rate)}         good={m.win_rate >= 0.5} />
              <MetricBox label="Max Drawdown"    value={fmtPct(m.max_drawdown)}     bad={m.max_drawdown >= 0.35}
                good={m.max_drawdown < 0.2} />
              <MetricBox label="Avg Trade Ret"   value={fmtPct(m.avg_trade_return)} good={m.avg_trade_return > 0} />
              <MetricBox label="Exposure"        value={fmtPct(m.exposure_pct)} />
              <MetricBox label="Turnover"
                value={m.turnover != null ? `${m.turnover.toFixed(2)}×` : '—'}
                good={m.turnover < 5} />
              <MetricBox label="Win Days"        value={m.win_days} />
            </View>

            {/* Equity curve */}
            {chartData.length > 1 && (
              <View style={styles.chartCard}>
                <View style={styles.chartHeader}>
                  <Text style={styles.sectionTitle}>Equity Curve</Text>
                  <View style={styles.legend}>
                    <View style={[styles.legendDot, { backgroundColor: COLORS.teal }]} />
                    <Text style={styles.legendLabel}>Portfolio</Text>
                    {benchmarkData.length > 1 && (
                      <>
                        <View style={[styles.legendDot, { backgroundColor: COLORS.textMuted, marginLeft: 10 }]} />
                        <Text style={styles.legendLabel}>S&P 500</Text>
                      </>
                    )}
                  </View>
                </View>
                <LineChart data={chartData} benchmark={benchmarkData} width={chartW - 32} height={200} />
              </View>
            )}

            {/* Strategy benchmarks */}
            <BaselinesTable agentMetrics={m} baselines={result.baselines} />

            {/* Walk-forward */}
            <WalkForward periods={result.walk_forward_periods} />

            {/* Stress tests */}
            <StressTests base={m} stress={result.stress_tests} />

            {/* RL sanity */}
            <SanityPanel sanity={result.rl_sanity} />

            {/* Distribution + CI */}
            <ConfidenceStrip metrics={result.metrics} />

            {/* Regime analysis */}
            <RegimePanel regime={result.regime_analysis} />

            {/* Significance tests */}
            <SignificanceSummary tests={result.significance_tests} />

            {/* Overfitting report */}
            <OverfittingReport report={result.overfitting_report} />

            {/* Trade log */}
            <TradeLog trades={result.trades} />
          </>
        )}
      </ScrollView>
    </View>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  root:   { flex: 1, backgroundColor: COLORS.bg },
  header: {
    paddingHorizontal: 20, paddingTop: 56, paddingBottom: 16,
    borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder,
  },
  title:    { fontSize: 20, fontWeight: '800', color: COLORS.textPrimary },
  subtitle: { fontSize: 13, color: COLORS.textMuted, marginTop: 2 },
  scroll:   { padding: 20, paddingBottom: 80 },

  card: {
    backgroundColor: COLORS.card, borderRadius: RADIUS.lg,
    borderWidth: 1, borderColor: COLORS.cardBorder,
    padding: 16, marginBottom: 14,
  },
  cardTitle: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 14 },
  label:     { fontSize: 12, color: COLORS.textMuted, marginBottom: 5, marginTop: 10 },
  input: {
    backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md, paddingHorizontal: 12, paddingVertical: 10,
    fontSize: 14, color: COLORS.textPrimary,
  },
  pickerWrap:  { marginBottom: 2 },
  pickerRow:   { flexDirection: 'row', gap: 8 },
  noRuns:      { fontSize: 13, color: COLORS.textMuted },
  runChip: {
    paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: RADIUS.full, backgroundColor: COLORS.bg,
    borderWidth: 1, borderColor: COLORS.cardBorder,
  },
  runChipActive:     { borderColor: COLORS.teal, backgroundColor: COLORS.teal + '15' },
  runChipText:       { fontSize: 12, color: COLORS.textMuted, fontWeight: '500' },
  runChipTextActive: { color: COLORS.teal, fontWeight: '700' },
  row:       { flexDirection: 'row', gap: 12 },
  halfField: { flex: 1 },

  quickCapRow: { flexDirection: 'row', gap: 8, marginTop: 8 },
  quickCap:    { paddingHorizontal: 10, paddingVertical: 4, borderRadius: RADIUS.full, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.cardBorder },
  quickCapTxt: { fontSize: 11, color: COLORS.textMuted },

  frictionToggleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 },
  frictionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 6 },
  frictionField: { width: '47%' },
  frictionLabel: { fontSize: 11, color: COLORS.textMuted, marginBottom: 3 },
  frictionInput: {
    backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md, paddingHorizontal: 10, paddingVertical: 8,
    fontSize: 13, color: COLORS.textPrimary,
  },
  frictionHint:    { width: '100%' },
  frictionHintTxt: { fontSize: 11, color: '#b45309', backgroundColor: '#fffbeb', borderRadius: RADIUS.sm, paddingHorizontal: 8, paddingVertical: 4, marginTop: 2 },

  btn:         { backgroundColor: COLORS.teal, borderRadius: RADIUS.md, paddingVertical: 14, alignItems: 'center', marginTop: 18 },
  btnDisabled: { opacity: 0.5 },
  btnInner:    { flexDirection: 'row', alignItems: 'center' },
  btnText:     { color: '#fff', fontWeight: '700', fontSize: 15 },

  loadedBanner: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    padding: 10,
    marginBottom: 10,
  },
  loadedBannerTxt: { fontSize: 11, color: COLORS.textMuted },

  frictionNotice: {
    backgroundColor: '#eff6ff', borderRadius: RADIUS.md, borderWidth: 1,
    borderColor: '#bfdbfe', padding: 12, marginBottom: 12,
  },
  frictionNoticeTxt: { fontSize: 12, color: '#1d4ed8' },

  capitalRow: { flexDirection: 'row', gap: 10, marginBottom: 12 },
  capitalBox: {
    flex: 1, backgroundColor: COLORS.card, borderRadius: RADIUS.md,
    borderWidth: 1, borderColor: COLORS.cardBorder, padding: 12,
  },
  capitalLabel: { fontSize: 11, color: COLORS.textMuted, marginBottom: 4 },
  capitalValue: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },

  metricsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 14 },
  metricBox: {
    flex: 1, minWidth: '45%', backgroundColor: COLORS.card,
    borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.cardBorder, padding: 12,
  },
  metricLabel: { fontSize: 11, color: COLORS.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 5 },
  metricValue: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary },

  chartCard: {
    backgroundColor: COLORS.card, borderRadius: RADIUS.lg,
    borderWidth: 1, borderColor: COLORS.cardBorder, padding: 16, marginBottom: 14,
  },
  chartHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  legend:      { flexDirection: 'row', alignItems: 'center' },
  legendDot:   { width: 8, height: 8, borderRadius: 4, marginRight: 4 },
  legendLabel: { fontSize: 11, color: COLORS.textMuted },

  sectionHeader: { marginBottom: 12 },
  sectionTitle:  { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary },
  sectionSub:    { fontSize: 11, color: COLORS.textMuted, marginTop: 1 },

  // Baselines table
  tableRow:     { flexDirection: 'row', paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder + '55' },
  tableHead:    { backgroundColor: COLORS.bg + 'cc', borderRadius: RADIUS.sm },
  tableHeadTxt: { fontSize: 10, fontWeight: '700', color: COLORS.textMuted, textTransform: 'uppercase', textAlign: 'right' },
  tableCell:    { flex: 1, fontSize: 11, color: COLORS.textMuted, textAlign: 'right' },
  tableCellLeft:{ textAlign: 'left' },
  tableRowLbl:  { fontSize: 11, color: COLORS.textPrimary, fontWeight: '600' },

  // Stress tests
  stressRow:    { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder + '33' },
  stressLabel:  { width: 80, fontSize: 12, fontWeight: '600' },
  stressMets:   { flex: 1, flexDirection: 'row', gap: 10, justifyContent: 'flex-end' },
  stressMet:    { fontSize: 11 },
  stressMetKey: { color: COLORS.textMuted },
  stressMetVal: { color: COLORS.textPrimary },

  // Walk-forward
  wfRow:    { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder + '33' },
  wfPeriod: { fontSize: 11, color: COLORS.textMuted, fontFamily: 'monospace', marginBottom: 4 },
  wfMets:   { flexDirection: 'row', gap: 14 },

  // Sanity
  sanityPass: { borderColor: '#6ee7b7' + '66', backgroundColor: '#f0fdf4' },
  sanityWarn: { borderColor: '#fcd34d' + '66', backgroundColor: '#fffbeb' },
  sanityHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sanityBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.full },
  badgeGreen:  { backgroundColor: '#d1fae5' },
  badgeAmber:  { backgroundColor: '#fef3c7' },
  sanityBadgeTxt: { fontSize: 11, fontWeight: '700' },
  sanityVerdict:  { fontSize: 11, color: COLORS.textMuted, fontStyle: 'italic', marginTop: 8 },

  // Overfitting report
  ofPass:      { borderColor: '#6ee7b7' + '66', backgroundColor: '#f0fdf4' },
  ofWarn:      { borderColor: '#fcd34d' + '66', backgroundColor: '#fffbeb' },
  ofFail:      { borderColor: '#fca5a5' + '66', backgroundColor: '#fff1f2' },
  badgeRed:    { backgroundColor: '#fee2e2' },
  ofPhaseRow:  { flexDirection: 'row', gap: 8, marginBottom: 12 },
  ofPhaseBox:  { flex: 1, backgroundColor: COLORS.card, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.cardBorder, padding: 10 },
  ofPhaseLabel:{ fontSize: 10, fontWeight: '700', color: COLORS.textMuted, textTransform: 'uppercase', letterSpacing: 0.5 },
  ofPhasePeriod:{ fontSize: 9, color: COLORS.textMuted, fontFamily: 'monospace', marginVertical: 2 },
  ofPhaseValue:{ fontSize: 14, fontWeight: '700', color: COLORS.teal },
  ofPhaseSub:  { fontSize: 9, color: COLORS.textMuted, marginTop: 2 },
  ofGaps:      { backgroundColor: COLORS.card, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.cardBorder, padding: 10, marginBottom: 10 },
  ofGapRow:    { flexDirection: 'row', alignItems: 'center', paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder + '44' },
  ofGapLabel:  { width: 80, fontSize: 11, color: COLORS.textMuted },
  ofGapVal:    { width: 60, fontSize: 12, fontWeight: '700' },
  ofGapHint:   { flex: 1, fontSize: 10, color: COLORS.textMuted, textAlign: 'right' },

  // Trade log
  tradLogHead:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  tradeFilterRow: { flexDirection: 'row', gap: 8, marginBottom: 12 },
  filterChip:     { paddingHorizontal: 12, paddingVertical: 5, borderRadius: RADIUS.full, backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.cardBorder },
  filterChipActive: { backgroundColor: COLORS.textPrimary, borderColor: COLORS.textPrimary },
  filterChipTxt:    { fontSize: 12, color: COLORS.textMuted },
  filterChipTxtActive: { color: '#fff', fontWeight: '600' },
  tradeRow:     { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder + '44' },
  actionBadge:  { paddingHorizontal: 8, paddingVertical: 3, borderRadius: RADIUS.sm, width: 42, alignItems: 'center' },
  actionBuy:    { backgroundColor: '#d1fae5' },
  actionSell:   { backgroundColor: '#fee2e2' },
  actionTxt:    { fontSize: 10, fontWeight: '700' },
  tradeTicker:  { fontSize: 13, fontWeight: '700', color: COLORS.textPrimary },
  tradeDate:    { fontSize: 11, color: COLORS.textMuted },
  tradePrice:   { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary },
  tradeLiveRef: { fontSize: 10, color: '#9ca3af' },          // muted — reference only
  tradeSlip:    { fontSize: 10, color: '#6366f1' },          // indigo — slippage
  tradeFriction:{ fontSize: 10, color: '#d97706' },
  tradeMore:    { textAlign: 'center', fontSize: 12, color: COLORS.textMuted, paddingTop: 12 },
})
