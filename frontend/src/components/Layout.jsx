import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/authContext'
import toast from 'react-hot-toast'

const adminLinks = [
  { to: '/',             label: 'Dashboard',    end: true },
  { to: '/data',         label: 'Data' },
  { to: '/train',        label: 'RL Train' },
  { to: '/ml-train',     label: 'ML Train' },
  { to: '/backtest',     label: 'Backtest' },
  { to: '/compare',      label: 'Compare' },
  { to: '/publish',      label: 'Publish' },
  { to: '/paper-trading',label: 'Paper Trading' },
]

const userLinks = [
  { to: '/signals',      label: 'Signals',      end: true },
  { to: '/market',       label: 'Market' },
  { to: '/leaderboard',  label: 'Leaderboard' },
  { to: '/simulator',    label: 'Simulator' },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'
  const links = isAdmin ? adminLinks : userLinks

  const handleLogout = () => {
    logout()
    toast('Signed out')
    navigate('/login')
  }

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col py-6 px-4 shrink-0">
        <div className="mb-8">
          <h1 className="text-base font-bold text-white">NextGen TradeBot</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {isAdmin ? 'Admin Panel' : 'Trading Dashboard'}
          </p>
        </div>

        <nav className="flex flex-col gap-1 flex-1">
          {links.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {label}
            </NavLink>
          ))}

          {/* Admin quick-links to user views */}
          {isAdmin && (
            <>
              <div className="mt-4 mb-1 px-3 text-xs text-gray-600 uppercase tracking-wide">User views</div>
              {userLinks.map(({ to, label }) => (
                <NavLink key={to} to={to}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded-md text-xs transition-colors ${isActive ? 'bg-gray-700 text-white' : 'text-gray-500 hover:bg-gray-800 hover:text-white'}`
                  }>
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        {/* User info */}
        {user && (
          <div className="mt-4 pt-4 border-t border-gray-800">
            <div className="px-3 mb-2">
              <p className="text-xs font-medium text-gray-300">{user.username}</p>
              <p className="text-xs text-gray-500 capitalize">{user.role}</p>
            </div>
            <button onClick={handleLogout}
              className="w-full px-3 py-1.5 text-left text-xs text-gray-500 hover:text-white hover:bg-gray-800 rounded-md transition-colors">
              Sign out
            </button>
          </div>
        )}
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto bg-gray-50">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
