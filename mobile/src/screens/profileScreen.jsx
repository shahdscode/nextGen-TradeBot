import { useState, useEffect } from 'react'
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView,
  ActivityIndicator, Alert,
} from 'react-native'
import { Ionicons } from '@expo/vector-icons'

import client from '../api/client'
import { useAuth } from '../context/authContext'
import { COLORS, RADIUS } from '../constants/theme'

export default function ProfileScreen() {
  const { user, logout } = useAuth()
  const [cfg, setCfg] = useState(null)        // { configured, key_preview }
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const loadCfg = () => client.get('/api/auth/alpaca-config')
    .then(r => setCfg(r.data)).catch(() => setCfg({ configured: false }))

  useEffect(() => { loadCfg().finally(() => setLoading(false)) }, [])

  const save = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      Alert.alert('Missing keys', 'Enter both your Alpaca API key and secret.')
      return
    }
    setSaving(true)
    try {
      await client.put('/api/auth/alpaca-config', {
        api_key: apiKey.trim(), api_secret: apiSecret.trim(),
      })
      setApiKey(''); setApiSecret('')
      await loadCfg()
      Alert.alert('Saved', 'Your Alpaca paper-trading keys are connected.')
    } catch (e) {
      Alert.alert('Error', e.response?.data?.detail || 'Could not save keys')
    } finally { setSaving(false) }
  }

  const clear = async () => {
    setSaving(true)
    try {
      await client.delete('/api/auth/alpaca-config')
      await loadCfg()
      Alert.alert('Removed', 'Alpaca keys cleared.')
    } catch (e) {
      Alert.alert('Error', e.response?.data?.detail || 'Could not clear keys')
    } finally { setSaving(false) }
  }

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.title}>Profile</Text>
        <Text style={styles.sub}>Account & broker connection</Text>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {/* Account */}
        <View style={styles.card}>
          <View style={styles.avatarRow}>
            <View style={styles.avatar}>
              <Text style={styles.avatarText}>{(user?.username || '?')[0].toUpperCase()}</Text>
            </View>
            <View>
              <Text style={styles.username}>{user?.username}</Text>
              <Text style={styles.role}>{user?.role}</Text>
            </View>
          </View>
        </View>

        {/* Alpaca connection */}
        <Text style={styles.sectionTitle}>Alpaca Paper Trading</Text>
        <View style={styles.card}>
          {loading ? (
            <ActivityIndicator color={COLORS.teal} />
          ) : (
            <>
              <View style={styles.statusRow}>
                <Ionicons
                  name={cfg?.configured ? 'checkmark-circle' : 'alert-circle-outline'}
                  size={20}
                  color={cfg?.configured ? COLORS.green : COLORS.amber}
                />
                <Text style={[styles.statusText, { color: cfg?.configured ? COLORS.green : COLORS.amber }]}>
                  {cfg?.configured
                    ? `Connected (${cfg.key_preview || 'key set'})`
                    : 'Not connected'}
                </Text>
              </View>

              <Text style={styles.helpText}>
                Connect your own free Alpaca paper account to trade the models live.
                Get keys at alpaca.markets → Paper Trading → API Keys.
              </Text>

              <TextInput
                style={styles.input}
                placeholder="API Key ID"
                placeholderTextColor={COLORS.textMuted}
                value={apiKey}
                onChangeText={setApiKey}
                autoCapitalize="none"
                autoCorrect={false}
              />
              <TextInput
                style={styles.input}
                placeholder="API Secret"
                placeholderTextColor={COLORS.textMuted}
                value={apiSecret}
                onChangeText={setApiSecret}
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry
              />

              <TouchableOpacity style={styles.saveBtn} onPress={save} disabled={saving}>
                <Text style={styles.saveBtnText}>
                  {saving ? 'Saving…' : cfg?.configured ? 'Update Keys' : 'Connect Alpaca'}
                </Text>
              </TouchableOpacity>

              {cfg?.configured && (
                <TouchableOpacity style={styles.clearBtn} onPress={clear} disabled={saving}>
                  <Text style={styles.clearBtnText}>Disconnect</Text>
                </TouchableOpacity>
              )}
            </>
          )}
        </View>

        <Text style={styles.note}>
          Keys are paper-trading only (no real money). They're stored on your account
          and used to place simulated orders on your behalf.
        </Text>

        <TouchableOpacity style={styles.logoutBtn} onPress={logout}>
          <Ionicons name="log-out-outline" size={18} color={COLORS.red} />
          <Text style={styles.logoutText}>Sign out</Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: COLORS.bg },
  header: {
    paddingHorizontal: 20, paddingTop: 56, paddingBottom: 16,
    borderBottomWidth: 1, borderBottomColor: COLORS.cardBorder,
  },
  title: { fontSize: 18, fontWeight: '700', color: COLORS.textPrimary },
  sub: { fontSize: 13, color: COLORS.textMuted, marginTop: 2 },
  content: { padding: 20, paddingBottom: 40 },
  card: {
    backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.lg, padding: 16, marginBottom: 16,
  },
  avatarRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: COLORS.tealDim,
    alignItems: 'center', justifyContent: 'center',
  },
  avatarText: { fontSize: 18, fontWeight: '700', color: '#fff' },
  username: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary },
  role: { fontSize: 12, color: COLORS.textMuted, textTransform: 'capitalize' },
  sectionTitle: {
    fontSize: 14, fontWeight: '700', color: COLORS.textPrimary,
    textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10,
  },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  statusText: { fontSize: 14, fontWeight: '600' },
  helpText: { fontSize: 12, color: COLORS.textMuted, marginBottom: 14, lineHeight: 18 },
  input: {
    backgroundColor: COLORS.bg, borderWidth: 1, borderColor: COLORS.cardBorder,
    borderRadius: RADIUS.md, paddingHorizontal: 12, paddingVertical: 10,
    color: COLORS.textPrimary, fontSize: 14, marginBottom: 10,
  },
  saveBtn: {
    backgroundColor: COLORS.teal, borderRadius: RADIUS.md,
    paddingVertical: 12, alignItems: 'center', marginTop: 4,
  },
  saveBtnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
  clearBtn: { paddingVertical: 10, alignItems: 'center', marginTop: 4 },
  clearBtnText: { color: COLORS.red, fontWeight: '600', fontSize: 13 },
  note: { fontSize: 11, color: COLORS.textMuted, lineHeight: 16, marginBottom: 20 },
  logoutBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    borderWidth: 1, borderColor: COLORS.cardBorder, borderRadius: RADIUS.md, paddingVertical: 12,
  },
  logoutText: { color: COLORS.red, fontWeight: '600', fontSize: 14 },
})
