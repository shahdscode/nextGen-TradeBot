import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/authContext'
import toast from 'react-hot-toast'
import AppBackground from './AppBackground'

const APP = '/app'

const adminLinks = [
  { to: `${APP}`,               label: 'Dashboard',    end: true, section: null },
  { to: `${APP}/data`,           label: 'Data',                    section: null },
  { to: `${APP}/train`,          label: 'RL Train',                section: null },
  { to: `${APP}/ml-train`,       label: 'ML Train',                section: null },
  { to: `${APP}/meta-learner`,   label: 'Meta-Learner',            section: 'AI Pipeline' },
  { to: `${APP}/model-weights`,  label: 'Model Weights',           section: 'AI Pipeline' },
  { to: `${APP}/performance`,    label: 'Performance',             section: 'AI Pipeline' },
  { to: `${APP}/backtest`,       label: 'Backtest',                section: 'Analysis' },
  { to: `${APP}/compare`,        label: 'Compare',                 section: 'Analysis' },
  { to: `${APP}/publish`,        label: 'Publish',                 section: 'Analysis' },
  { to: `${APP}/paper-trading`,  label: 'Paper Trading',           section: 'Analysis' },
]

const userLinks = [
  { to: `${APP}/signals`,      label: 'Signals',      end: true },
  { to: `${APP}/market`,       label: 'Market' },
  { to: `${APP}/leaderboard`,  label: 'Leaderboard' },
  { to: `${APP}/simulator`,    label: 'Simulator' },
]

const navClass = ({ isActive }, compact = false) =>
  `px-3 ${compact ? 'py-1.5 text-xs' : 'py-2 text-sm'} rounded-lg transition-colors border ${
    isActive
      ? 'bg-teal-600/15 text-teal-300 border-teal-500/30'
      : 'text-gray-400 border-transparent hover:bg-white/5 hover:text-white'
  }`

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
    <div className="app-shell flex min-h-screen bg-[#050810] text-gray-100 relative">
      <AppBackground className="opacity-60" />

      {/* Sidebar */}
      <aside className="relative z-20 w-56 shrink-0 flex flex-col py-6 px-4 border-r border-white/10 bg-gray-900/60 backdrop-blur-xl">
        <div className="mb-8 px-1">
          <div className="flex items-center gap-2.5">
            <img src="/logo.png" alt="" className="h-8 w-8 rounded-lg" />
            <div>
              <h1 className="text-sm font-bold text-white leading-tight">NextGen TradeBot</h1>
              <p className="text-[10px] text-gray-500 mt-0.5">
                {isAdmin ? 'Admin Panel' : 'Trading Dashboard'}
              </p>
            </div>
          </div>
        </div>

        <nav className="flex flex-col gap-0.5 flex-1">
          {links.reduce((acc, link, idx) => {
            const prev = links[idx - 1]
            if (link.section && link.section !== prev?.section) {
              acc.push(
                <div
                  key={`section-${link.section}`}
                  className="mt-3 mb-1 px-3 text-[10px] text-teal-500/70 uppercase tracking-widest font-semibold"
                >
                  {link.section}
                </div>
              )
            }
            acc.push(
              <NavLink key={link.to} to={link.to} end={link.end} className={navClass}>
                {link.label}
              </NavLink>
            )
            return acc
          }, [])}

          {isAdmin && (
            <>
              <div className="mt-4 mb-1 px-3 text-[10px] text-gray-600 uppercase tracking-widest font-semibold">
                User views
              </div>
              {userLinks.map(({ to, label }) => (
                <NavLink key={to} to={to} className={(props) => navClass(props, true)}>
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        {user && (
          <div className="mt-4 pt-4 border-t border-white/10">
            <div className="px-3 mb-2">
              <p className="text-xs font-medium text-gray-200">{user.username}</p>
              <p className="text-xs text-gray-500 capitalize">{user.role}</p>
            </div>
            <button
              onClick={handleLogout}
              className="w-full px-3 py-1.5 text-left text-xs text-gray-500 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
            >
              Sign out
            </button>
          </div>
        )}
      </aside>

      {/* Main content */}
      <main className="relative z-10 flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
