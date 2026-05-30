#!/usr/bin/env node
/**
 * One command for physical phones — works with macOS firewall, any Wi‑Fi, mobile data.
 *
 *   cd mobile && npm start
 *
 * Starts backend (if needed), Cloudflare/ngrok API tunnel, Expo ngrok Metro tunnel.
 * Keep this terminal open while using Expo Go.
 */
const fs = require('fs')
const http = require('http')
const path = require('path')
const { spawn, execSync } = require('child_process')
const { ensureBackend } = require('./ensureBackend')
const { ensureCloudflared } = require('./ensureCloudflared')
const { mobileRoot, requireToken, writeEnvRemoteMode, restoreLanEnv } = require('./ngrokEnv')
const { startApiTunnel, probeTunnelUrl, API_PORT } = require('./tunnelLib')

const SESSION_FILE = path.join(mobileRoot, '.dev-session.json')

function freePort(p) {
  try {
    const pids = execSync(`lsof -ti :${p}`, { encoding: 'utf8' }).trim()
    if (pids) execSync(`kill -9 ${pids.split('\n').join(' ')}`)
  } catch {
    /* free */
  }
}

function killStaleNgrok() {
  for (const name of ['ngrok', 'ngrok.exe']) {
    try {
      execSync(`pkill -f "${name}" 2>/dev/null || true`, { shell: true })
    } catch {
      /* ignore */
    }
  }
}

async function verifyNgrokToken(token) {
  try {
    const ngrok = require('@ngrok/ngrok')
    const listener = await ngrok.forward({ addr: 19998, authtoken: token })
    const url = listener.url()
    await listener.close()
    return url ? true : false
  } catch (e) {
    const msg = String(e.message || e)
    if (msg.includes('ERR_NGROK_316') || msg.includes('ACL policy')) return 'warn'
    console.error('\n  ✗ ngrok token check failed:', msg)
    return false
  }
}

async function startApiTunnelWithRetry() {
  let api = null
  try {
    api = await startApiTunnel({ reserveNgrokForExpo: true })
  } catch (e) {
    throw new Error(`API tunnel failed: ${e.message || e}`)
  }

  const warmupMs = api.kind === 'cloudflare' ? 12000 : 3000
  console.log(`  Warming up ${api.kind} tunnel (${warmupMs / 1000}s)…`)
  await new Promise((r) => setTimeout(r, warmupMs))

  if (await probeTunnelUrl(api.url, 6)) {
    return api
  }

  // Cloudflare quick tunnels often need extra time; backend is still local.
  if (api.kind === 'cloudflare') {
    console.warn('  ⚠ Cloudflare probe slow — continuing (tap Retry on login if needed)')
    return api
  }

  try {
    await api.close()
  } catch {
    /* ignore */
  }

  const lt = await startApiTunnel({ reserveNgrokForExpo: true })
  await new Promise((r) => setTimeout(r, 4000))
  if (await probeTunnelUrl(lt.url, 4)) return lt

  if (lt.kind === 'localtunnel') {
    console.warn('  ⚠ localtunnel probe slow — continuing anyway')
    return lt
  }

  await lt.close()
  throw new Error('Could not open a stable API tunnel')
}

function fetchManifest() {
  return new Promise((resolve, reject) => {
    http
      .get('http://127.0.0.1:8081/', { timeout: 5000 }, (res) => {
        let body = ''
        res.on('data', (c) => {
          body += c
        })
        res.on('end', () => {
          try {
            resolve(JSON.parse(body))
          } catch (e) {
            reject(e)
          }
        })
      })
      .on('error', reject)
  })
}

async function waitForExpoUrl(maxMs = 120000) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    try {
      const manifest = await fetchManifest()
      const host =
        manifest?.extra?.expoClient?.hostUri ||
        manifest?.extra?.expoGo?.debuggerHost
      if (host) return `exp://${host.replace(/^exp:\/\//, '')}`
    } catch {
      /* Metro still starting */
    }
    await new Promise((r) => setTimeout(r, 2500))
  }
  return null
}

function writeSession(data) {
  fs.writeFileSync(SESSION_FILE, JSON.stringify({ ...data, updatedAt: new Date().toISOString() }, null, 2))
}

