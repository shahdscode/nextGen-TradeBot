import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import DashboardPage    from './pages/DashboardPage'
import DataPage         from './pages/DataPage'
import TrainingPage     from './pages/TrainingPage'
import BacktestPage     from './pages/BacktestPage'
import ComparePage      from './pages/ComparePage'
import PaperTradingPage from './pages/PaperTradingPage'

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index                 element={<DashboardPage />} />
          <Route path="data"           element={<DataPage />} />
          <Route path="train"          element={<TrainingPage />} />
          <Route path="backtest"       element={<BacktestPage />} />
          <Route path="compare"        element={<ComparePage />} />
          <Route path="paper-trading"  element={<PaperTradingPage />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}
