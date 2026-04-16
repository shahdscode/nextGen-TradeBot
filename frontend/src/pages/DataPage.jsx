import { useState, useEffect } from 'react'
import Select from 'react-select'
import toast from 'react-hot-toast'
import client from '../api/client'
import JobStatusBadge from '../components/JobStatusBadge'
import { CardSkeleton, TableSkeleton } from '../components/Skeleton'

const SOURCE_OPTIONS = [
  { value: 'yahoo', label: 'Yahoo Finance (free)' },
  { value: 'alpaca', label: 'Alpaca Markets (requires API key)' },
  { value: 'mt5', label: 'MT5 Demo Gateway (requires API key)' },
]

const MT5_TIMEFRAME_OPTIONS = [
  { value: 'M1', label: 'M1' },
  { value: 'M5', label: 'M5' },
  { value: 'M15', label: 'M15' },
  { value: 'M30', label: 'M30' },
  { value: 'H1', label: 'H1' },
  { value: 'H4', label: 'H4' },
  { value: 'D1', label: 'D1' },
]

export default function DataPage() {
  const [allTickersBySource, setAllTickersBySource] = useState({})
  const [selectedTickers, setSelectedTickers] = useState([])
  const [loadingInfo, setLoadingInfo] = useState(true)
  const [startDate, setStartDate] = useState('2020-01-01')
  const [endDate, setEndDate] = useState('2023-12-31')
  const [source, setSource] = useState(SOURCE_OPTIONS[0])
  const [mt5Timeframe, setMt5Timeframe] = useState(MT5_TIMEFRAME_OPTIONS[2])
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [preview, setPreview] = useState(null)

  useEffect(() => {
    client.get('/api/info').then((r) => {
      let tickersBySource = r.data.tickers_by_source || {}
      
      // Fallback: if old API (returns tickers array), convert to new format
      if (!tickersBySource.yahoo && r.data.tickers) {
        tickersBySource = {
          yahoo: r.data.tickers,
          alpaca: r.data.tickers,
          mt5: r.data.tickers,
        }
      }
      
      console.log('Tickers by source:', tickersBySource)
      setAllTickersBySource(tickersBySource)
      
      // Initialize with yahoo tickers
      const initialTickers = (tickersBySource.yahoo || []).slice(0, 5)
      const opts = initialTickers.map((t) => ({ value: t, label: t }))
      setSelectedTickers(opts)
    }).catch((err) => {
      console.error('Failed to fetch /api/info:', err)
      toast.error('Failed to load tickers')
    }).finally(() => {
      setLoadingInfo(false)
    })
  }, [])

  useEffect(() => {
    if (!source?.value || !allTickersBySource[source.value]) return
    // Update selected tickers when source changes
    const sourceTickersArray = allTickersBySource[source.value] || []
    const opts = sourceTickersArray.slice(0, 5).map((t) => ({ value: t, label: t }))
    setSelectedTickers(opts)
  }, [source, allTickersBySource])

  // Poll job status
  useEffect(() => {
    if (!jobId || jobStatus === 'done' || jobStatus === 'failed') return
    const timer = setInterval(async () => {
      const r = await client.get(`/api/data/status/${jobId}`)
      setJobStatus(r.data.status)
      if (r.data.status === 'done') {
        clearInterval(timer)
        toast.success('Data download complete!')
        client.get(`/api/data/preview/${jobId}`).then((r) => setPreview(r.data.rows))
      }
      if (r.data.status === 'failed') {
        clearInterval(timer)
        toast.error('Data download failed')
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [jobId, jobStatus])

  const handleSubmit = async () => {
    if (!selectedTickers.length) return toast.error('Select at least one ticker')
    setSubmitting(true)
    setPreview(null)
    try {
      const r = await client.post('/api/data/download', {
        tickers: selectedTickers.map((t) => t.value),
        start_date: startDate,
        end_date: endDate,
        source: source.value,
        timeframe: source.value === 'mt5' ? mt5Timeframe.value : null,
      })
      setJobId(r.data.job_id)
      setJobStatus('pending')
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
          <label className="block text-sm font-medium text-gray-700 mb-1">Tickers</label>
          <Select
            isMulti
            options={(allTickersBySource[source?.value] || []).map((t) => ({ value: t, label: t }))}
            value={selectedTickers}
            onChange={setSelectedTickers}
            placeholder="Search tickers..."
            className="text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Start date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">End date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Data source</label>
          <Select
            options={SOURCE_OPTIONS}
            value={source}
            onChange={setSource}
            className="text-sm"
          />
          {source?.value === 'mt5' && (
            <p className="text-xs text-gray-500 mt-1">Use MT5 symbol names such as BTCUSDm.</p>
          )}
        </div>

        {source?.value === 'mt5' && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">MT5 timeframe</label>
            <Select
              options={MT5_TIMEFRAME_OPTIONS}
              value={mt5Timeframe}
              onChange={setMt5Timeframe}
              className="text-sm"
            />
          </div>
        )}

        <div className="flex items-center gap-4">
          <button
            onClick={handleSubmit}
            disabled={submitting}
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
