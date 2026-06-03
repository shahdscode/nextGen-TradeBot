import { useState, useEffect, useCallback } from 'react'
import {
  View, Text, FlatList, TouchableOpacity, ScrollView,
  RefreshControl, StyleSheet, ActivityIndicator, Dimensions,
} from 'react-native'
import CandleChart from '../components/candleChart'
import DataSourceBadge from '../components/dataSourceBadge'
import client from '../api/client'
import {
  filterOverview,
  acceptMarketQuote,
  acceptMarketCandles,
  acceptMarketNews,
  cleanHeadline,
  isLiveMarketSource,
} from '../utils/marketData'
import ConnectionBanner from '../components/connectionBanner'
import { COLORS, RADIUS } from '../constants/theme'

const screenW = Dimensions.get('window').width

const changeColor = (pct) => (pct > 0 ? COLORS.green : pct < 0 ? COLORS.red : COLORS.textMuted)

// Selectable chart durations (default 3M). value = yfinance period.
const PERIODS = [
  { label: '1M', value: '1mo' },
  { label: '3M', value: '3mo' },
  { label: '6M', value: '6mo' },
  { label: '1Y', value: '1y' },
  { label: '2Y', value: '2y' },
  { label: '5Y', value: '5y' },
]
const PERIOD_LABEL = { '1mo': '1-Month', '3mo': '3-Month', '6mo': '6-Month',
  '1y': '1-Year', '2y': '2-Year', '5y': '5-Year' }

