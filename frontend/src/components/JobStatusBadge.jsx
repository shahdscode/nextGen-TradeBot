const styles = {
  pending: 'bg-white/10 text-gray-400 border-white/10',
  running: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
  done:    'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  failed:  'bg-red-500/15 text-red-300 border-red-500/30',
  error:   'bg-red-500/15 text-red-300 border-red-500/30',
}

export default function JobStatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${styles[status] || styles.pending}`}>
      {status === 'running' && (
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 mr-1.5 animate-pulse" />
      )}
      {status}
    </span>
  )
}
