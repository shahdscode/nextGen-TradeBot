import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import toast from 'react-hot-toast'

export default function SettingsPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [configured, setConfigured] = useState(false)
  const [keyPreview, setKeyPreview] = useState(null)
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')

  const load = () =>
    client.get('/api/auth/alpaca-config')
      .then((r) => {
        setConfigured(!!r.data.configured)
        setKeyPreview(r.data.key_preview)
      })
      .catch(() => {})
      .finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  const handleSave = async (e) => {
    e.preventDefault()
    if (!apiKey.trim() || !apiSecret.trim()) {
      return toast.error('Enter both API key and secret')
    }
    setSaving(true)
    try {
      await client.put('/api/auth/alpaca-config', {
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
      })
      toast.success('Alpaca paper keys saved')
      setApiKey('')
      setApiSecret('')
      await load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to save keys')
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    if (!window.confirm('Remove your Alpaca keys from this account?')) return
    try {
      await client.delete('/api/auth/alpaca-config')
      toast.success('Alpaca keys removed')
      setConfigured(false)
      setKeyPreview(null)
    } catch {
      toast.error('Failed to remove keys')
    }
  }

  if (loading) {
    return <p className="text-gray-400 text-sm">Loading settings…</p>
  }

  return (
    <div className="space-y-8 max-w-lg">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">
          Connect your own Alpaca paper account. Keys are stored per user and never shared.
        </p>
      </div>

      <div className="bg-gray-900/60 border border-white/10 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Alpaca Paper Trading</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            configured ? 'bg-teal-500/20 text-teal-300' : 'bg-gray-700 text-gray-400'
          }`}>
            {configured ? 'Connected' : 'Not configured'}
          </span>
        </div>

        {configured && keyPreview && (
          <p className="text-xs text-gray-500">Current key: {keyPreview}</p>
        )}

        <form onSubmit={handleSave} className="space-y-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={configured ? 'Enter new key to replace' : 'PK…'}
              className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">API Secret</label>
            <input
              type="password"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              className="w-full bg-gray-950 border border-white/10 rounded-lg px-3 py-2 text-sm text-white"
            />
          </div>
          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={saving}
              className="bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-lg"
            >
              {saving ? 'Saving…' : configured ? 'Update keys' : 'Save keys'}
            </button>
            {configured && (
              <button
                type="button"
                onClick={handleClear}
                className="text-sm text-gray-400 hover:text-white px-4 py-2 rounded-lg border border-white/10"
              >
                Remove
              </button>
            )}
          </div>
        </form>

        <p className="text-xs text-gray-500">
          Get free paper keys at{' '}
          <a href="https://alpaca.markets" target="_blank" rel="noreferrer" className="text-teal-400">
            alpaca.markets
          </a>
          . Then open{' '}
          <Link to="/app/paper-trading" className="text-teal-400 hover:text-teal-300">
            Paper Trading
          </Link>
          .
        </p>
      </div>
    </div>
  )
}
