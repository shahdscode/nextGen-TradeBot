import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import AppBackground from '../components/AppBackground'

export default function VerifyEmailPage() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [status, setStatus] = useState('verifying')   // verifying | ok | error

  useEffect(() => {
    if (!token) { setStatus('error'); return }
    client.post('/api/auth/verify-email', { token })
      .then(() => setStatus('ok'))
      .catch(() => setStatus('error'))
  }, [token])

  return (
    <div className="min-h-screen bg-[#050810] flex items-center justify-center px-4 relative">
      <AppBackground />
      <div className="w-full max-w-sm relative z-10 text-center">
        <img src="/logo.png" alt="NextGen TradeBot" className="h-12 w-12 rounded-xl mb-3 mx-auto" />
        <h1 className="text-2xl font-bold text-white mb-6">NextGen TradeBot</h1>
        <div className="bg-gray-900/80 border border-white/10 backdrop-blur-xl rounded-2xl p-8 shadow-2xl">
          {status === 'verifying' && <p className="text-sm text-gray-300">Verifying your email…</p>}
          {status === 'ok' && (
            <>
              <p className="text-2xl mb-2">✅</p>
              <p className="text-sm text-gray-200 mb-4">Your email is verified. You can sign in now.</p>
              <Link to="/login" className="inline-block bg-teal-600 hover:bg-teal-500 text-white text-sm font-medium px-4 py-2 rounded-lg">Sign in</Link>
            </>
          )}
          {status === 'error' && (
            <>
              <p className="text-2xl mb-2">⚠️</p>
              <p className="text-sm text-gray-200 mb-1">This verification link is invalid or has expired.</p>
              <p className="text-xs text-gray-400 mb-4">Sign in and request a new link if needed.</p>
              <Link to="/login" className="text-teal-400 hover:text-teal-300 text-sm">Back to sign in</Link>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
