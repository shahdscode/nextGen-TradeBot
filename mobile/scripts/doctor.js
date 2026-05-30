#!/usr/bin/env node
/**
 * Diagnose why Expo Go cannot connect (LAN firewall, stale .env, Metro down).
 * Usage: npm run doctor
 */
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const http = require('http')
const { getBestLanIp } = require('./networkUtils')

const mobileRoot = path.join(__dirname, '..')
const envPath = path.join(mobileRoot, '.env')

function firewallEnabled() {
  try {
    const out = execSync(
      '/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate',
      { encoding: 'utf8' },
    )
    return /enabled/i.test(out) && !/disabled/i.test(out)
  } catch {
    return null
  }
}

function portOpen(host, port) {
  return new Promise((resolve) => {
    const req = http.get(`http://${host}:${port}/`, { timeout: 3000 }, (res) => {
      res.resume()
      resolve(res.statusCode >= 200 && res.statusCode < 500)
    })
    req.on('error', () => resolve(false))
    req.on('timeout', () => {
      req.destroy()
      resolve(false)
    })
  })
}

function readEnv() {
  if (!fs.existsSync(envPath)) return {}
  const out = {}
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const m = line.match(/^([A-Z_]+)=(.*)$/)
    if (m) out[m[1]] = m[2].trim()
  }
  return out
}

async function main() {
  const ip = getBestLanIp()
  const env = readEnv()
  const fw = firewallEnabled()
  const metroLocal = await portOpen('127.0.0.1', 8081)
  const metroLan = ip ? await portOpen(ip, 8081) : false
  const apiLocal = await portOpen('127.0.0.1', 8002)

  console.log('\n══ Expo Go connection doctor ══\n')
  console.log('LAN IP:     ', ip || '(not found — connect Mac to Wi‑Fi)')
  console.log('Metro :8081: ', metroLocal ? 'running' : 'NOT running → npm run start')
  console.log('API   :8002: ', apiLocal ? 'running' : 'NOT running → ../scripts/start-all.sh')
  console.log('Firewall:   ', fw === null ? 'unknown' : fw ? 'ON (often blocks phones on LAN)' : 'off')
  console.log('.env API:    ', env.EXPO_PUBLIC_API_URL || '(unset)')
  console.log('Force tunnel:', env.EXPO_PUBLIC_FORCE_TUNNEL || '0')

  let issues = 0

  if (!metroLocal) {
    issues++
    console.log('\n✗ Metro is not running. Start it and keep the terminal open.')
  }

  if (!apiLocal) {
    issues++
    console.log('\n✗ Backend API is not running on port 8002.')
  }

  if (fw && ip && metroLocal) {
    issues++
    console.log('\n⚠ macOS Firewall is ON — phones often cannot reach Metro/API on LAN.')
    console.log('  Fix: System Settings → Network → Firewall → Options')
    console.log('       Allow incoming connections for **Node** (or turn Firewall off briefly to test).')
    console.log('  Or skip LAN entirely:  npm run start:remote')
  }

  if (env.EXPO_PUBLIC_API_URL?.includes('loca.lt') && env.EXPO_PUBLIC_FORCE_TUNNEL !== '1') {
    issues++
    console.log('\n⚠ Stale tunnel URL in .env (loca.lt) but not in remote mode.')
    console.log('  Fix: npm run sync-api-ip && npm run start')
  }

  if (env.EXPO_PUBLIC_FORCE_TUNNEL === '1' && !metroLocal) {
    console.log('\n  Remote .env is set but Metro is down — run: npm run start:remote')
  }

  console.log('\n── What to run ──\n')
  console.log('  One command (any network, recommended):')
  console.log('    npm run setup    # once — ngrok token + cloudflared')
  console.log('    npm start        # auto backend + tunnels + QR')
  console.log('  Same Wi‑Fi only (firewall off): npm run start:lan\n')

  console.log('  Expo Go must be updated (supports SDK 54).')
  console.log('  Scan inside Expo Go — not a screenshot of an old QR.\n')

  process.exit(issues > 0 ? 1 : 0)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
