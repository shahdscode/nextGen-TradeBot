import { useState, useEffect, useMemo, useCallback } from 'react'
import Select from 'react-select'
import toast from 'react-hot-toast'
import client from '../api/client'
import JobStatusBadge from '../components/JobStatusBadge'
import { CardSkeleton, TableSkeleton } from '../components/Skeleton'
import { darkSelectStyles } from '../selectTheme'

const sourceOptions = [
  { value: 'yahoo', label: 'Yahoo Finance — US (S&P 500, ETFs, indices)' },
  { value: 'yahoo_egx', label: 'Yahoo Finance — Egypt (EGX)' },
  { value: 'alpaca', label: 'Alpaca Markets (requires API key)' },
  { value: 'mt5', label: 'MT5 Demo Gateway (requires API key)' },
]

const mt5TimeframeOptions = [
  { value: 'M1', label: 'M1' },
  { value: 'M5', label: 'M5' },
  { value: 'M15', label: 'M15' },
  { value: 'M30', label: 'M30' },
  { value: 'H1', label: 'H1' },
  { value: 'H4', label: 'H4' },
  { value: 'D1', label: 'D1' },
]

function toTickerOption(t) {
  return { value: t, label: t }
}

function buildGroupedOptions(catalog, flatList) {
  if (catalog?.groups?.length) {
    return catalog.groups
      .filter((g) => g.tickers?.length)
      .map((g) => ({
        label: g.label,
        options: g.tickers.map(toTickerOption),
      }))
  }
  return (flatList || []).map(toTickerOption)
}

function defaultTickersForSource(sourceKey, allowedList, recommended) {
  const allowed = new Set(allowedList || [])
  if (!allowed.size) return []

  if (sourceKey === 'mt5') {
    return ['EURUSD', 'GBPUSD', 'XAUUSD'].filter((t) => allowed.has(t))
  }
  if (sourceKey === 'yahoo_egx') {
    return allowedList.slice(0, Math.min(3, allowedList.length))
  }

  const preset = recommended?.length
    ? recommended
    : ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'SPY', 'QQQ']
  const picked = preset.filter((t) => allowed.has(t))
  return picked.length >= 3 ? picked : allowedList.slice(0, 8)
}

