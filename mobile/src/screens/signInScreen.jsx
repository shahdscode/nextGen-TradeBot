import { useState, useEffect } from 'react'
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform, Alert, ScrollView,
} from 'react-native'
import { StatusBar } from 'expo-status-bar'
import { useAuth } from '../context/authContext'
import BrandHeader from '../components/brandHeader'
import { resolveApiBaseUrl, silentRequest, isRemoteApiMode } from '../api/client'
import { COLORS, RADIUS } from '../constants/theme'

export default function SignInScreen({ navigation }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [apiUrl, setApiUrl] = useState(resolveApiBaseUrl())
  const [apiStatus, setApiStatus] = useState('checking')

  const checkApi = () => {
    const url = resolveApiBaseUrl()
    setApiUrl(url)
    setApiStatus('checking')
    silentRequest({ method: 'get', url: '/health' })
      .then(() => setApiStatus('ok'))
      .catch(() => setApiStatus('fail'))
  }

  useEffect(() => {
    checkApi()
  }, [])

  const handleSignIn = async () => {
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
      <ScrollView
        contentContainerStyle={styles.scroll}
        keyboardShouldPersistTaps="handled"
      >
        <BrandHeader size="small" />

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Sign in</Text>

          <View style={styles.field}>
            <Text style={styles.label}>Username</Text>
            <TextInput
              style={styles.input}
              value={username}
              onChangeText={setUsername}
              placeholder="Your username"
              placeholderTextColor={COLORS.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
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
              onSubmitEditing={handleSignIn}
            />
          </View>

          <TouchableOpacity
            style={[styles.button, loading && styles.buttonDisabled]}
            onPress={handleSignIn}
            disabled={loading}
            activeOpacity={0.8}
          >
            <Text style={styles.buttonText}>
              {loading ? 'Signing in…' : 'Sign in'}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.linkRow}
            onPress={() => navigation.navigate('SignUp')}
          >
            <Text style={styles.linkMuted}>No account? </Text>
            <Text style={styles.link}>Sign up</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity onPress={checkApi} disabled={apiStatus === 'checking'}>
          <Text style={[
            styles.apiStatus,
            apiStatus === 'ok' && styles.apiStatusOk,
            apiStatus === 'fail' && styles.apiStatusFail,
          ]}>
            {apiStatus === 'checking' && 'Checking API…'}
            {apiStatus === 'ok' && '● API reachable'}
            {apiStatus === 'fail' && '● API unreachable — tap to retry'}
          </Text>
        </TouchableOpacity>
        <Text style={styles.apiHint} numberOfLines={2}>
          {isRemoteApiMode() ? '🌐 Remote' : '📶 LAN'} · {apiUrl}
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  scroll: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
    paddingVertical: 32,
  },
  card: {
    marginTop: 28,
    backgroundColor: COLORS.card,
    borderWidth: 1,
    borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.xl,
    padding: 24,
  },
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
  linkRow: { flexDirection: 'row', justifyContent: 'center', marginTop: 16 },
  linkMuted: { color: COLORS.textMuted, fontSize: 13 },
  link: { color: COLORS.teal, fontSize: 13, fontWeight: '600' },
  apiHint: { textAlign: 'center', color: COLORS.textMuted, fontSize: 10, marginTop: 8, opacity: 0.7 },
  apiStatus: { textAlign: 'center', fontSize: 11, marginTop: 16, color: COLORS.textMuted },
  apiStatusOk: { color: COLORS.green },
  apiStatusFail: { color: COLORS.red },
})
