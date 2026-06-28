import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/authContext'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import ProtectedRoute from './components/protectedRoute'

// Public
import LandingPage from './pages/LandingPage'
import LoginPage from './pages/loginPage'
import SignUpPage from './pages/signUpPage'

// Admin pages
import DashboardPage       from './pages/DashboardPage'
import DataPage            from './pages/DataPage'
import TrainingPage        from './pages/TrainingPage'
import MLTrainingPage      from './pages/mlTrainingPage'
import BacktestPage        from './pages/BacktestPage'
import ComparePage         from './pages/ComparePage'
import PublishPage         from './pages/publishPage'
import PaperTradingPage    from './pages/PaperTradingPage'
import MetaLearnerPage     from './pages/MetaLearnerPage'
import ModelWeightsPage    from './pages/ModelWeightsPage'
import ModelPerformancePage from './pages/ModelPerformancePage'

// User pages
import SignalsPage      from './pages/signalsPage'
import MarketPage       from './pages/marketPage'
import LeaderboardPage  from './pages/leaderboardPage'
import SimulatorPage    from './pages/simulatorPage'
import SettingsPage     from './pages/SettingsPage'
import CommandCenterPage from './pages/CommandCenterPage'
import TradeDecisionPage from './pages/TradeDecisionPage'

export default function App() {
  return (
    <AuthProvider>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignUpPage />} />

          <Route path="/app" element={
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
            <Route path="meta-learner" element={<ProtectedRoute adminOnly><MetaLearnerPage /></ProtectedRoute>} />
            <Route path="model-weights" element={<ProtectedRoute adminOnly><ModelWeightsPage /></ProtectedRoute>} />
            <Route path="performance" element={<ProtectedRoute adminOnly><ModelPerformancePage /></ProtectedRoute>} />

            {/* User routes — accessible to all authenticated users */}
            <Route path="home" element={<CommandCenterPage />} />
            <Route path="trades/:tradeId" element={<TradeDecisionPage />} />
            <Route path="signals" element={<SignalsPage />} />
            <Route path="market" element={<MarketPage />} />
            <Route path="leaderboard" element={<LeaderboardPage />} />
            <Route path="simulator" element={<SimulatorPage />} />
            <Route path="paper-trading" element={<PaperTradingPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </AuthProvider>
  )
}