function printBanner(api, expoUrl) {
  console.log('\n╔══════════════════════════════════════════════════════════╗')
  console.log('  PHONE: Open Expo Go → Scan QR below (or Enter URL manually)')
  console.log('╠══════════════════════════════════════════════════════════╣')
  if (expoUrl) {
    console.log(`  Expo URL:  ${expoUrl}`)
  } else {
    console.log('  Expo URL:  (wait for QR — look for "Tunnel ready" below)')
  }
  console.log(`  API:       ${api.url}  (${api.kind})`)
  console.log('  Login:     admin / admin123')
  console.log('  Keep this terminal OPEN while testing.')
  console.log('╠══════════════════════════════════════════════════════════╣')
  console.log('  "Something went wrong" on phone?')
  console.log('    1. Update Expo Go (must support SDK 54)')
  console.log('    2. Expo Go → Profile → Clear cache')
  console.log('    3. Force-quit Expo Go, scan QR again')
  console.log('╚══════════════════════════════════════════════════════════╝\n')
}

function clearExpoCache() {
  for (const dir of ['.expo', path.join('node_modules', '.cache')]) {
    try {
      fs.rmSync(path.join(mobileRoot, dir), { recursive: true, force: true })
    } catch {
      /* ignore */
    }
  }
}

async function main() {
  const token = requireToken()

  console.log('\n══ NextGen TradeBot — mobile dev (auto) ══\n')

  clearExpoCache()

  await ensureBackend()
  ensureCloudflared()

  freePort(8081)
  killStaleNgrok()

  console.log('  Checking ngrok token (Expo tunnel)...')
  const tokenOk = await verifyNgrokToken(token)
  if (tokenOk === false) {
    console.error('\n  Run once:  npm run setup\n')
    process.exit(1)
  }
  if (tokenOk === 'warn') {
    console.log('  ⚠ ngrok ACL warning — if Expo tunnel fails, get a new token: npm run setup')
  } else {
    console.log('  ✓ ngrok token OK')
  }

  console.log('\n  Opening API tunnel (Cloudflare preferred)...')
  const api = await startApiTunnelWithRetry()
  writeEnvRemoteMode(api.url, token)
  console.log(`  ✓ API tunnel (${api.kind}): ${api.url}`)

  killStaleNgrok()

  const env = {
    ...process.env,
    NGROK_AUTHTOKEN: token,
    EXPO_PUBLIC_API_URL: api.url,
    EXPO_PUBLIC_FORCE_TUNNEL: '1',
  }

  console.log('\n  Starting Expo tunnel (30–60s)...')

  // EXPO_NO_TYPESCRIPT_SETUP avoids extra transforms; tunnel mode for any network.
  env.EXPO_NO_TYPESCRIPT_SETUP = '1'

  const child = spawn(
    'npx',
    ['expo', 'start', '--go', '--tunnel', '-p', '8081', '--clear'],
    { stdio: 'inherit', cwd: mobileRoot, env, shell: false },
  )

  let cleaned = false
  let healthTimer = null

  const cleanup = async () => {
    if (cleaned) return
    cleaned = true
    if (healthTimer) clearInterval(healthTimer)
    try {
      await api.close()
    } catch {
      /* ignore */
    }
    try {
      fs.unlinkSync(SESSION_FILE)
    } catch {
      /* ignore */
    }
    restoreLanEnv()
  }

  setTimeout(async () => {
    const expoUrl = await waitForExpoUrl()
    writeSession({ apiUrl: api.url, apiKind: api.kind, expoUrl })
    printBanner(api, expoUrl)
  }, 8000)

  healthTimer = setInterval(async () => {
    const ok = await probeTunnelUrl(api.url, 1)
    if (!ok) {
      console.warn('\n  ⚠ API tunnel dropped — press Ctrl+C and run: npm start\n')
    }
  }, 90000)

  child.on('exit', async (code) => {
    await cleanup()
    if (code !== 0) {
      console.error('\n  Expo tunnel failed. Run: npm run doctor')
      console.error('  New ngrok token: npm run setup\n')
    }
    process.exit(code ?? 0)
  })

  process.on('SIGINT', async () => {
    child.kill('SIGINT')
    await cleanup()
    process.exit(0)
  })
}

if (require.main === module) {
  main().catch((e) => {
    console.error('\n', e.message || e)
    console.error('\n  Try: npm run setup && npm start\n')
    process.exit(1)
  })
}

module.exports = { main }
