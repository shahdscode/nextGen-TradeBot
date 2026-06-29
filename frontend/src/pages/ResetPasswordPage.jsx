import { useState } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import client from '../api/client'
import toast from 'react-hot-toast'
import AppBackground from '../components/AppBackground'

export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') || ''
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (pw.length < 8) return toast.error('Password must be at least 8 characters')
    if (pw !== pw2) return toast.error('Passwords do not match')
    setLoading(true)
    try {
      await client.post('/api/auth/reset-password', { token, new_password: pw })
      toast.success('Password updated — please sign in')
      navigate('/login')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Reset link is invalid or expired')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#050810] flex items-center justify-center px-4 relative">
      <AppBackground />
      <div className="w-full max-w-sm relative z-10">
        <div className="text-center mb-8">
          <img src="/logo.png" alt="NextGen TradeBot" className="h-12 w-12 rounded-xl mb-3 mx-auto" />
          <h1 className="text-2xl font-bold text-white">NextGen TradeBot</h1>
        </div>
        <div className="bg-gray-900/80 border border-white/10 backdrop-blur-xl rounded-2xl p-8 shadow-2xl">
          <h2 className="text-lg font-semibold text-white mb-5">Choose a new password</h2>
          {!token ? (
            <p className="text-sm text-red-400">Missing reset token. Use the link from your email.</p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
                placeholder="New password" autoFocus
                className="w-full bg-gray-900/80 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500/40" />
              <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
                placeholder="Confirm new password"
                className="w-full bg-gray-900/80 border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-teal-500/40" />
              <button type="submit" disabled={loading}
                className="w-full bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg text-sm">
                {loading ? 'Updating…' : 'Update password'}
              </button>
            </form>
          )}
          <p className="text-xs text-gray-500 mt-4 text-center">
            <Link to="/login" className="text-teal-400 hover:text-teal-300">Back to sign in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
