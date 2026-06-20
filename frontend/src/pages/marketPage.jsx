import { useState, useEffect } from 'react'
import client from '../api/client'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
         ComposedChart, Area, ReferenceLine } from 'recharts'

const changeStyle = (pct) =>
  pct > 0 ? 'text-emerald-600' : pct < 0 ? 'text-red-500' : 'text-gray-500'

export default function MarketPage() {
  const [market, setMarket] = useState('us')
  const [overview, setOverview] = useState([])
  const [candles, setCandles] = useState([])
  const [selectedTicker, setSelectedTicker] = useState(null)
  const [quote, setQuote] = useState(null)
  const [news, setNews] = useState(null)
  const [loadingOverview, setLoadingOverview] = useState(true)
  const [loadingCandles, setLoadingCandles] = useState(false)
  const dataSource = quote?.source || candles[0]?.source || overview[0]?.source

  // ── FinCast forecast ───────────────────────────────────────────────────────
  const [fcStatus, setFcStatus] = useState(null)     // {ready: bool}
  const [fcLoading, setFcLoading] = useState(false)
  const [fcResult, setFcResult] = useState(null)
  const [fcError, setFcError] = useState(null)

  useEffect(() => {
    client.get('/api/fincast/status').then(r => setFcStatus(r.data)).catch(() => setFcStatus({ ready: false }))
  }, [])

  const runForecast = async () => {
    if (!selectedTicker) return
    setFcLoading(true); setFcResult(null); setFcError(null)
    try {
      const post = await client.post('/api/fincast/forecast', null,
        { params: { ticker: selectedTicker, market } })
      if (post.data.cached && post.data.result) { setFcResult(post.data.result); return }
      const jobId = post.data.job_id
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 3000))
        const { data } = await client.get(`/api/fincast/forecast/${jobId}`)
        if (data.status === 'done') { setFcResult(data.result); return }
        if (data.status === 'failed') { setFcError(data.error || 'Forecast failed'); return }
      }
      setFcError('Timed out waiting for forecast')
    } catch (e) {
      setFcError(e.response?.data?.detail || 'Forecast request failed')
    } finally { setFcLoading(false) }
  }

  // Build a combined series: recent 5-min actual closes + forecast cone appended.
  // Use the 5-min history the model actually consumed (fcResult.history) so the
  // actual and forecast portions share the same time scale.
  const forecastChartData = (() => {
    if (!fcResult?.ok) return []
    const histCloses = fcResult.history?.length ? fcResult.history : candles.slice(-40).map(c => c.close)
    const hist = histCloses.map((close, i) => ({ i, close }))
    const start = hist.length
    const fc = fcResult.mean.map((m, j) => ({
      i: start + j, mean: m, band: [fcResult.q10[j], fcResult.q90[j]],
    }))
    // bridge: anchor the forecast to the last actual close
    if (hist.length) fc.unshift({ i: start - 1, mean: hist[hist.length - 1].close, band: [hist[hist.length - 1].close, hist[hist.length - 1].close] })
    return [...hist, ...fc]
  })()

  useEffect(() => {
    setLoadingOverview(true)
    client.get('/api/market/overview', { params: { market } })
      .then((r) => { setOverview(r.data); if (r.data.length > 0) selectTicker(r.data[0].ticker) })
      .catch(() => setOverview([]))
      .finally(() => setLoadingOverview(false))
  }, [market])

  const selectTicker = (ticker) => {
    setSelectedTicker(ticker)
    setFcResult(null); setFcError(null)
    setLoadingCandles(true)
    Promise.allSettled([
      client.get(`/api/market/candles/${ticker}`, { params: { period: '3mo', interval: '1d' } }),
      client.get(`/api/market/quote/${ticker}`),
      client.get(`/api/market/news/${ticker}`),
    ])
      .then(([c, q, n]) => {
        if (c.status === 'fulfilled') setCandles(c.value.data)
        if (q.status === 'fulfilled') setQuote(q.value.data)
        if (n.status === 'fulfilled') setNews(n.value.data)
      })
      .finally(() => setLoadingCandles(false))
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Market Overview</h1>
          <p className="text-sm text-gray-500 mt-1">
            {dataSource === 'live'
              ? 'Live prices from Yahoo Finance'
              : dataSource === 'dataset'
                ? 'Training dataset prices (not live market)'
                : dataSource === 'synthetic' || dataSource === 'demo'
                  ? 'Demo / placeholder data'
                  : 'Market data'}
          </p>
        </div>
        <div className="flex gap-1">
          {['us', 'egx'].map((m) => (
            <button key={m} onClick={() => setMarket(m)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                market === m ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {m === 'us' ? 'US Market' : 'EGX'}
            </button>
          ))}
        </div>
      </div>

      {dataSource && dataSource !== 'live' && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
          {dataSource === 'dataset'
            ? 'Showing ML training CSV prices — these are not live market quotes.'
            : 'Showing demo/placeholder data — not real market prices.'}
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Ticker list */}
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-sm font-medium text-gray-700">Tickers</h2>
          </div>
          {loadingOverview ? (
            <div className="p-4 text-center text-sm text-gray-400">Loading…</div>
          ) : (
            <div className="divide-y divide-gray-50">
              {overview.map((item) => (
                <button
                  key={item.ticker}
                  onClick={() => selectTicker(item.ticker)}
                  className={`w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors ${
                    selectedTicker === item.ticker ? 'bg-gray-50' : ''
                  }`}
                >
                  <div>
                    <p className="text-sm font-medium text-gray-900">{item.ticker}</p>
                    <p className="text-xs text-gray-400">${item.price?.toLocaleString()}</p>
                  </div>
                  <span className={`text-sm font-medium ${changeStyle(item.change_pct)}`}>
                    {item.change_pct > 0 ? '+' : ''}{item.change_pct}%
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Chart + detail */}
        <div className="lg:col-span-2 space-y-4">
          {/* Quote card */}
          {quote && (
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{quote.ticker}</h3>
                  <p className="text-sm text-gray-400">{quote.company}</p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold text-gray-900">${quote.price?.toLocaleString()}</p>
                  <p className={`text-sm font-medium ${changeStyle(quote.change_pct)}`}>
                    {quote.change_pct > 0 ? '+' : ''}{quote.change_pct}%
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-gray-100">
                {quote.sector && <div><p className="text-xs text-gray-400">Sector</p><p className="text-xs font-medium text-gray-700 truncate">{quote.sector}</p></div>}
                {quote['52w_high'] && <div><p className="text-xs text-gray-400">52W High</p><p className="text-xs font-medium text-gray-700">${quote['52w_high']?.toFixed(2)}</p></div>}
                {quote['52w_low'] && <div><p className="text-xs text-gray-400">52W Low</p><p className="text-xs font-medium text-gray-700">${quote['52w_low']?.toFixed(2)}</p></div>}
              </div>
            </div>
          )}

          {/* Price chart */}
          <div className="bg-white border border-gray-200 rounded-xl p-4">
            <h3 className="text-sm font-medium text-gray-700 mb-3">3-Month Price</h3>
            {loadingCandles ? (
              <div className="h-40 flex items-center justify-center text-sm text-gray-400">Loading…</div>
            ) : candles.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={candles}>
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#9ca3af' }}
                    tickFormatter={(d) => d?.slice(5)} interval={Math.floor(candles.length / 5)} />
                  <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} domain={['auto', 'auto']} width={60} />
                  <Tooltip
                    contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                    labelStyle={{ color: '#9ca3af', fontSize: 11 }}
                    itemStyle={{ color: '#10b981', fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="close" stroke="#10b981" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-gray-400 text-center py-8">No data</p>
            )}
          </div>

          {/* FinCast forecast */}
          {fcStatus?.ready && (
            <div className="bg-white border border-violet-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-gray-700">FinCast Forecast</h3>
                  <span className="text-[10px] text-violet-700 bg-violet-50 border border-violet-200 px-1.5 py-0.5 rounded">
                    {fcResult?.horizon || 60}-step · {fcStatus.model || 'fincast'}
                  </span>
                </div>
                <button onClick={runForecast} disabled={fcLoading || !selectedTicker}
                  className="px-3 py-1.5 text-xs rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50">
                  {fcLoading ? 'Forecasting…' : `Forecast ${selectedTicker || ''}`}
                </button>
              </div>
              {fcError && <p className="text-xs text-red-600 mb-2">{fcError}</p>}
              {fcResult?.ok ? (
                <>
                  <ResponsiveContainer width="100%" height={200}>
                    <ComposedChart data={forecastChartData}>
                      <XAxis dataKey="i" tick={{ fontSize: 10, fill: '#9ca3af' }} />
                      <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} domain={['auto', 'auto']} width={55} />
                      <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                        labelStyle={{ color: '#9ca3af', fontSize: 11 }} />
                      {fcResult?.history?.length &&
                        <ReferenceLine x={fcResult.history.length - 1} stroke="#a78bfa" strokeDasharray="3 3" />}
                      <Area dataKey="band" stroke="none" fill="#8b5cf6" fillOpacity={0.15} />
                      <Line dataKey="close" stroke="#10b981" strokeWidth={2} dot={false} name="actual" />
                      <Line dataKey="mean" stroke="#8b5cf6" strokeWidth={2} dot={false} name="forecast" />
                    </ComposedChart>
                  </ResponsiveContainer>
                  <p className="text-[11px] text-gray-400 mt-1">
                    Green = recent actual close · purple = forecast mean · band = q10–q90.
                    Last ${fcResult.last_close} → mean ${fcResult.mean[fcResult.mean.length - 1]} in {fcResult.horizon} steps.
                  </p>
                </>
              ) : !fcLoading && (
                <p className="text-xs text-gray-400">Click “Forecast” to run the finetuned FinCast model (first run loads the model, ~a few seconds).</p>
              )}
            </div>
          )}

          {/* News sentiment */}
          {news && (
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-gray-700">News Sentiment</h3>
                  {news.source === 'demo' && (
                    <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded">demo</span>
                  )}
                </div>
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  news.label === 'positive' ? 'bg-emerald-100 text-emerald-700' :
                  news.label === 'negative' ? 'bg-red-100 text-red-700' :
                  'bg-gray-100 text-gray-500'
                }`}>
                  {news.label} {news.score != null ? `(${news.score > 0 ? '+' : ''}${news.score?.toFixed(2)})` : ''}
                </span>
              </div>
              {news.headlines?.length > 0 ? (
                <ul className="space-y-1.5">
                  {news.headlines.slice(0, 4).map((h, i) => (
                    <li key={i} className="text-xs text-gray-500 leading-relaxed">{h}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-gray-400">No recent headlines</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
