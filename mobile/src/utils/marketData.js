/** Sources that are not real-time market data. */
export const placeholderSources = new Set(['synthetic', 'demo', 'dataset', 'unavailable'])

export function isLiveMarketSource(source) {
  if (!source) return true
  return source === 'live' || source === 'yahoo'
}

/**
 * Keep rows with real prices. By default hide synthetic/demo unless allowDemo.
 */
export function filterOverview(items, { allowDemo = false } = {}) {
  return (items || []).filter((item) => {
    if (!item?.ticker || item.price == null) return false
    if (item.source === 'unavailable') return false
    if (placeholderSources.has(item.source)) return allowDemo
    return isLiveMarketSource(item.source)
  })
}

/** @deprecated use filterOverview */
export function filterLiveOverview(items, opts) {
  return filterOverview(items, opts)
}

export function acceptMarketQuote(quote, { allowDemo = false } = {}) {
  if (!quote || quote.price == null) return null
  if (quote.source === 'unavailable') return null
  if (placeholderSources.has(quote.source) && !allowDemo) return null
  if (!isLiveMarketSource(quote.source) && !allowDemo) return null
  return quote
}

export function acceptLiveQuote(quote, opts) {
  return acceptMarketQuote(quote, opts)
}

export function acceptMarketCandles(rows, opts) {
  if (!rows?.length) return []
  const src = rows[0]?.source
  if (src === 'unavailable') return []
  if (placeholderSources.has(src) && !opts?.allowDemo) return []
  if (!isLiveMarketSource(src) && !opts?.allowDemo) return []
  return rows
}

export function acceptLiveCandles(rows, opts) {
  return acceptMarketCandles(rows, opts)
}

export function acceptMarketNews(news, opts) {
  if (!news) return null
  if (news.source === 'unavailable') return null
  if (placeholderSources.has(news.source) && !opts?.allowDemo) return null
  if (!isLiveMarketSource(news.source) && !opts?.allowDemo) return null
  return news
}

export function acceptLiveNews(news, opts) {
  return acceptMarketNews(news, opts)
}

/** Strip HTML from Yahoo/news API headlines for readable display. */
export function cleanHeadline(text) {
  if (!text) return ''
  return text.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
}
