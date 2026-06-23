/** Subtle animated background — shared by landing, login, and app shell */
export default function AppBackground({ className = '' }) {
  return (
    <div className={`landing-bg ${className}`} aria-hidden="true">
      <div className="landing-grid" />
      <div className="landing-orb landing-orb-1" />
      <div className="landing-orb landing-orb-2" />
      <div className="landing-orb landing-orb-3" />
    </div>
  )
}