export default function MarketScreen() {
  const [market, setMarket] = useState('us')
  const [overview, setOverview] = useState([])
  const [selected, setSelected] = useState(null)
  const [period, setPeriod] = useState('3mo')
  const [candles, setCandles] = useState([])
  const [quote, setQuote] = useState(null)
  const [news, setNews] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [chartLoading, setChartLoading] = useState(false)
  const [dataStatus, setDataStatus] = useState(null)
  const [dataError, setDataError] = useState(null)
  const priceSource = quote?.source || candles[0]?.source || overview[0]?.source

  const fetchOverview = useCallback(async () => {
    setDataError(null)
    try {
      const statusRes = await client.get('/api/market/data-status').catch(() => null)
      const allowDemo = statusRes?.data?.demo_fallback_enabled === true
      if (statusRes?.data) setDataStatus(statusRes.data)

      const { data } = await client.get('/api/market/overview', { params: { market } })
      const live = filterOverview(data, { allowDemo })
      setOverview(live)
      if (live.length > 0) {
        selectTicker(live[0].ticker)
      } else {
        setSelected(null)
        setQuote(null)
        setCandles([])
        setNews(null)
        setDataError(
          market === 'egx'
            ? 'No live EGX data from Yahoo. Switch to US market or add a regional data provider.'
            : 'Live market data unavailable. Check API connection and refresh.',
        )
      }
    } catch {
      setOverview([])
      setDataError('Could not load market data from the API.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [market])

  useEffect(() => { setLoading(true); fetchOverview() }, [fetchOverview])

  // Fetch OHLC candles for a ticker over a given period (interval auto-scales
  // for long ranges so charts stay readable). Preserves full OHLC for candlesticks.
  const fetchCandles = useCallback(async (ticker, p) => {
    setChartLoading(true)
    const allowDemo = dataStatus?.demo_fallback_enabled === true
    const interval = (p === '2y' || p === '5y') ? '1wk' : '1d'
    try {
      const c = await client.get(`/api/market/candles/${ticker}`, {
        params: { period: p, interval },
      })
      const rows = acceptMarketCandles(c.data || [], { allowDemo })
      setCandles(rows.map((d) => ({
        date: d.date?.slice(0, 10),
        open: d.open, high: d.high, low: d.low, close: d.close,
        source: d.source,
      })))
    } catch {
      setCandles([])
    } finally {
      setChartLoading(false)
    }
  }, [dataStatus])

  const selectTicker = async (ticker) => {
    setSelected(ticker)
    const allowDemo = dataStatus?.demo_fallback_enabled === true
    const marketOpts = { allowDemo }
    fetchCandles(ticker, period)
    const [q, n] = await Promise.allSettled([
      client.get(`/api/market/quote/${ticker}`),
      client.get(`/api/market/news/${ticker}`),
    ])
    if (q.status === 'fulfilled') setQuote(acceptMarketQuote(q.value.data, marketOpts))
    else setQuote(null)
    if (n.status === 'fulfilled') {
      const liveNews = acceptMarketNews(n.value.data, marketOpts)
      if (liveNews?.headlines) liveNews.headlines = liveNews.headlines.map(cleanHeadline)
      setNews(liveNews)
    } else setNews(null)
  }

  // Re-fetch candles when the user changes the duration
  const changePeriod = (p) => {
    setPeriod(p)
    if (selected) fetchCandles(selected, p)
  }

  const onRefresh = () => { setRefreshing(true); fetchOverview(); if (selected) fetchCandles(selected, period) }

  const chartW = screenW - 40

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Market</Text>
          {dataStatus && !dataStatus.live_market_ok && (
            <Text style={styles.statusWarn} numberOfLines={2}>{dataStatus.message}</Text>
          )}
        </View>
        <DataSourceBadge source={priceSource} />
        <View style={styles.tabs}>
          {['us', 'egx'].map((m) => (
            <TouchableOpacity key={m} onPress={() => setMarket(m)} style={[styles.tab, market === m && styles.tabActive]}>
              <Text style={[styles.tabText, market === m && styles.tabTextActive]}>
                {m === 'us' ? 'US' : 'EGX'}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      <ScrollView
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={COLORS.teal} />}
        showsVerticalScrollIndicator={false}
      >
        <ConnectionBanner marketStatus={dataStatus} error={dataError} />

        {/* Quote card */}
        {quote && (
          <View style={styles.quoteCard}>
            <View style={styles.quoteTop}>
              <View>
                <Text style={styles.quoteTicker}>{quote.ticker}</Text>
                {quote.company ? <Text style={styles.quoteCompany} numberOfLines={1}>{quote.company}</Text> : null}
              </View>
              <View style={styles.quoteRight}>
                <Text style={styles.quotePrice}>${quote.price?.toLocaleString()}</Text>
                <Text style={[styles.quoteChange, { color: changeColor(quote.change_pct) }]}>
                  {quote.change_pct > 0 ? '+' : ''}{quote.change_pct}%
                </Text>
              </View>
            </View>
            {quote['52w_high'] && (
              <View style={styles.quoteStats}>
                {[
                  ['52W High', `$${quote['52w_high']?.toFixed(2)}`],
                  ['52W Low', `$${quote['52w_low']?.toFixed(2)}`],
                  ['Sector', quote.sector || '—'],
                ].map(([l, v]) => (
                  <View key={l} style={styles.statItem}>
                    <Text style={styles.statLabel}>{l}</Text>
                    <Text style={styles.statValue} numberOfLines={1}>{v}</Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        )}

        {/* Chart */}
        <View style={styles.chartCard}>
          <View style={styles.chartHead}>
            <Text style={styles.chartTitle}>
              {selected ? `${selected} · ${PERIOD_LABEL[period]}` : `${PERIOD_LABEL[period]} Candles`}
            </Text>
          </View>

          {/* Duration selector */}
          <View style={styles.periodRow}>
            {PERIODS.map((p) => (
              <TouchableOpacity
                key={p.value}
                onPress={() => changePeriod(p.value)}
                style={[styles.periodChip, period === p.value && styles.periodChipActive]}
              >
                <Text style={[styles.periodChipText, period === p.value && styles.periodChipTextActive]}>
                  {p.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {chartLoading ? (
            <ActivityIndicator color={COLORS.teal} style={{ height: 220 }} />
          ) : candles.length > 1 && isLiveMarketSource(candles[0]?.source) ? (
            <CandleChart data={candles} width={chartW} height={220} />
          ) : (
            <View style={styles.noChart}>
              <Text style={styles.noChartText}>
                {selected ? 'No live price data for this range' : 'Select a ticker below to view its candles'}
              </Text>
            </View>
          )}
        </View>

        {/* Ticker list */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>All Tickers</Text>
          {loading ? (
            <ActivityIndicator color={COLORS.teal} />
          ) : overview.length === 0 ? (
            <Text style={styles.noNews}>No live tickers to display</Text>
          ) : (
            overview.map((item) => (
              <TouchableOpacity key={item.ticker} onPress={() => selectTicker(item.ticker)}
                style={[styles.tickerRow, selected === item.ticker && styles.tickerRowActive]}>
                <View>
                  <Text style={styles.tickerSymbol}>{item.ticker}</Text>
                  <Text style={styles.tickerPrice}>${item.price?.toLocaleString()}</Text>
                </View>
                <Text style={[styles.tickerChange, { color: changeColor(item.change_pct) }]}>
                  {item.change_pct > 0 ? '+' : ''}{item.change_pct}%
                </Text>
              </TouchableOpacity>
            ))
          )}
        </View>

        {/* News sentiment */}
        {news && isLiveMarketSource(news.source) && (
          <View style={[styles.section, { marginBottom: 40 }]}>
            <View style={styles.newsHeader}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={styles.sectionTitle}>News Sentiment</Text>
                <DataSourceBadge source={news.source} />
              </View>
              <View style={[styles.sentimentBadge, {
                backgroundColor: news.label === 'positive' ? COLORS.greenBg : news.label === 'negative' ? COLORS.redBg : 'rgba(255,255,255,0.05)',
              }]}>
                <Text style={{ fontSize: 11, fontWeight: '600', color: news.label === 'positive' ? COLORS.green : news.label === 'negative' ? COLORS.red : COLORS.textMuted }}>
                  {news.label} {news.score != null ? `(${news.score > 0 ? '+' : ''}${news.score?.toFixed(2)})` : ''}
                </Text>
              </View>
            </View>
            {(news.headlines || []).slice(0, 4).map((h, i) => (
              <Text key={i} style={styles.headline} numberOfLines={2}>{h}</Text>
            ))}
            {(!news.headlines || news.headlines.length === 0) && (
              <Text style={styles.noNews}>No recent headlines</Text>
            )}
          </View>
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
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: COLORS.cardBorder,
  },
  title: { fontSize: 20, fontWeight: '800', color: COLORS.textPrimary },
  statusWarn: { fontSize: 11, color: COLORS.amber, marginTop: 4 },
  errorBox: {
    marginHorizontal: 20,
    marginTop: 12,
    padding: 12,
    backgroundColor: COLORS.redBg,
    borderRadius: RADIUS.md,
    borderWidth: 1,
    borderColor: COLORS.red + '40',
  },
  errorText: { fontSize: 12, color: COLORS.red, lineHeight: 18 },
  tabs: { flexDirection: 'row', gap: 6 },
  tab: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: RADIUS.full, backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.cardBorder },
  tabActive: { backgroundColor: COLORS.teal, borderColor: COLORS.teal },
  tabText: { fontSize: 12, color: COLORS.textMuted, fontWeight: '500' },
  tabTextActive: { color: '#fff', fontWeight: '700' },
  quoteCard: { margin: 20, marginBottom: 0, backgroundColor: COLORS.card, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.cardBorder, padding: 16 },
  quoteTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  quoteTicker: { fontSize: 18, fontWeight: '800', color: COLORS.textPrimary },
  quoteCompany: { fontSize: 12, color: COLORS.textMuted, marginTop: 2, maxWidth: 180 },
  quoteRight: { alignItems: 'flex-end' },
  quotePrice: { fontSize: 22, fontWeight: '800', color: COLORS.textPrimary },
  quoteChange: { fontSize: 14, fontWeight: '600', marginTop: 2 },
  quoteStats: { flexDirection: 'row', marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.06)' },
  statItem: { flex: 1, alignItems: 'center' },
  statLabel: { fontSize: 10, color: COLORS.textMuted, marginBottom: 2, textTransform: 'uppercase' },
  statValue: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '500' },
  chartCard: { margin: 20, marginBottom: 8, backgroundColor: COLORS.card, borderRadius: RADIUS.lg, borderWidth: 1, borderColor: COLORS.cardBorder, padding: 16 },
  chartHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  chartTitle: { fontSize: 13, color: COLORS.textPrimary, fontWeight: '600' },
  periodRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10, marginBottom: 12 },
  periodChip: {
    paddingHorizontal: 12, paddingVertical: 5, borderRadius: RADIUS.full,
    borderWidth: 1, borderColor: COLORS.cardBorder, backgroundColor: COLORS.bg,
  },
  periodChipActive: { backgroundColor: COLORS.teal, borderColor: COLORS.teal },
  periodChipText: { fontSize: 12, color: COLORS.textSecondary, fontWeight: '600' },
  periodChipTextActive: { color: '#fff' },
  noChart: { height: 160, alignItems: 'center', justifyContent: 'center' },
  noChartText: { color: COLORS.textMuted },
  section: { paddingHorizontal: 20, marginTop: 12 },
  sectionTitle: { fontSize: 12, color: COLORS.textMuted, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 },
  tickerRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.04)' },
  tickerRowActive: { opacity: 0.7 },
  tickerSymbol: { fontSize: 14, fontWeight: '700', color: COLORS.textPrimary },
  tickerPrice: { fontSize: 12, color: COLORS.textMuted, marginTop: 2 },
  tickerChange: { fontSize: 14, fontWeight: '600' },
  newsHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  sentimentBadge: { borderRadius: RADIUS.full, paddingHorizontal: 10, paddingVertical: 4 },
  headline: { fontSize: 13, color: COLORS.textSecondary, lineHeight: 20, marginBottom: 8 },
  noNews: { fontSize: 13, color: COLORS.textMuted },
})
