/** Inject API URL into the app manifest (works for LAN + remote tunnel sessions). */
const fs = require('fs')
const path = require('path')

function loadDotEnv() {
  const envPath = path.join(__dirname, '.env')
  if (!fs.existsSync(envPath)) return
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const i = trimmed.indexOf('=')
    if (i === -1) continue
    const key = trimmed.slice(0, i).trim()
    const val = trimmed.slice(i + 1).trim()
    if (!process.env[key]) process.env[key] = val
  }
}

loadDotEnv()

module.exports = ({ config }) => ({
  ...config,
  extra: {
    ...config.extra,
    apiUrl: process.env.EXPO_PUBLIC_API_URL || '',
    forceTunnel: process.env.EXPO_PUBLIC_FORCE_TUNNEL === '1',
  },
})
