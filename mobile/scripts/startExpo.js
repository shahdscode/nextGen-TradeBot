#!/usr/bin/env node
/**
 * Expo Go for one or many phones.
 *   npm run start        → LAN (same Wi‑Fi)
 *   npm run start:share  → tunnel QR (any network) + optional API tunnel
 *   npm run start:tunnel → same as start:share
 */
const { spawn, execSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const { getBestLanIp } = require('./networkUtils')

const mobileRoot = path.join(__dirname, '..')
const port = 8081

function loadEnvFile() {
  const env = { ...process.env }
  const envPath = path.join(mobileRoot, '.env')
  if (!fs.existsSync(envPath)) return env
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const i = trimmed.indexOf('=')
    if (i === -1) continue
    const key = trimmed.slice(0, i).trim()
    const val = trimmed.slice(i + 1).trim()
    env[key] = val
  }
  return env
}

function freePort(p) {
  try {
    const pids = execSync(`lsof -ti :${p}`, { encoding: 'utf8' }).trim()
    if (!pids) return
    execSync(`kill -9 ${pids.split('\n').join(' ')}`)
    console.log(`Freed port ${p}`)
  } catch {
    /* free */
  }
}

const useTunnel =
  process.argv.includes('--tunnel') || process.argv.includes('--share')
const ip = getBestLanIp()
const env = loadEnvFile()

if (useTunnel) {
  if (!env.NGROK_AUTHTOKEN) {
    console.error('\n── Multiple phones / different Wi‑Fi ──')
    console.error('1. Get free token: https://dashboard.ngrok.com/get-started/your-authtoken')
    console.error('2. Add to mobile/.env:  NGROK_AUTHTOKEN=your_token')
    console.error('3. Run:  npm run start:share\n')
    console.error('Same Wi‑Fi only? Use: npm run start\n')
    process.exit(1)
  }
  env.NGROK_AUTHTOKEN = env.NGROK_AUTHTOKEN
} else {
  freePort(8081)
  try {
    require('child_process').execSync('node scripts/syncApiIp.js', { cwd: mobileRoot, stdio: 'inherit' })
  } catch {
    console.warn('sync-api-ip skipped — set EXPO_PUBLIC_API_URL in mobile/.env manually')
  }
}

console.log('\n══════════════════════════════════════════════════════')
console.log('  Expo Go — connect phones')
console.log('══════════════════════════════════════════════════════')

if (useTunnel) {
  console.log('\n  MODE: TUNNEL (same QR works on every phone / any network)')
  console.log('  1. Open Expo Go → Scan QR (NOT iPhone Camera)')
  console.log('  2. For login/data, run in another terminal:')
  console.log('       npm run tunnel:api')
  console.log('     (exposes backend via ngrok; requires: brew install ngrok/ngrok/ngrok)')
} else {
  console.log('\n  MODE: LAN (all phones must join the SAME Wi‑Fi as this Mac)')
  console.log('  • Guest Wi‑Fi / AP isolation often blocks other phones — use start:share')
  console.log('  • Open Expo Go → Scan QR or Enter URL manually')
  if (ip) {
    console.log(`\n  Manual URL (type on each phone):  exp://${ip}:${port}`)
    console.log(`  API:  http://${ip}:8002  (run: npm run sync-api-ip)`)
  }
  console.log('\n  Other phones fail?  npm run start:share')
}

console.log('\n  Press s in terminal if it says "development build" → switch to Expo Go')
console.log('══════════════════════════════════════════════════════\n')

if (ip && !useTunnel) {
  env.REACT_NATIVE_PACKAGER_HOSTNAME = ip
  env.EXPO_PACKAGER_HOSTNAME = ip
}

const args = [
  'expo',
  'start',
  '--clear',
  '--go',
  useTunnel ? '--tunnel' : '--lan',
]

const child = spawn('npx', args, {
  stdio: 'inherit',
  cwd: mobileRoot,
  env,
  shell: false,
})
child.on('exit', (code) => process.exit(code ?? 0))
