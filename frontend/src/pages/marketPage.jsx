import { useState, useEffect } from 'react'
import client from '../api/client'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

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

  useEffect(() => {
    setLoadingOverview(true)
    client.get('/api/market/overview', { params: { market } })
      .then((r) => { setOverview(r.data); if (r.data.length > 0) selectTicker(r.data[0].ticker) })
      .catch(() => setOverview([]))
      .finally(() => setLoadingOverview(false))
  }, [market])

  const selectTicker = (ticker) => {
    setSelectedTicker(ticker)
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
