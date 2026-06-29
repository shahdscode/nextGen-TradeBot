import { Link } from 'react-router-dom'

export default function LegalLayout({ title, updated, children }) {
  return (
    <div className="min-h-screen bg-[#050810] text-gray-300 px-4 py-12">
      <div className="max-w-2xl mx-auto">
        <Link to="/" className="inline-flex items-center gap-2 mb-8 hover:opacity-80">
          <img src="/logo.png" alt="NextGen TradeBot" className="h-8 w-8 rounded-lg" />
          <span className="text-white font-semibold">NextGen TradeBot</span>
        </Link>
        <h1 className="text-2xl font-bold text-white mb-1">{title}</h1>
        {updated && <p className="text-xs text-gray-500 mb-8">Last updated: {updated}</p>}
        <div className="space-y-4 text-sm leading-relaxed [&_h2]:text-white [&_h2]:font-semibold [&_h2]:mt-6 [&_h2]:mb-1">
          {children}
        </div>
        <div className="mt-10 pt-6 border-t border-white/10 text-xs text-gray-500 flex gap-4">
          <Link to="/terms" className="hover:text-teal-400">Terms</Link>
          <Link to="/privacy" className="hover:text-teal-400">Privacy</Link>
          <Link to="/disclaimer" className="hover:text-teal-400">Disclaimer</Link>
        </div>
      </div>
    </div>
  )
}
