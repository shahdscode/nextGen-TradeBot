import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/authContext'
import Layout from './components/layout'
import ErrorBoundary from './components/errorBoundary'
import ProtectedRoute from './components/protectedRoute'

// Auth
import LoginPage from './pages/loginPage'

// Admin pages
import DashboardPage       from './pages/dashboardPage'
import DataPage            from './pages/dataPage'
import TrainingPage        from './pages/trainingPage'
import MLTrainingPage      from './pages/mlTrainingPage'
import BacktestPage        from './pages/backtestPage'
import ComparePage         from './pages/comparePage'
import PublishPage         from './pages/publishPage'
import PaperTradingPage    from './pages/paperTradingPage'
import MetaLearnerPage     from './pages/MetaLearnerPage'
import ModelWeightsPage    from './pages/ModelWeightsPage'
import ModelPerformancePage from './pages/ModelPerformancePage'

// User pages
import SignalsPage      from './pages/signalsPage'
import MarketPage       from './pages/marketPage'
import LeaderboardPage  from './pages/leaderboardPage'
import SimulatorPage    from './pages/simulatorPage'

export default function App() {
  return (
    <AuthProvider>
      <ErrorBoundary>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route path="/" element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }>
            {/* Admin routes */}
            <Route index element={
              <ProtectedRoute adminOnly>
                <DashboardPage />
              </ProtectedRoute>
            } />
            <Route path="data" element={<ProtectedRoute adminOnly><DataPage /></ProtectedRoute>} />
            <Route path="train" element={<ProtectedRoute adminOnly><TrainingPage /></ProtectedRoute>} />
            <Route path="ml-train" element={<ProtectedRoute adminOnly><MLTrainingPage /></ProtectedRoute>} />
            <Route path="backtest" element={<ProtectedRoute adminOnly><BacktestPage /></ProtectedRoute>} />
            <Route path="compare" element={<ProtectedRoute adminOnly><ComparePage /></ProtectedRoute>} />
            <Route path="publish" element={<ProtectedRoute adminOnly><PublishPage /></ProtectedRoute>} />
            <Route path="paper-trading" element={<ProtectedRoute adminOnly><PaperTradingPage /></ProtectedRoute>} />
            <Route path="meta-learner" element={<ProtectedRoute adminOnly><MetaLearnerPage /></ProtectedRoute>} />
            <Route path="model-weights" element={<ProtectedRoute adminOnly><ModelWeightsPage /></ProtectedRoute>} />
            <Route path="performance" element={<ProtectedRoute adminOnly><ModelPerformancePage /></ProtectedRoute>} />

            {/* User routes — accessible to all authenticated users */}
            <Route path="signals" element={<SignalsPage />} />
            <Route path="market" element={<MarketPage />} />
            <Route path="leaderboard" element={<LeaderboardPage />} />
            <Route path="simulator" element={<SimulatorPage />} />
          </Route>

          {/* Catch-all: redirect to login */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </ErrorBoundary>
    </AuthProvider>
  )
}
