export function Skeleton({ className = '' }) {
  return <div className={`animate-pulse bg-white/10 rounded ${className}`} />
}

export function CardSkeleton() {
  return (
    <div className="bg-gray-900/50 rounded-xl border border-white/10 p-6 space-y-3">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-8 w-1/2" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  )
}

export function TableSkeleton({ rows = 5 }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

export function ChartSkeleton() {
  return <Skeleton className="h-64 w-full" />
}
