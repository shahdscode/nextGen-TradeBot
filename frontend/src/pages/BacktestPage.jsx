import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import client from '../api/client'
import EquityCurveChart from '../components/equityCurveChart'
import MetricsCard from '../components/metricsCard'
import JobStatusBadge from '../components/jobStatusBadge'
import { ChartSkeleton, CardSkeleton } from '../components/skeleton'

// ── Formatters ────────────────────────────────────────────────────────────────
const fmtCurrency = (v) =>
  v != null ? `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'
const fmtPct   = (v) => v != null ? `${(v * 100).toFixed(2)}%` : '—'
const fmtRatio = (v) => v != null ? Number(v).toFixed(3) : '—'

const actionBadge = {
  buy:  'bg-green-100 text-green-700',
  sell: 'bg-red-100 text-red-700',
  hold: 'bg-gray-100 text-gray-500',
}

const stressColors = {
  base:            'text-blue-700',
  high_costs:      'text-amber-700',
  crash_scenario:  'text-red-700',
  execution_delay: 'text-purple-700',
}

// ── Baseline comparison table ─────────────────────────────────────────────────
function BaselinesTable({ agentMetrics, baselines = {} }) {
  const cols = [
    { key: 'agent',        label: 'RL Agent',     metrics: agentMetrics,                       color: 'text-blue-700 font-semibold' },
    { key: 'buy_hold',     label: 'Buy & Hold',   metrics: baselines.buy_hold?.metrics,         color: 'text-gray-700' },
    { key: 'sma',          label: 'SMA 20/50',    metrics: baselines.sma_crossover?.metrics,    color: 'text-gray-700' },
    { key: 'momentum',     label: 'Momentum',     metrics: baselines.momentum?.metrics,         color: 'text-indigo-600' },
    { key: 'equal_weight', label: 'Equal-Wt',     metrics: baselines.equal_weight?.metrics,     color: 'text-teal-600' },
    { key: 'random',       label: 'Random',       metrics: baselines.random?.metrics,           color: 'text-gray-400' },
  ]
  const rows = [
    { label: 'Total Return', fn: (m) => fmtPct(m?.total_return),  better: 'higher' },
    { label: 'CAGR',         fn: (m) => fmtPct(m?.cagr),          better: 'higher' },
    { label: 'Sharpe',       fn: (m) => fmtRatio(m?.sharpe),      better: 'higher' },
    { label: 'Sortino',      fn: (m) => fmtRatio(m?.sortino),     better: 'higher' },
    { label: 'Max Drawdown', fn: (m) => fmtPct(m?.max_drawdown),  better: 'lower'  },
    { label: 'Win Rate',     fn: (m) => fmtPct(m?.win_rate),      better: 'higher' },
    { label: 'Profit Factor',fn: (m) => fmtRatio(m?.profit_factor), better: 'higher' },
  ]

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <h2 className="text-sm font-medium text-gray-700">Strategy Benchmarks</h2>
        <span className="text-xs text-gray-400">RL Agent vs Buy&Hold · SMA 20/50 · 12-1 Momentum · Equal-Weight · Random</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-2 text-xs text-gray-500 font-medium">Metric</th>
              {cols.map(c => (
                <th key={c.key} className={`text-right px-4 py-2 text-xs font-medium ${c.color}`}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map(({ label, fn, better }) => {
              const vals = cols.map(c => ({ ...c, val: fn(c.metrics), raw: c.metrics }))
              // Find best value for highlighting
              const numVals = vals.map(v => parseFloat(v.val?.replace(/[%$,]/g, '') ?? 'NaN'))
              const bestIdx = numVals.reduce((best, v, i) => {
                if (isNaN(v)) return best
                const isBetter = better === 'higher' ? v > (numVals[best] ?? -Infinity) : v < (numVals[best] ?? Infinity)
                return isBetter ? i : best
              }, 0)
              return (
                <tr key={label} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 text-xs text-gray-500 font-medium">{label}</td>
                  {vals.map((col, ci) => (
                    <td key={col.key} className={`px-4 py-2.5 text-right text-xs ${
                      ci === bestIdx ? 'font-bold ' + col.color : 'text-gray-600'
                    }`}>
                      {col.val ?? '—'}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Stress tests section ──────────────────────────────────────────────────────
function StressTestsTable({ base, stress }) {
  if (!stress) return null
  const scenarios = [
    { key: 'base',            label: 'Base (no stress)',       metrics: base },
    { key: 'high_costs',      label: stress.high_costs?.label ?? '2× Costs',    metrics: stress.high_costs?.metrics },
    { key: 'crash_scenario',  label: stress.crash_scenario?.label ?? 'Crash',   metrics: stress.crash_scenario?.metrics },
    { key: 'execution_delay', label: stress.execution_delay?.label ?? '1-Day Delay', metrics: stress.execution_delay?.metrics },
  ]
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <h2 className="text-sm font-medium text-gray-700">Stress Tests</h2>
        <span className="text-xs text-gray-400">How the strategy survives adverse conditions</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-2 text-xs text-gray-500 font-medium">Scenario</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Total Return</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Sharpe</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Sortino</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Max Drawdown</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Final Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {scenarios.map(({ key, label, metrics: m }) => (
              <tr key={key} className={key === 'base' ? 'bg-gray-50' : 'hover:bg-gray-50'}>
                <td className={`px-4 py-2.5 text-xs font-medium ${stressColors[key] || 'text-gray-600'}`}>
                  {key === 'base' && <span className="mr-1">↳</span>}{label}
                </td>
                <td className={`px-4 py-2.5 text-right text-xs ${m?.total_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {fmtPct(m?.total_return)}
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtRatio(m?.sharpe)}</td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtRatio(m?.sortino)}</td>
                <td className={`px-4 py-2.5 text-right text-xs ${(m?.max_drawdown ?? 0) > 0.3 ? 'text-red-600 font-medium' : 'text-gray-600'}`}>
                  {fmtPct(m?.max_drawdown)}
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtCurrency(m?.final_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Walk-forward sub-period table ─────────────────────────────────────────────
function WalkForwardTable({ periods }) {
  if (!periods?.length) return null
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <h2 className="text-sm font-medium text-gray-700">Walk-Forward Sub-Period Analysis</h2>
        <span className="text-xs text-gray-400">Performance stability across quarters</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-2 text-xs text-gray-500 font-medium">Period</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Return</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Sharpe</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Sortino</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Max DD</th>
              <th className="text-right px-4 py-2 text-xs text-gray-500 font-medium">Win Rate</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {periods.map(({ period, metrics: m }, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-4 py-2.5 text-xs text-gray-700 font-mono">{period}</td>
                <td className={`px-4 py-2.5 text-right text-xs ${m?.total_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {fmtPct(m?.total_return)}
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtRatio(m?.sharpe)}</td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtRatio(m?.sortino)}</td>
                <td className={`px-4 py-2.5 text-right text-xs ${(m?.max_drawdown ?? 0) > 0.2 ? 'text-amber-600' : 'text-gray-600'}`}>
                  {fmtPct(m?.max_drawdown)}
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtPct(m?.win_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── RL sanity checks panel ────────────────────────────────────────────────────
function SanityPanel({ sanity }) {
  if (!sanity) return null
  const pass = !sanity.overtrading_flag && !sanity.action_bias_flag
  return (
    <div className={`border rounded-xl p-4 ${pass ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-sm font-medium text-gray-700">RL Sanity Checks</h2>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${pass ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
          {pass ? '✓ Pass' : '⚠ Warning'}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
        {[
          { label: 'Total Trades',    value: sanity.n_trades },
          { label: 'Trades / Day',    value: sanity.trades_per_day, warn: sanity.overtrading_flag },
          { label: 'Buy / Sell Split',value: `${sanity.buy_pct}% / ${sanity.sell_pct}%`, warn: sanity.action_bias_flag },
          { label: 'Turnover Rate',   value: sanity.turnover_rate != null ? `${sanity.turnover_rate}×` : '—' },
          { label: 'Avg Hold (days)', value: sanity.avg_hold_days ?? '—' },
        ].map(({ label, value, warn }) => (
          <div key={label} className="bg-white border border-gray-200 rounded-lg p-3">
            <p className="text-xs text-gray-400 mb-0.5">{label}</p>
            <p className={`text-sm font-semibold ${warn ? 'text-amber-600' : 'text-gray-800'}`}>{value ?? '—'}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-gray-600 italic">{sanity.verdict}</p>
    </div>
  )
}

// ── Walk-forward summary strip ────────────────────────────────────────────────
function WalkForwardSummary({ summary }) {
  if (!summary || !summary.n_windows) return null
  const consistencyColor = {
    High:   'text-green-600',
    Medium: 'text-amber-600',
    Low:    'text-red-600',
  }[summary.consistency] || 'text-gray-600'
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap gap-6 text-sm">
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Windows</p>
        <p className="font-semibold text-gray-800">{summary.n_windows}</p>
      </div>
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Positive windows</p>
        <p className={`font-semibold ${summary.pct_positive >= 60 ? 'text-green-600' : 'text-red-600'}`}>
          {summary.positive_windows}/{summary.n_windows} ({summary.pct_positive}%)
        </p>
      </div>
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Avg return / window</p>
        <p className={`font-semibold ${summary.mean_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
          {fmtPct(summary.mean_return)}
          <span className="text-gray-400 font-normal text-xs ml-1">±{fmtPct(summary.std_return)}</span>
        </p>
      </div>
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Avg Sharpe / window</p>
        <p className="font-semibold text-gray-800">{fmtRatio(summary.mean_sharpe)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Avg Max DD / window</p>
        <p className={`font-semibold ${(summary.mean_max_dd ?? 0) > 0.2 ? 'text-amber-600' : 'text-gray-800'}`}>
          {fmtPct(summary.mean_max_dd)}
        </p>
      </div>
      <div>
        <p className="text-xs text-gray-400 mb-0.5">Consistency</p>
        <p className={`font-semibold ${consistencyColor}`}>{summary.consistency}</p>
      </div>
    </div>
  )
}

// ── Overfitting report ────────────────────────────────────────────────────────
function OverfittingReport({ report }) {
  if (!report) return null
  const pass = !report.verdict?.startsWith('⚠')
  const moderate = report.verdict?.startsWith('~')
  const bgColor = pass && !moderate ? 'bg-green-50 border-green-200'
                : moderate          ? 'bg-amber-50 border-amber-200'
                                    : 'bg-red-50 border-red-200'

  const phases = [
    { key: 'train',      label: 'Training',   data: report.train      },
    { key: 'validation', label: 'Validation', data: report.validation },
    { key: 'test',       label: 'Test',        data: report.test       },
  ]

  const gapColor = (gap) => gap == null ? 'text-gray-400'
    : gap > 0.10 ? 'text-red-600 font-semibold'
    : gap > 0.02 ? 'text-amber-600'
    : 'text-green-600'

  return (
    <div className={`border rounded-xl p-4 ${bgColor}`}>
      <div className="flex items-center gap-2 mb-4">
        <h2 className="text-sm font-medium text-gray-700">Overfitting Report</h2>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
          pass && !moderate ? 'bg-green-100 text-green-700'
          : moderate        ? 'bg-amber-100 text-amber-700'
                            : 'bg-red-100 text-red-700'
        }`}>
          {pass && !moderate ? '✓ Good generalization' : report.verdict?.slice(0, 1) === '~' ? '~ Moderate' : '⚠ Overfitting risk'}
        </span>
      </div>

      {/* Phase comparison */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        {phases.map(({ key, label, data }) => {
          const m = data?.metrics || {}
          return (
            <div key={key} className="bg-white border border-gray-200 rounded-xl p-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-0.5">{label}</p>
              <p className="text-xs text-gray-400 mb-2 font-mono">{data?.period || '—'}</p>
              <div className="space-y-1">
                {[
                  { l: 'Total Return', v: fmtPct(m.total_return),  neg: (m.total_return ?? 0) < 0 },
                  { l: 'Sharpe',       v: fmtRatio(m.sharpe) },
                  { l: 'Max Drawdown', v: fmtPct(m.max_drawdown),   neg: (m.max_drawdown ?? 0) > 0.25 },
                  { l: 'Win Rate',     v: fmtPct(m.win_rate) },
                ].map(({ l, v, neg }) => (
                  <div key={l} className="flex justify-between">
                    <span className="text-xs text-gray-400">{l}</span>
                    <span className={`text-xs font-medium ${neg ? 'text-red-600' : 'text-gray-800'}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {/* Gap table */}
      {report.gaps && Object.keys(report.gaps).length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-3">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-3 py-2 text-gray-500 font-medium">Degradation gap</th>
                <th className="text-right px-3 py-2 text-gray-500 font-medium">Δ Return</th>
                <th className="text-right px-3 py-2 text-gray-500 font-medium">Interpretation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {[
                { k: 'train_to_val',  label: 'Train → Validation' },
                { k: 'val_to_test',   label: 'Validation → Test'  },
                { k: 'train_to_test', label: 'Train → Test'        },
              ].filter(({ k }) => report.gaps[k] != null).map(({ k, label }) => {
                const gap = report.gaps[k]
                return (
                  <tr key={k} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-600">{label}</td>
                    <td className={`px-3 py-2 text-right ${gapColor(gap)}`}>{fmtPct(gap)}</td>
                    <td className="px-3 py-2 text-right text-gray-400">
                      {gap > 0.20 ? 'Large ⚠' : gap > 0.10 ? 'Moderate' : gap > 0 ? 'Normal' : 'Improving ✓'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-gray-600 italic">{report.verdict}</p>
    </div>
  )
}

// ── Return distribution + bootstrap CI panel ─────────────────────────────────
function ConfidencePanel({ metrics }) {
  if (!metrics) return null
  const { sharpe_ci, var_95, cvar_95, return_skew, return_kurtosis } = metrics
  if (!sharpe_ci && var_95 == null && return_skew == null) return null
  const skewDesc = return_skew == null ? '' :
    return_skew < -0.5 ? 'Left tail risk' :
    return_skew >  0.5 ? 'Right-skewed' : 'Near-symmetric'
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-sm font-medium text-gray-700">Return Distribution &amp; Confidence Intervals</h2>
        <span className="text-xs text-gray-400">1000-resample bootstrap · 95% CI</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {sharpe_ci && (
          <div className="bg-gray-50 border border-gray-100 rounded-lg p-3">
            <p className="text-xs text-gray-400 mb-1">Sharpe 95% CI</p>
            <p className="text-sm font-semibold text-gray-800">
              [{fmtRatio(sharpe_ci.lower)},  {fmtRatio(sharpe_ci.upper)}]
            </p>
            <p className="text-xs text-gray-400 mt-0.5">median {fmtRatio(sharpe_ci.median)}</p>
          </div>
        )}
        {var_95 != null && (
          <div className="bg-gray-50 border border-gray-100 rounded-lg p-3">
            <p className="text-xs text-gray-400 mb-1">Daily VaR 95%</p>
            <p className="text-sm font-semibold text-red-600">{fmtPct(var_95)}</p>
            <p className="text-xs text-gray-400 mt-0.5">loss on worst 5% of days</p>
          </div>
        )}
        {cvar_95 != null && (
          <div className="bg-gray-50 border border-gray-100 rounded-lg p-3">
            <p className="text-xs text-gray-400 mb-1">Daily CVaR 95%</p>
            <p className="text-sm font-semibold text-red-700">{fmtPct(cvar_95)}</p>
            <p className="text-xs text-gray-400 mt-0.5">avg loss in tail</p>
          </div>
        )}
        {return_skew != null && (
          <div className="bg-gray-50 border border-gray-100 rounded-lg p-3">
            <p className="text-xs text-gray-400 mb-1">Skew / Excess Kurt.</p>
            <p className="text-sm font-semibold text-gray-800">
              {fmtRatio(return_skew)} / {fmtRatio(return_kurtosis)}
            </p>
            <p className={`text-xs mt-0.5 ${return_skew < -0.5 ? 'text-amber-600' : 'text-gray-400'}`}>
              {skewDesc}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Regime analysis panel ─────────────────────────────────────────────────────
function RegimePanel({ regime }) {
  if (!regime?.regime_performance) return null
  const entries = Object.entries(regime.regime_performance)
  if (!entries.length) return null
  const regimeColors = {
    bull:            'text-green-700',
    bear:            'text-red-700',
    high_volatility: 'text-amber-700',
    low_volatility:  'text-blue-600',
  }
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-start justify-between">
        <div>
          <h2 className="text-sm font-medium text-gray-700">Regime Analysis</h2>
          <p className="text-xs text-gray-400 mt-0.5">20-day rolling vol + trend · performance per market regime</p>
        </div>
        {regime.trade_vol_correlation != null && (
          <div className="text-right shrink-0">
            <p className="text-xs text-gray-400">Trade–vol correlation</p>
            <p className={`text-sm font-semibold ${
              Math.abs(regime.trade_vol_correlation) > 0.3 ? 'text-amber-600' : 'text-green-600'
            }`}>
              {regime.trade_vol_correlation.toFixed(3)}
            </p>
          </div>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Regime', 'Days', '% Period', 'Daily Ret', 'Sharpe', 'Win Rate', 'Max DD'].map(h => (
                <th key={h} className={`px-4 py-2 text-xs text-gray-500 font-medium ${h === 'Regime' ? 'text-left' : 'text-right'}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {entries.map(([key, r]) => (
              <tr key={key} className="hover:bg-gray-50">
                <td className={`px-4 py-2.5 text-xs font-semibold ${regimeColors[key] || 'text-gray-700'}`}>
                  {r.label}
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{r.n_days}</td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-500">{r.pct_of_period}%</td>
                <td className={`px-4 py-2.5 text-right text-xs font-medium ${r.mean_daily_return >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {fmtPct(r.mean_daily_return)}
                </td>
                <td className={`px-4 py-2.5 text-right text-xs font-medium ${
                  r.sharpe_ann >= 1 ? 'text-green-600' : r.sharpe_ann >= 0 ? 'text-gray-700' : 'text-red-600'
                }`}>{fmtRatio(r.sharpe_ann)}</td>
                <td className="px-4 py-2.5 text-right text-xs text-gray-600">{fmtPct(r.win_rate)}</td>
                <td className={`px-4 py-2.5 text-right text-xs ${(r.max_drawdown ?? 0) > 0.2 ? 'text-red-600 font-medium' : 'text-gray-600'}`}>
                  {fmtPct(r.max_drawdown)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {regime.trade_vol_note && (
        <p className="px-4 py-2 border-t border-gray-100 text-xs text-gray-500 italic">
          {regime.trade_vol_note}
        </p>
      )}
    </div>
  )
}

// ── Statistical significance table ────────────────────────────────────────────
function SignificanceTable({ tests }) {
  if (!tests) return null
  const entries = Object.entries(tests).filter(([k]) => k !== '_summary')
  if (!entries.length) return null
  const summary = tests._summary
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-medium text-gray-700">Statistical Significance — Diebold-Mariano Test</h2>
        <p className="text-xs text-gray-400">
          H₀: RL and baseline have equal daily returns. Newey-West HAC SE (lags = ⌊n^⅓⌋). Two-tailed, α = 0.05.
          {summary && (
            <span className={`ml-2 font-medium ${
              summary.beats_significantly >= 2 ? 'text-green-600' : 'text-amber-600'
            }`}>{summary.overall}</span>
          )}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Baseline', 'DM stat', 'p-value', 'Sig.', 'Result'].map((h, i) => (
                <th key={h} className={`px-4 py-2 text-xs text-gray-500 font-medium ${i > 0 && i < 4 ? 'text-right' : i === 4 ? 'text-left pl-4' : 'text-left'}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {entries.map(([name, r]) => (
              <tr key={name} className="hover:bg-gray-50">
                <td className="px-4 py-2.5 text-xs text-gray-700 font-medium capitalize">
                  {name.replace(/_/g, ' ')}
                </td>
                <td className={`px-4 py-2.5 text-right text-xs font-semibold ${
                  r.dm_stat > 0 ? 'text-green-600' : 'text-red-600'
                }`}>{r.dm_stat?.toFixed(3)}</td>
                <td className={`px-4 py-2.5 text-right text-xs ${
                  r.p_value < 0.05 ? 'font-bold text-gray-900' : 'text-gray-500'
                }`}>{r.p_value?.toFixed(3)}</td>
                <td className="px-4 py-2.5 text-right">
                  <span className={`inline-flex px-1.5 py-0.5 text-xs rounded-full ${
                    r.significant && r.agent_beats  ? 'bg-green-100 text-green-700' :
                    r.significant && !r.agent_beats ? 'bg-red-100 text-red-700' :
                                                      'bg-gray-100 text-gray-500'
                  }`}>
                    {r.significant ? (r.agent_beats ? '✓ p<.05' : '✗ p<.05') : 'n.s.'}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-gray-500 max-w-xs">{r.interpretation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Methodology notes card ────────────────────────────────────────────────────
// ── Step log debug panel ───────────────────────────────────────────────────────
function StepLogPanel({ summary, backtestId }) {
  const [expanded, setExpanded] = React.useState(false)
  const [stepRows, setStepRows]   = React.useState(null)
  const [loadErr, setLoadErr]     = React.useState(null)
  const [loadPage, setLoadPage]   = React.useState(0)
  const [totalPages, setTotalPages] = React.useState(1)

  if (!summary) return null

  const fetchPage = (page) => {
    setLoadErr(null)
    fetch(`/api/backtest/${backtestId}/step-log?page=${page}&size=50`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => {
        setStepRows(d.rows || [])
        setTotalPages(Math.max(1, Math.ceil(d.total_steps / 50)))
        setLoadPage(page)
      })
      .catch(e => setLoadErr(String(e)))
  }

  const STA = ({ v, label }) => (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <div className="text-lg font-semibold text-gray-800">{v}</div>
      <div className="text-xs text-gray-400 mt-0.5">{label}</div>
    </div>
  )

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      {/* Header */}
      <button
        className="w-full flex items-center justify-between px-4 py-3 border-b border-gray-200 hover:bg-gray-50 transition-colors"
        onClick={() => {
          const next = !expanded
          setExpanded(next)
          if (next && !stepRows) fetchPage(0)
        }}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-700">Debug — Step Log</span>
          <span className="text-xs text-gray-400">
            {summary.total_logged_steps ?? summary.total_steps} steps · {summary.total_trades} trades
          </span>
        </div>
        <svg className={`w-4 h-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Summary stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <STA v={summary.total_steps} label="Total steps" />
            <STA v={summary.total_trades} label="Total trades" />
            <STA
              v={summary.avg_daily_reward != null ? (summary.avg_daily_reward * 100).toFixed(4) + '%' : '—'}
              label="Avg daily reward"
            />
            <STA
              v={summary.reward_std != null ? (summary.reward_std * 100).toFixed(4) + '%' : '—'}
              label="Reward σ"
            />
          </div>

          {/* Step table */}
          {loadErr && (
            <div className="text-xs text-red-500 bg-red-50 rounded p-2">{loadErr}</div>
          )}
          {stepRows && (
            <>
              {/* Schema version guard */}
              {stepRows.length > 0 && stepRows[0].v != null && stepRows[0].v !== 1 && (
                <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
                  ⚠ Step log schema v{stepRows[0].v} — this UI was built for v1.
                  Some columns may not display correctly.
                </div>
              )}
              <div className="max-h-72 overflow-y-auto text-xs">
                <table className="w-full">
                  <thead className="bg-gray-50 sticky top-0">
                    <tr>
                      {['Step','Date','Portfolio $','Cash $','Reward','Signals','Rolling Vol'].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-gray-500 font-medium whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {stepRows.map((s, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-3 py-1.5 text-gray-400">{s.step}</td>
                        <td className="px-3 py-1.5 text-gray-600 whitespace-nowrap">{s.date}</td>
                        <td className="px-3 py-1.5 font-medium text-gray-800">
                          ${s.portfolio_value?.toLocaleString(undefined, {maximumFractionDigits: 0})}
                        </td>
                        <td className="px-3 py-1.5 text-gray-600">
                          ${s.cash?.toLocaleString(undefined, {maximumFractionDigits: 0})}
                        </td>
                        <td className={`px-3 py-1.5 font-medium ${(s.reward ?? 0) >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                          {s.reward != null ? `${(s.reward * 100).toFixed(4)}%` : '—'}
                        </td>
                        <td className="px-3 py-1.5 text-gray-500 font-mono text-xs">
                          {s.signals
                            ? Object.entries(s.signals).filter(([,v]) => v !== 0)
                                .map(([k, v]) => `${k}:${v > 0 ? '↑' : '↓'}`).join(' ') || 'Hold'
                            : s.actions
                              ? Object.entries(s.actions).filter(([,v]) => Math.abs(v) > 0.01)
                                  .map(([k, v]) => `${k}:${v.toFixed(2)}`).join(' ') || 'Hold'
                              : '—'}
                        </td>
                        <td className="px-3 py-1.5 text-gray-400 font-mono text-xs">
                          {s.indicators
                            ? Object.entries(s.indicators).map(([tk, ind]) =>
                                `${tk}: vol=${(ind.rolling_vol_20d * 100).toFixed(2)}%`
                              ).join(' | ')
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-gray-400">Page {loadPage + 1} / {totalPages}</span>
                <div className="flex gap-2">
                  <button
                    disabled={loadPage === 0}
                    onClick={() => fetchPage(loadPage - 1)}
                    className="px-3 py-1 text-xs bg-gray-100 rounded disabled:opacity-40 hover:bg-gray-200"
                  >← Prev</button>
                  <button
                    disabled={loadPage >= totalPages - 1}
                    onClick={() => fetchPage(loadPage + 1)}
                    className="px-3 py-1 text-xs bg-gray-100 rounded disabled:opacity-40 hover:bg-gray-200"
                  >Next →</button>
                </div>
              </div>
            </>
          )}

          {/* Download link */}
          <div className="text-xs text-gray-400">
            Full JSONL log: <code className="bg-gray-100 rounded px-1 py-0.5">/api/backtest/{backtestId}/step-log?size=1000</code>
          </div>
        </div>
      )}
    </div>
  )
}


function MethodologyCard({ notes }) {
  if (!notes) return null
  const items = [
    { label: 'Slippage model',    value: notes.slippage_model },
    { label: 'Walk-forward type', value: notes.walk_forward_type },
    { label: 'Fill assumption',   value: notes.fill_assumption },
    { label: 'Baseline friction', value: notes.baseline_friction },
    { label: 'DM test setup',     value: notes.dm_test },
    { label: 'Regime window',     value: notes.regime_window },
  ]
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Methodology Notes</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-y-2 gap-x-6">
        {items.filter(i => i.value).map(({ label, value }) => (
          <div key={label} className="flex gap-2">
            <span className="text-xs text-gray-400 whitespace-nowrap">{label}:</span>
            <span className="text-xs text-gray-600">{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function BacktestPage() {
  const [searchParams] = useSearchParams()
  const [runs, setRuns]                   = useState([])
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get('run_id') || '')
  const [testStart, setTestStart]         = useState('2024-01-01')
  const [testEnd, setTestEnd]             = useState('2025-12-31')
  const [presets, setPresets]             = useState({})
  const [initialCapital, setInitialCapital] = useState('100000')
  // Friction controls
  const [commissionPct, setCommissionPct] = useState('0.1')   // shown as %
  const [slippagePct, setSlippagePct]     = useState('0.1')
  const [maxPosPct, setMaxPosPct]         = useState('20')    // shown as %
  const [cooldown, setCooldown]           = useState('5')
  const [showTrades, setShowTrades]       = useState(true)
  const [backtestId, setBacktestId]       = useState(null)
  const [backtestStatus, setBacktestStatus] = useState(null)
  const [result, setResult]               = useState(null)
  const [submitting, setSubmitting]       = useState(false)
  const [tradeFilter, setTradeFilter]     = useState('all')

  useEffect(() => {
    client.get('/api/train/runs')
      .then((r) => setRuns(r.data.filter((r) => r.status === 'done')))
    client.get('/api/research/walk-forward-presets')
      .then((r) => setPresets(r.data.presets || {}))
      .catch(() => {})
  }, [])

  const applyTestPreset = (key) => {
    const p = presets[key]?.test
    if (!p) return
    setTestStart(p.start)
    setTestEnd(p.end)
    toast.success('Test window updated')
  }

  // Poll
  useEffect(() => {
    if (!backtestId || backtestStatus === 'done' || backtestStatus === 'failed') return
    const timer = setInterval(async () => {
      const r = await client.get(`/api/backtest/${backtestId}`)
      setBacktestStatus(r.data.status)
      if (r.data.status === 'done') { clearInterval(timer); setResult(r.data); toast.success('Backtest complete!') }
      if (r.data.status === 'failed') { clearInterval(timer); toast.error(r.data.error || 'Backtest failed') }
    }, 2000)
    return () => clearInterval(timer)
  }, [backtestId, backtestStatus])

  const handleSubmit = async () => {
    if (!selectedRunId) return toast.error('Select a training run')
    const capital = parseFloat(initialCapital.replace(/,/g, ''))
    if (isNaN(capital) || capital <= 0) return toast.error('Enter a valid capital amount')
    setResult(null)
    setSubmitting(true)
    try {
      const r = await client.post('/api/backtest', {
        run_id: selectedRunId,
        test_start: testStart,
        test_end: testEnd,
        initial_capital: capital,
        commission_pct: parseFloat(commissionPct) / 100,
        slippage_pct:   parseFloat(slippagePct)   / 100,
        max_position_pct: parseFloat(maxPosPct)   / 100,
        cooldown_days:  parseInt(cooldown, 10),
      })
      setBacktestId(r.data.backtest_id)
      setBacktestStatus('pending')
    } finally {
      setSubmitting(false)
    }
  }

  const selectedRun = runs.find((r) => r.run_id === selectedRunId)
  const loading     = (backtestStatus === 'running' || backtestStatus === 'pending') && !result
  const curveData   = result ? [{
    label: selectedRun?.algorithm?.toUpperCase() || 'Agent',
    accountValue: result.account_value,
    dates: result.dates,
    trades: result.trades,
  }] : []

  const filteredTrades = (result?.trades ?? []).filter((t) =>
    tradeFilter === 'all' ? true : t.action === tradeFilter
  )

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Backtest</h1>
      <p className="text-sm text-gray-500 mb-6">
        Evaluate a trained agent on historical data with full trading friction and benchmarks
      </p>

      {/* ── Config form ── */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 max-w-4xl mb-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Training run</label>
            <select
              value={selectedRunId}
              onChange={(e) => setSelectedRunId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Select a completed run...</option>
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.algorithm.toUpperCase()} — {r.run_id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>

          <div className="sm:col-span-2">
            <p className="text-xs text-gray-500 mb-2">Walk-forward test window (out-of-sample)</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(presets).map(([key, p]) => (
                <button key={key} type="button" onClick={() => applyTestPreset(key)}
                  className="px-3 py-1 text-xs rounded-full bg-gray-100 hover:bg-gray-200 text-gray-700">
                  {p.label?.split('(')[1]?.replace(')', '') || key}
                </button>
              ))}
              <button type="button" onClick={() => { setTestStart('2024-01-01'); setTestEnd('2025-12-31') }}
                className="px-3 py-1 text-xs rounded-full bg-blue-50 text-blue-700">2024–2025</button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Test start</label>
            <input type="date" value={testStart} onChange={(e) => setTestStart(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Test end</label>
            <input type="date" value={testEnd} onChange={(e) => setTestEnd(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Starting capital ($)</label>
            <input type="text" value={initialCapital} onChange={(e) => setInitialCapital(e.target.value)}
              placeholder="e.g. 100000"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none" />
            <p className="text-xs text-gray-400 mt-1">
              {[10000, 50000, 100000, 1000000].map((v) => (
                <button key={v} onClick={() => setInitialCapital(String(v))}
                  className="text-blue-600 hover:underline mr-2">${v.toLocaleString()}</button>
              ))}
            </p>
          </div>

          {/* Friction controls */}
          <div className="sm:col-span-2">
            <p className="text-xs font-medium text-gray-600 mb-2 mt-1 border-t border-gray-100 pt-3">
              Trading friction (applied to every trade)
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Commission %', value: commissionPct, set: setCommissionPct, hint: '0.1% typical retail' },
                { label: 'Slippage %',   value: slippagePct,   set: setSlippagePct,   hint: '0.1% mid-cap stocks' },
                { label: 'Max position %', value: maxPosPct,   set: setMaxPosPct,     hint: '20% per stock max' },
                { label: 'Cooldown days', value: cooldown,     set: setCooldown,      hint: 'Min days btw trades' },
              ].map(({ label, value, set, hint }) => (
                <div key={label}>
                  <label className="block text-xs text-gray-500 mb-1">{label}</label>
                  <input type="number" value={value} onChange={(e) => set(e.target.value)} step="0.05" min="0"
                    className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:outline-none" />
                  <p className="text-xs text-gray-400 mt-0.5">{hint}</p>
                </div>
              ))}
            </div>
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1 mt-2 inline-block">
              Round-trip cost ≈ {((parseFloat(commissionPct || 0) + parseFloat(slippagePct || 0)) * 2).toFixed(2)}%
              per complete trade
            </p>
          </div>

          <div className="flex items-center gap-2">
            <input type="checkbox" id="showTrades" checked={showTrades}
              onChange={(e) => setShowTrades(e.target.checked)}
              className="accent-blue-600 w-4 h-4" />
            <label htmlFor="showTrades" className="text-sm text-gray-700 cursor-pointer">
              Show buy/sell markers on chart
            </label>
          </div>
        </div>

        <div className="flex items-center gap-4 mt-5">
          <button onClick={handleSubmit} disabled={submitting}
            className="px-5 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors">
            {submitting ? 'Submitting...' : 'Run backtest'}
          </button>
          {backtestStatus && <JobStatusBadge status={backtestStatus} />}
        </div>
      </div>

      {/* ── Loading skeletons ── */}
      {loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[0,1,2,3].map(i => <CardSkeleton key={i} />)}</div>
          <div className="bg-white border border-gray-200 rounded-xl p-6"><ChartSkeleton /></div>
        </div>
      )}

      {/* ── Results ── */}
      {result && (
        <div className="space-y-6">

          {/* Friction applied notice */}
          {result.transaction_costs && (
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm">
              <p className="font-medium text-blue-800 mb-1">Trading friction applied</p>
              <p className="text-blue-700 text-xs">{result.transaction_costs.note}</p>
              <p className="text-blue-600 text-xs mt-1">
                Max position: {((result.transaction_costs.max_position_pct ?? 0.2) * 100).toFixed(0)}% per stock
                &nbsp;·&nbsp; Cooldown: {result.transaction_costs.cooldown_days ?? 1} day(s) between trades
              </p>
            </div>
          )}

          {result.data_quality && !result.data_quality.live_prices && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-900">
              <p className="font-medium mb-1">Price data</p>
              <p>{result.data_quality.message}</p>
            </div>
          )}

          {/* Capital summary */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">Starting capital</p>
              <p className="text-xl font-semibold text-gray-900">{fmtCurrency(result.initial_capital)}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">Final value</p>
              <p className="text-xl font-semibold text-gray-900">{fmtCurrency(result.metrics?.final_value)}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1">P&amp;L</p>
              <p className={`text-xl font-semibold ${
                (result.metrics?.final_value ?? 0) - (result.initial_capital ?? 0) >= 0
                  ? 'text-green-600' : 'text-red-600'
              }`}>
                {fmtCurrency((result.metrics?.final_value ?? 0) - (result.initial_capital ?? 0))}
              </p>
            </div>
          </div>

          {/* Full metrics grid (Sharpe, Sortino, Calmar, ...) */}
          <MetricsCard metrics={result.metrics} />

          {/* Strategy benchmarks */}
          <BaselinesTable agentMetrics={result.metrics} baselines={result.baselines} />

          {/* Equity curve */}
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium text-gray-700">Equity Curve</h2>
              <span className="text-xs text-gray-400">Normalized from starting capital</span>
            </div>
            <EquityCurveChart curves={curveData} benchmark={result.benchmark} showTrades={showTrades} />
          </div>

          {/* Walk-forward sub-periods */}
          <WalkForwardTable periods={result.walk_forward_periods} />
          <WalkForwardSummary summary={result.walk_forward_summary} />

          {/* Stress tests */}
          <StressTestsTable base={result.metrics} stress={result.stress_tests} />

          {/* RL sanity checks */}
          <SanityPanel sanity={result.rl_sanity} />

          {/* Overfitting report */}
          <OverfittingReport report={result.overfitting_report} />

          {/* Return distribution + CI */}
          <ConfidencePanel metrics={result.metrics} />

          {/* Regime analysis */}
          <RegimePanel regime={result.regime_analysis} />

          {/* Statistical significance */}
          <SignificanceTable tests={result.significance_tests} />

          {/* Methodology notes */}
          <MethodologyCard notes={result.methodology_notes} />

          {/* Debug — Step log */}
          <StepLogPanel summary={result.step_log_summary} backtestId={backtestId} />

          {/* Trade log */}
          {result.trades?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
                <h2 className="text-sm font-medium text-gray-700">
                  Trade log
                  <span className="ml-2 text-xs font-normal text-gray-400">{result.trades.length} trades</span>
                </h2>
                <div className="flex gap-2">
                  {['all', 'buy', 'sell'].map((f) => (
                    <button key={f} onClick={() => setTradeFilter(f)}
                      className={`px-3 py-1 rounded-full text-xs transition-colors ${
                        tradeFilter === f ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}>
                      {f.charAt(0).toUpperCase() + f.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="max-h-72 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 sticky top-0 border-b border-gray-200">
                    <tr>
                      <th className="text-left px-4 py-2 text-gray-500 font-medium text-xs">Date</th>
                      <th className="text-left px-4 py-2 text-gray-500 font-medium text-xs">Ticker</th>
                      <th className="text-left px-4 py-2 text-gray-500 font-medium text-xs">Action</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Shares</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Exec Price</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Eff. Price</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Live Ref</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Slip %</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Friction $</th>
                      <th className="text-right px-4 py-2 text-gray-500 font-medium text-xs">Notional</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {filteredTrades.map((t, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-4 py-2 text-gray-500 text-xs">{t.date}</td>
                        <td className="px-4 py-2 font-semibold text-gray-900 text-xs">{t.ticker}</td>
                        <td className="px-4 py-2">
                          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${actionBadge[t.action]}`}>
                            {t.action}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right text-gray-600 text-xs">{t.shares}</td>
                        {/* Exec Price = simulation price before friction */}
                        <td className="px-4 py-2 text-right text-gray-700 text-xs font-medium">
                          ${t.price?.toFixed(2) ?? '—'}
                        </td>
                        {/* Eff. Price = exec price + commission + slippage */}
                        <td className="px-4 py-2 text-right text-xs text-indigo-600 font-medium">
                          {t.effective_price ? `$${t.effective_price.toFixed(2)}` : '—'}
                        </td>
                        {/* Live Ref = Yahoo real-world price for reference only (not used in simulation) */}
                        <td className="px-4 py-2 text-right text-xs text-gray-400">
                          {t.live_price ? `$${t.live_price.toFixed(2)}` : '—'}
                        </td>
                        <td className="px-4 py-2 text-right text-xs text-gray-500">
                          {t.slippage_pct != null ? `${t.slippage_pct.toFixed(3)}%` : '—'}
                        </td>
                        <td className="px-4 py-2 text-right text-xs text-amber-600">
                          {t.friction_cost != null ? `$${t.friction_cost.toFixed(2)}` : '—'}
                        </td>
                        <td className="px-4 py-2 text-right text-gray-600 text-xs">
                          {t.price != null && t.shares != null ? `$${(t.shares * t.price).toFixed(2)}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  )
}
