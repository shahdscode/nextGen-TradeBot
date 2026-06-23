#!/usr/bin/env node
/**
 * One command to run the whole mobile stack on the local network:
 *
 *   cd mobile && npm start        (or from repo root: ./scripts/mobile-dev.sh)
 *
 * It (1) starts the FastAPI backend on :8002 if it is not already running,
 * (2) points the app at this Mac's LAN IP, and (3) starts Expo in LAN mode,
 * which prints the QR code. Scan it with Expo Go on a phone joined to the SAME
 * Wi-Fi. No ngrok/tunnel account required.
 *
 * For off-network access (mobile data / different Wi-Fi) use the tunnel runner:
 *   npm run start:tunnel
 */
const { spawn, execSync } = require('child_process')
const path = require('path')
const { ensureBackend } = require('./ensureBackend')
const { getBestLanIp } = require('./networkUtils')

const mobileRoot = path.join(__dirname, '..')
const API_PORT = 8002
const METRO_PORT = 8081

function freePort(p) {
  try {
    const pids = execSync(`lsof -ti :${p}`, { encoding: 'utf8' }).trim()
    if (pids) execSync(`kill -9 ${pids.split('\n').join(' ')}`)
  } catch {
    /* nothing to free */
  }
}

async function main() {
  console.log('\n══ NextGen TradeBot — mobile dev (LAN) ══\n')

  // 1) Backend
  await ensureBackend()
  console.log(`  ✓ Backend healthy on :${API_PORT}`)

  // 2) LAN IP for both the API and the Metro bundler
  const ip = getBestLanIp()
  if (!ip) {
    console.error(
      '\n  ✗ No LAN IP found. Connect this Mac to Wi-Fi and retry.\n' +
        '    (For mobile data / different network, use: npm run start:tunnel)\n',
    )
    process.exit(1)
  }
  const apiUrl = `http://${ip}:${API_PORT}`
  console.log(`  ✓ LAN IP: ${ip}`)
  console.log(`  ✓ API URL the phone will use: ${apiUrl}`)

  // 3) Expo (LAN) — prints the QR itself via inherited stdio
  freePort(METRO_PORT)

  const env = {
    ...process.env,
    EXPO_PUBLIC_API_URL: apiUrl,
    EXPO_PUBLIC_FORCE_TUNNEL: '0',
    REACT_NATIVE_PACKAGER_HOSTNAME: ip,
    EXPO_PACKAGER_HOSTNAME: ip,
    EXPO_DEV_SERVER_LISTEN_ADDRESS: '0.0.0.0',
    EXPO_NO_TYPESCRIPT_SETUP: '1',
  }

  console.log('\n╔═══════════════════════════════════╗')
  console.log('  PHONE: open Expo Go → scan the QR code printed below')
  console.log('  Phone and Mac must be on the SAME Wi-Fi network')
  console.log('  Login:  admin / admin123')
  console.log('  Keep this terminal OPEN while testing. Ctrl+C to stop.')
  console.log('╚═══════════════════════════════════╝\n')

  const child = spawn(
    'npx',
    ['expo', 'start', '--go', '--lan', '-p', String(METRO_PORT), '--clear'],
    { stdio: 'inherit', cwd: mobileRoot, env, shell: false },
  )

  const stop = () => {
    try {
      child.kill('SIGINT')
    } catch {
      /* ignore */
    }
  }
  process.on('SIGINT', () => {
    stop()
    process.exit(0)
  })
  child.on('exit', (code) => process.exit(code ?? 0))
}

if (require.main === module) {
  main().catch((e) => {
    console.error('\n  Error:', e.message || e)
    console.error('  Backend setup: from repo root run ./scripts/start-backend-only.sh\n')
    process.exit(1)
  })
}

module.exports = { main }