export default function DataPage() {
  const [allTickersBySource, setAllTickersBySource] = useState({})
  const [tickerCatalogs, setTickerCatalogs] = useState({})
  const [selectedTickers, setSelectedTickers] = useState([])
  const [loadingInfo, setLoadingInfo] = useState(true)
  const [startDate, setStartDate] = useState('2020-01-01')
  const [endDate, setEndDate] = useState('2025-12-31')
  const [recommendedTickers, setRecommendedTickers] = useState([])
  const [source, setSource] = useState(sourceOptions[0])
  const [mt5Timeframe, setMt5Timeframe] = useState(mt5TimeframeOptions[2])
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [preview, setPreview] = useState(null)

  const activeCatalog = tickerCatalogs[source?.value]
  const allowedList = allTickersBySource[source?.value] || []
  const allowedSet = useMemo(() => new Set(allowedList), [allowedList])

  const selectOptions = useMemo(() => {
    return buildGroupedOptions(activeCatalog, allowedList)
  }, [activeCatalog, allowedList])

  const invalidSelected = useMemo(
    () => selectedTickers.filter((t) => !allowedSet.has(t.value)),
    [selectedTickers, allowedSet],
  )

  const applySelectionForSource = useCallback(
    (sourceKey, prevSelected, { announceRemovals = false } = {}) => {
      const list = allTickersBySource[sourceKey] || []
      const allowed = new Set(list)
      const kept = prevSelected.filter((o) => allowed.has(o.value))

      if (announceRemovals) {
        const removed = prevSelected.filter((o) => !allowed.has(o.value))
        if (removed.length > 0) {
          const label = sourceOptions.find((s) => s.value === sourceKey)?.label || sourceKey
          toast.error(
            `Not available for ${label}: ${removed.map((o) => o.value).join(', ')}`,
            { duration: 6000 },
          )
        }
      }

      if (kept.length > 0) return kept

      const defaults = defaultTickersForSource(sourceKey, list, recommendedTickers)
      return defaults.map(toTickerOption)
    },
    [allTickersBySource, recommendedTickers],
  )

  useEffect(() => {
    client.get('/api/info').then((r) => {
      const tickersBySource = r.data.tickers_by_source || {}
      setAllTickersBySource(tickersBySource)
      setTickerCatalogs(r.data.ticker_catalogs || {})

      const yahooList = tickersBySource.yahoo || []
      const defaults = defaultTickersForSource('yahoo', yahooList, [])
      setSelectedTickers(defaults.map(toTickerOption))
    }).catch((err) => {
      console.error('Failed to fetch /api/info:', err)
      toast.error('Failed to load tickers')
    }).finally(() => {
      setLoadingInfo(false)
    })

    client.get('/api/research/walk-forward-presets')
      .then((r) => {
        setRecommendedTickers(r.data.recommended_tickers || [])
        const dl = r.data.presets?.research_v1?.data_download
        if (dl) {
          setStartDate(dl.start_date)
          setEndDate(dl.end_date)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!source?.value || !allTickersBySource[source.value]) return
    setSelectedTickers((prev) =>
      applySelectionForSource(source.value, prev, { announceRemovals: true }),
    )
  }, [source, allTickersBySource, applySelectionForSource])

  const applyRecommendedTickers = () => {
    if (!recommendedTickers.length || !source?.value) return
    const opts = recommendedTickers
      .filter((t) => allowedSet.has(t))
      .map(toTickerOption)
    if (!opts.length) {
      toast.error(`Research preset tickers are not available for ${source.label}`)
      return
    }
    setSelectedTickers(opts)
    toast.success(`Selected ${opts.length} tickers (research preset)`)
  }

  useEffect(() => {
    if (!jobId || jobStatus === 'done' || jobStatus === 'failed') return
    const timer = setInterval(async () => {
      const r = await client.get(`/api/data/status/${jobId}`)
      setJobStatus(r.data.status)
      if (r.data.status === 'done') {
        clearInterval(timer)
        toast.success('Data download complete!')
        client.get(`/api/data/preview/${jobId}`).then((res) => setPreview(res.data.rows))
      }
      if (r.data.status === 'failed') {
        clearInterval(timer)
        toast.error('Data download failed')
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [jobId, jobStatus])

  const handleSubmit = async () => {
    if (!selectedTickers.length) {
      toast.error('Select at least one ticker')
      return
    }
    if (invalidSelected.length > 0) {
      toast.error(
        `Not available for ${source.label}: ${invalidSelected.map((t) => t.value).join(', ')}`,
      )
      return
    }

    const tickers = selectedTickers.map((t) => t.value)
    setSubmitting(true)
    setPreview(null)
    try {
      const r = await client.post('/api/data/download', {
        tickers,
        start_date: startDate,
        end_date: endDate,
        source: source.value,
        timeframe: source.value === 'mt5' ? mt5Timeframe.value : null,
      })
      setJobId(r.data.job_id)
      setJobStatus(r.data.status || 'pending')
    } catch (err) {
      // Global axios interceptor already shows API errors (avoid duplicate toasts)
      if (!err.response) {
        toast.error('Cannot reach API — is the backend running on port 8002?')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleCopyJobId = async () => {
    if (!jobId) return
    try {
      await navigator.clipboard.writeText(jobId)
      toast.success('Data Job ID copied')
    } catch {
      toast.error('Copy failed. Select and copy manually.')
    }
  }

  const canUseResearchPreset = ['yahoo', 'alpaca'].includes(source?.value)
    && recommendedTickers.some((t) => allowedSet.has(t))

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">Data</h1>
      <p className="text-sm text-gray-500 mb-6">Download and prepare market data for training</p>

      {loadingInfo ? (
        <div className="space-y-6 max-w-2xl">
          <CardSkeleton />
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <TableSkeleton rows={6} />
          </div>
        </div>
      ) : (
        <>

      <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5 max-w-2xl">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Data source</label>
          <Select
            options={sourceOptions}
            value={source}
            onChange={setSource}
            className="text-sm"
            styles={darkSelectStyles}
            classNamePrefix="app-select"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Tickers</label>
          <Select
            isMulti
            options={selectOptions}
            value={selectedTickers.filter((t) => allowedSet.has(t.value))}
            onChange={(opts) => setSelectedTickers(opts || [])}
            placeholder="Search tickers for this source..."
            className="text-sm"
            styles={darkSelectStyles}
            classNamePrefix="app-select"
            noOptionsMessage={() => 'No symbols for this data source'}
          />
          {activeCatalog?.note && (
            <p className="text-xs text-gray-500 mt-2">{activeCatalog.note}</p>
          )}
          {activeCatalog?.count > 0 && (
            <p className="text-xs text-gray-400 mt-1">
              {activeCatalog.count} symbols available for {source.label}
            </p>
          )}
          {invalidSelected.length > 0 && (
            <div className="mt-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
              Not available for {source.label}:{' '}
              <strong>{invalidSelected.map((t) => t.value).join(', ')}</strong>
            </div>
          )}
          {canUseResearchPreset && (
            <button
              type="button"
              onClick={applyRecommendedTickers}
              className="mt-2 text-xs text-blue-600 hover:underline"
            >
              Use research preset (AAPL, MSFT, GOOGL, SPY, QQQ, …)
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Start date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-gray-900/80 text-white focus:outline-none focus:ring-2 focus:ring-teal-500/40 focus:border-teal-500/40"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">End date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-gray-900/80 text-white focus:outline-none focus:ring-2 focus:ring-teal-500/40 focus:border-teal-500/40"
            />
          </div>
        </div>

        {source?.value === 'mt5' && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">MT5 timeframe</label>
            <Select
              options={mt5TimeframeOptions}
              value={mt5Timeframe}
              onChange={setMt5Timeframe}
              className="text-sm"
              styles={darkSelectStyles}
              classNamePrefix="app-select"
            />
            <p className="text-xs text-gray-500 mt-1">Use MT5 symbol names from the list above.</p>
          </div>
        )}

        <div className="flex items-center gap-4">
          <button
            onClick={handleSubmit}
            disabled={submitting || invalidSelected.length > 0 || !selectedTickers.length}
            className="px-5 py-2 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Submitting...' : 'Download data'}
          </button>
          {jobStatus && <JobStatusBadge status={jobStatus} />}
        </div>

        {jobId && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <p className="text-xs font-medium text-gray-600 mb-1">Data Job ID</p>
            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
              <code className="text-xs sm:text-sm text-gray-900 bg-white border border-gray-200 rounded px-2 py-1 break-all select-all">
                {jobId}
              </code>
              <button
                type="button"
                onClick={handleCopyJobId}
                className="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 bg-white text-gray-700 hover:bg-gray-100 transition-colors"
              >
                Copy ID
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">Use this ID in the Training page.</p>
          </div>
        )}
      </div>

      {preview && (
        <div className="mt-8">
          <h2 className="text-base font-medium text-gray-900 mb-3">Data preview (first 20 rows)</h2>
          <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
            <table className="text-xs w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {Object.keys(preview[0] || {}).slice(0, 10).map((k) => (
                    <th key={k} className="px-3 py-2 text-left text-gray-500 font-medium">{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {preview.map((row, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    {Object.values(row).slice(0, 10).map((v, j) => (
                      <td key={j} className="px-3 py-2 text-gray-600">
                        {typeof v === 'number' ? v.toFixed(4) : String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
        </>
      )}
    </div>
  )
}
