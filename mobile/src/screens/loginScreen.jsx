import { useState, useEffect } from 'react'
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform, Alert,
} from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { useAuth } from '../context/authContext'
import { resolveApiBaseUrl, silentRequest, isRemoteApiMode } from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

export default function LoginScreen() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [apiUrl, setApiUrl] = useState(resolveApiBaseUrl())
  const [apiStatus, setApiStatus] = useState('checking') // checking | ok | fail

  useEffect(() => {
    const url = resolveApiBaseUrl()
    setApiUrl(url)
    silentRequest({ method: 'get', url: '/health' })
      .then(() => setApiStatus('ok'))
      .catch(() => setApiStatus('fail'))
  }, [])

  const handleLogin = async () => {
    if (!username.trim() || !password.trim()) {
      return Alert.alert('Error', 'Please fill in all fields')
    }
    setLoading(true)
    try {
      await login(username.trim(), password)
    } catch {
      // handled by interceptor
    } finally {
      setLoading(false)
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <StatusBar style="light" />
      <View style={styles.inner}>
        <View style={styles.brandRow}>
          <View style={styles.dot} />
          <Text style={styles.brand}>NextGen TradeBot</Text>
        </View>
        <Text style={styles.tagline}>AI-Powered Trading Intelligence</Text>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Sign in</Text>

          <View style={styles.field}>
            <Text style={styles.label}>Username</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="admin"
              placeholderTextColor={COLORS.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="next"
            />
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>Password</Text>
            <TextInput
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              placeholderTextColor={COLORS.textMuted}
              secureTextEntry
              returnKeyType="go"
              onSubmitEditing={handleLogin}
            />
          </View>

          <TouchableOpacity
            style={[styles.button, loading && styles.buttonDisabled]}
            onPress={handleLogin}
            disabled={loading}
            activeOpacity={0.8}
          >
            <Text style={styles.buttonText}>
              {loading ? 'Signing in…' : 'Sign in'}
            </Text>
          </TouchableOpacity>

          <Text style={styles.hint}>Default: admin / admin123</Text>
          <Text style={styles.apiHint} numberOfLines={2}>
            {isRemoteApiMode() ? '🌐 Remote' : '📶 LAN'} · API: {apiUrl}
          </Text>
          <Text style={[
            styles.apiStatus,
            apiStatus === 'ok' && styles.apiStatusOk,
            apiStatus === 'fail' && styles.apiStatusFail,
          ]}>
            {apiStatus === 'checking' && 'Checking API…'}
            {apiStatus === 'ok' && '● API reachable'}
            {apiStatus === 'fail' && '● API unreachable — run ./scripts/start-all.sh'}
          </Text>
        </View>
      </View>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  inner: { flex: 1, justifyContent: 'center', paddingHorizontal: 24 },
  brandRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', marginBottom: 6 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: COLORS.teal, marginRight: 8 },
  brand: { fontSize: 22, fontWeight: '800', color: COLORS.textPrimary },
  tagline: { textAlign: 'center', color: COLORS.textMuted, fontSize: 13, marginBottom: 36 },
  card: { backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.cardBorder, borderRadius: RADIUS.xl, padding: 24 },
  cardTitle: { fontSize: 17, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 20 },
  field: { marginBottom: 16 },
  label: { fontSize: 12, color: COLORS.textMuted, marginBottom: 6 },
  input: {
    backgroundColor: COLORS.bg,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    color: COLORS.textPrimary,
  },
  button: {
    backgroundColor: COLORS.teal,
    borderRadius: RADIUS.md,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 8,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  hint: { textAlign: 'center', color: COLORS.textMuted, fontSize: 11, marginTop: 12 },
  apiHint: { textAlign: 'center', color: COLORS.textMuted, fontSize: 10, marginTop: 8, opacity: 0.7 },
  apiStatus: { textAlign: 'center', fontSize: 11, marginTop: 6, color: COLORS.textMuted },
  apiStatusOk: { color: COLORS.green },
  apiStatusFail: { color: COLORS.red },
})
