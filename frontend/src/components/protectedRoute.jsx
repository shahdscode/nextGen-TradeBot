import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/authContext'

export default function ProtectedRoute({ children, adminOnly = false }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  if (adminOnly && user.role !== 'admin') return <Navigate to="/app/signals" replace />
  return children
}
