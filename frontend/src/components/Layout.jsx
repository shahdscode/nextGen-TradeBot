import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/',              label: 'Dashboard' },
  { to: '/data',          label: 'Data' },
  { to: '/train',         label: 'Train' },
  { to: '/backtest',      label: 'Backtest' },
  { to: '/compare',       label: 'Compare' },
  { to: '/paper-trading', label: 'Paper Trading' },
]

export default function Layout() {
  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col py-6 px-4 shrink-0">
        <div className="mb-8">
          <h1 className="text-lg font-semibold text-white">FinRL</h1>
          <p className="text-xs text-gray-400 mt-0.5">Dashboard</p>
        </div>
        <nav className="flex flex-col gap-1">
          {links.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
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
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
