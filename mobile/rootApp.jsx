import { SafeAreaProvider } from 'react-native-safe-area-context'
import { AuthProvider } from './src/context/authContext'
import AppNavigator from './src/navigation/appNavigator'
import ErrorBoundary from './src/components/errorBoundary'
function Inner() {
  return <AppNavigator />
}

export default function App() {
  return (
    <ErrorBoundary>
      <SafeAreaProvider>
        <AuthProvider>
          <Inner />
        </AuthProvider>
      </SafeAreaProvider>
    </ErrorBoundary>
  )
}
