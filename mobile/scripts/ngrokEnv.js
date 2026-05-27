const fs = require('fs')
const path = require('path')

const mobileRoot = path.join(__dirname, '..')
const envPath = path.join(mobileRoot, '.env')
const API_PORT = 8002

function tokenFromYaml(filePath) {
  if (!fs.existsSync(filePath)) return null
  const m = fs.readFileSync(filePath, 'utf8').match(/^\s*authtoken:\s*(\S+)\s*$/m)
  return m ? m[1].trim() : null
}

function loadNgrokToken() {
  if (process.env.NGROK_AUTHTOKEN) return process.env.NGROK_AUTHTOKEN.trim()
  if (fs.existsSync(envPath)) {
    for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
      const m = line.match(/^NGROK_AUTHTOKEN=(.+)$/)
      if (m && m[1].trim()) return m[1].trim()
    }
  }
  const home = process.env.HOME || process.env.USERPROFILE || ''
  if (home) {
    const fromExpo = tokenFromYaml(path.join(home, '.expo', 'ngrok.yml'))
    if (fromExpo) return fromExpo
    const legacy = tokenFromYaml(path.join(home, '.ngrok2', 'ngrok.yml'))
    if (legacy) return legacy
  }
  return null
}

/** Save token + LAN API URL into mobile/.env */
function persistEnv(token) {
  const { getBestLanIp } = require('./networkUtils')
  const ip = getBestLanIp()
  const apiLine = ip
    ? `EXPO_PUBLIC_API_URL=http://${ip}:${API_PORT}`
    : '# EXPO_PUBLIC_API_URL set by npm run share'
  const lines = [
    '# LAN API (same Wi‑Fi)',
    `NGROK_AUTHTOKEN=${token}`,
    apiLine,
    'EXPO_PUBLIC_FORCE_TUNNEL=0',
    '',
  ]
  fs.writeFileSync(envPath, lines.join('\n'))
}

/** Remote / any-network mode: public API tunnel + Expo tunnel. */
function writeEnvRemoteMode(tunnelUrl, token) {
  const lines = [
    '# Remote mode — phones on ANY network (npm run start:remote)',
    `EXPO_PUBLIC_API_URL=${tunnelUrl}`,
    'EXPO_PUBLIC_FORCE_TUNNEL=1',
    `NGROK_AUTHTOKEN=${token}`,
    '',
  ]
  fs.writeFileSync(envPath, lines.join('\n'))
  console.log('Updated', envPath)
  console.log('EXPO_PUBLIC_API_URL=' + tunnelUrl)
  console.log('EXPO_PUBLIC_FORCE_TUNNEL=1')
}

/** Restore LAN .env after remote session ends. */
function restoreLanEnv() {
  const { execSync } = require('child_process')
  try {
    execSync('node scripts/syncApiIp.js', { cwd: mobileRoot, stdio: 'inherit' })
  } catch {
    const { getBestLanIp } = require('./networkUtils')
    const ip = getBestLanIp()
    const token = loadNgrokToken()
    if (!ip) return
    const lines = [
      '# Auto-synced LAN API (phones on same Wi‑Fi as Mac)',
      `EXPO_PUBLIC_API_URL=http://${ip}:${API_PORT}`,
      'EXPO_PUBLIC_FORCE_TUNNEL=0',
      token ? `NGROK_AUTHTOKEN=${token}` : '# NGROK_AUTHTOKEN=',
      '',
    ]
    fs.writeFileSync(envPath, lines.join('\n'))
    console.log('Restored LAN mode in .env')
  }
}

/** @deprecated use writeEnvRemoteMode */
function writeEnvApiUrl(tunnelUrl, token) {
  writeEnvRemoteMode(tunnelUrl, token)
}

function requireToken() {
  const token = loadNgrokToken()
  if (!token) {
    console.error('\nRemote mode needs NGROK_AUTHTOKEN (free at dashboard.ngrok.com)')
    console.error('1. https://dashboard.ngrok.com/get-started/your-authtoken')
    console.error('2. npm run sync:ngrok   OR add NGROK_AUTHTOKEN=... to mobile/.env')
    console.error('3. npm run start:remote\n')
    process.exit(1)
  }
  const hasTokenInEnv =
    fs.existsSync(envPath) && /^NGROK_AUTHTOKEN=\S+/m.test(fs.readFileSync(envPath, 'utf8'))
  if (!hasTokenInEnv) {
    persistEnv(token)
    console.log('Saved NGROK_AUTHTOKEN to mobile/.env')
  }
  return token
}

module.exports = {
  mobileRoot,
  envPath,
  API_PORT,
  loadNgrokToken,
  persistEnv,
  writeEnvRemoteMode,
  writeEnvApiUrl,
  restoreLanEnv,
  requireToken,
}
