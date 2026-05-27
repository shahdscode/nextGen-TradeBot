import axios from 'axios'
import AsyncStorage from '@react-native-async-storage/async-storage'
import { Alert, Platform } from 'react-native'
import Constants from 'expo-constants'

const apiPort = 8002

function isLanIPv4(host) {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(host || '')
}

function isPublicTunnelUrl(url) {
  if (!url) return false
  const u = url.toLowerCase()
  return (
    u.includes('loca.lt') ||
    u.includes('ngrok') ||
    u.includes('trycloudflare.com') ||
    u.includes('localhost.run')
  )
}

function getExpoDebuggerHost() {
  const raw =
    Constants.expoGoConfig?.debuggerHost ??
    Constants.manifest2?.extra?.expoGo?.debuggerHost ??
    Constants.manifest?.debuggerHost
  return raw ? raw.split(':')[0] : null
}

function lanApiFromDebugger() {
  const host = getExpoDebuggerHost()
  if (__DEV__ && host && isLanIPv4(host)) {
    return `http://${host}:${apiPort}`
  }
  return null
}

/** True when Expo Go loaded the bundle via exp.direct / tunnel (phone not on LAN). */
function isExpoRemoteSession() {
  if (Constants.expoConfig?.extra?.forceTunnel) return true
  if (process.env.EXPO_PUBLIC_FORCE_TUNNEL === '1') return true
  const host = (getExpoDebuggerHost() || '').toLowerCase()
  return (
    host.includes('exp.direct') ||
    host.includes('expo.dev') ||
    host.includes('ngrok') ||
    (!isLanIPv4(host) && host.length > 0)
  )
}

function getConfiguredApiUrl() {
  const fromExtra = Constants.expoConfig?.extra?.apiUrl
  const fromEnv = process.env.EXPO_PUBLIC_API_URL
  const url = (fromExtra || fromEnv || '').replace(/\/$/, '')
  return url || null
}

/**
 * LAN: Mac IP from Expo debugger or .env
 * Remote: public tunnel URL from npm run start:remote (never LAN fallback)
 */
export function resolveApiBaseUrl() {
  const configured = getConfiguredApiUrl()
  const forceTunnel =
    Constants.expoConfig?.extra?.forceTunnel === true ||
    process.env.EXPO_PUBLIC_FORCE_TUNNEL === '1'
  const remote = isExpoRemoteSession() || forceTunnel
  const lanFromExpo = lanApiFromDebugger()

  if (remote) {
    if (configured) return configured
    return configured || `http://127.0.0.1:${apiPort}`
  }

  if (__DEV__ && lanFromExpo) {
    if (!configured || isPublicTunnelUrl(configured)) {
      return lanFromExpo
    }
  }

  if (configured) return configured

  if (lanFromExpo) return lanFromExpo

  if (__DEV__ && Platform.OS === 'android') {
    return `http://10.0.2.2:${apiPort}`
  }

  return `http://127.0.0.1:${apiPort}`
}

export function isRemoteApiMode() {
  return isExpoRemoteSession() || isPublicTunnelUrl(resolveApiBaseUrl())
}

const client = axios.create({
  timeout: 45000,
})

client.interceptors.request.use(async (config) => {
  const base = resolveApiBaseUrl()
  config.baseURL = base
  if (base.includes('ngrok')) {
    config.headers['ngrok-skip-browser-warning'] = '1'
  }
  if (base.includes('loca.lt')) {
    config.headers['Bypass-Tunnel-Reminder'] = 'true'
  }
  const token = await AsyncStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

function formatApiError(err) {
  const base = resolveApiBaseUrl()
  const status = err.response?.status
  const detail = err.response?.data?.detail

  if (detail) {
    return typeof detail === 'string' ? detail : JSON.stringify(detail)
  }

  if (status === 404) {
    if (isPublicTunnelUrl(base)) {
      return (
        `API returned 404 via tunnel.\n\n` +
        'Restart remote mode on your Mac:\n' +
        '  ./scripts/start-all.sh\n' +
        '  cd mobile && npm run start:remote'
      )
    }
    return (
      `API returned 404 at ${base}. Restart the backend:\n` +
      './scripts/stop-all.sh && ./scripts/start-all.sh'
    )
  }

  if (err.message === 'Network Error') {
    if (isRemoteApiMode()) {
      return (
        `Cannot reach API at ${base}.\n\n` +
        'Remote mode:\n' +
        '• Mac: ./scripts/start-all.sh\n' +
        '• Mac: cd mobile && npm run start:remote\n' +
        '• Reload Expo Go after Metro restarts'
      )
    }
    return (
      `Cannot reach API at ${base}.\n\n` +
      'Same Wi‑Fi:\n' +
      '• ./scripts/start-all.sh\n' +
      '• cd mobile && npm run sync-api-ip && npm run start'
    )
  }

  return err.message || 'Something went wrong'
}

client.interceptors.response.use(
  (res) => res,
  async (err) => {
    if (err.response?.status === 401) {
      await AsyncStorage.removeItem('token')
    } else if (!err.config?.silent) {
      Alert.alert('Error', formatApiError(err))
    }
    return Promise.reject(err)
  }
)

export function silentRequest(config) {
  return client.request({ ...config, silent: true })
}

export default client
