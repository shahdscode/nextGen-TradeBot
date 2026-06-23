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
const { getBestLanIp } = require('./networkUtils')

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

  // Cloudflare quick tunnels often return 530 when unreachable — fall back to LAN.
  if (api.kind === 'cloudflare') {
    console.warn('  ⚠ Cloudflare tunnel unreachable — falling back to LAN API (same Wi‑Fi)')
    try {
      await api.close()
    } catch {
      /* ignore */
    }
    restoreLanEnv()
    const ip = getBestLanIp()
    if (!ip) throw new Error('No LAN IP — connect Mac to Wi‑Fi or use npm run start:lan')
    return {
      url: `http://${ip}:${API_PORT}`,
      kind: 'lan',
      close: async () => {},
    }
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

function normalizeExpoUrl(url) {
  if (!url) return null
  const lan = getBestLanIp()
  if (lan && /127\.0\.0\.1|localhost/i.test(url)) {
    return `exp://${lan}:8081`
  }
  return url
}

async function waitForExpoUrl(maxMs = 120000) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    try {
      const manifest = await fetchManifest()
      const host =
        manifest?.extra?.expoClient?.hostUri ||
        manifest?.extra?.expoGo?.debuggerHost
      if (host) {
        const raw = host.startsWith('exp://') ? host : `exp://${host}`
        return normalizeExpoUrl(raw)
      }
    } catch {
      /* Metro still starting */
    }
    await new Promise((r) => setTimeout(r, 2500))
  }
  const lan = getBestLanIp()
  return lan ? `exp://${lan}:8081` : null
}

function writeSession(data) {
  fs.writeFileSync(SESSION_FILE, JSON.stringify({ ...data, updatedAt: new Date().toISOString() }, null, 2))
}

function printBanner(api, expoUrl, mode = 'tunnel') {
  console.log('\n╔══════════════════════════════════════════════════════════╗')
  console.log('  PHONE: Open Expo Go → Scan QR below (or Enter URL manually)')
  console.log('╠══════════════════════════════════════════════════════════╣')
  if (expoUrl) {
    console.log(`  Expo URL:  ${expoUrl}`)
    if (mode === 'lan') {
      console.log('  Mode:      LAN — phone must be on the SAME Wi‑Fi as this Mac')
    }
  } else {
    console.log('  Expo URL:  (wait for QR — look for "Tunnel ready" below)')
  }
  console.log(`  API:       ${api.url}  (${api.kind})`)
  console.log('  Login:     admin / admin123')
  console.log('  Keep this terminal OPEN while testing.')
  console.log('╠══════════════════════════════════════════════════════════╣')
  if (mode === 'lan') {
    console.log('  ngrok Expo tunnel failed — using LAN for Metro bundle.')
    console.log('  API still uses Cloudflare (works on any network).')
  }
  console.log('  "Something went wrong" on phone?')
  console.log('    1. Update Expo Go (must support SDK 54)')
  console.log('    2. Expo Go → Profile → Clear cache')
  console.log('    3. Force-quit Expo Go, scan QR again')
  console.log('╚══════════════════════════════════════════════════════════╝\n')
}

function spawnExpo(env, mode) {
  const lan = getBestLanIp()
  if (lan) {
    env.REACT_NATIVE_PACKAGER_HOSTNAME = lan
    env.EXPO_PACKAGER_HOSTNAME = lan
    env.EXPO_DEV_SERVER_LISTEN_ADDRESS = '0.0.0.0'
  }
  const args =
    mode === 'lan'
      ? ['expo', 'start', '--go', '--lan', '-p', '8081', '--clear']
      : ['expo', 'start', '--go', '--tunnel', '-p', '8081', '--clear']
  return spawn('npx', args, { stdio: 'inherit', cwd: mobileRoot, env, shell: false })
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
  if (api.kind === 'lan') {
    // restoreLanEnv() already ran inside startApiTunnelWithRetry
    console.log(`  ✓ API (${api.kind}): ${api.url}`)
  } else {
    writeEnvRemoteMode(api.url, token)
    console.log(`  ✓ API tunnel (${api.kind}): ${api.url}`)
  }

  killStaleNgrok()

  const env = {
    ...process.env,
    NGROK_AUTHTOKEN: token,
    EXPO_PUBLIC_API_URL: api.url,
    EXPO_PUBLIC_FORCE_TUNNEL: api.kind === 'lan' ? '0' : '1',
  }

  console.log('\n  Starting Expo tunnel (30–60s)...')

  // EXPO_NO_TYPESCRIPT_SETUP avoids extra transforms; tunnel mode for any network.
  env.EXPO_NO_TYPESCRIPT_SETUP = '1'

  let expoMode = 'tunnel'
  let lanFallbackUsed = false
  let child = spawnExpo(env, expoMode)

  let cleaned = false
  let healthTimer = null
  let bannerTimer = null

  const scheduleBanner = () => {
    if (bannerTimer) clearTimeout(bannerTimer)
    bannerTimer = setTimeout(async () => {
      const expoUrl = await waitForExpoUrl(30000)
      writeSession({ apiUrl: api.url, apiKind: api.kind, expoUrl, expoMode })
      printBanner(api, expoUrl, expoMode)
    }, 8000)
  }

  scheduleBanner()

  const cleanup = async () => {
    if (cleaned) return
    cleaned = true
    if (healthTimer) clearInterval(healthTimer)
    if (bannerTimer) clearTimeout(bannerTimer)
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

  const attachChild = (proc) => {
    proc.on('exit', async (code) => {
      if (code !== 0 && !lanFallbackUsed && expoMode === 'tunnel') {
        lanFallbackUsed = true
        expoMode = 'lan'
        freePort(8081)
        console.error('\n  ⚠ Expo ngrok tunnel failed — falling back to LAN Metro')
        console.error('  Phone must join the SAME Wi‑Fi. API tunnel stays on Cloudflare.\n')
        child = spawnExpo(env, 'lan')
        scheduleBanner()
        attachChild(child)
        return
      }
      await cleanup()
      if (code !== 0 && expoMode === 'tunnel') {
        console.error('\n  Expo tunnel failed. Run: npm run doctor')
        console.error('  Same Wi‑Fi? Try: npm run start:lan')
        console.error('  New ngrok token: npm run setup\n')
      }
      process.exit(code ?? 0)
    })
  }

  attachChild(child)

  healthTimer = setInterval(async () => {
    const ok = await probeTunnelUrl(api.url, 1)
    if (!ok) {
      console.warn('\n  ⚠ API tunnel dropped — press Ctrl+C and run: npm start\n')
    }
  }, 90000)

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
