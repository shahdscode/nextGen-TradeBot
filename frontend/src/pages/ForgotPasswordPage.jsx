import { useState } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import AppBackground from '../components/AppBackground'

export default function ForgotPasswordPage() {
  const [identifier, setIdentifier] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!identifier.trim()) return
    setLoading(true)
    try {
      await client.post('/api/auth/forgot-password', { identifier: identifier.trim() })
      setSent(true)
    } catch {
      setSent(true)   // generic — never reveal whether the account exists
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#050810] flex items-center justify-center px-4 relative">
      <AppBackground />
      <div className="w-full max-w-sm relative z-10">
        <div className="text-center mb-8">
          <Link to="/" className="inline-flex flex-col items-center hover:opacity-80">
            <img src="/logo.png" alt="NextGen TradeBot" className="h-12 w-12 rounded-xl mb-3" />
            <h1 className="text-2xl font-bold text-white">NextGen TradeBot</h1>
          </Link>
        </div>
        <div className="bg-gray-900/80 border border-white/10 backdrop-blur-xl rounded-2xl p-8 shadow-2xl">
          <h2 className="text-lg font-semibold text-white mb-2">Reset your password</h2>
          {sent ? (
            <p className="text-sm text-gray-300">
              If an account exists for that username or email, a reset link has been sent.
              Check your inbox (and spam).
            </p>
          ) : (
            <>
              <p className="text-xs text-gray-400 mb-5">
                Enter your username or email and we'll send a reset link.
              </p>
              <form onSubmit={handleSubmit} className="space-y-4">
                <input
                  type="text" value={identifier} autoFocus
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="username or email"
                  className="w-full bg-gray-900/80 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500/40"
                />
                <button type="submit" disabled={loading}
                  className="w-full bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg text-sm">
                  {loading ? 'Sending…' : 'Send reset link'}
                </button>
              </form>
            </>
          )}
          <p className="text-xs text-gray-500 mt-4 text-center">
            <Link to="/login" className="text-teal-400 hover:text-teal-300">Back to sign in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
