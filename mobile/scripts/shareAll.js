#!/usr/bin/env node
/**
 * Remote mode — any phone on any network:
 *   • API via localtunnel (keeps ngrok free for Expo)
 *   • Expo Metro via ngrok tunnel (NGROK_AUTHTOKEN required)
 *
 * Usage: npm run start:remote
 */
const http = require('http')
const { spawn, execSync } = require('child_process')
const { mobileRoot, requireToken, writeEnvRemoteMode, restoreLanEnv } = require('./ngrokEnv')
const { startApiTunnel } = require('./tunnelLib')

function freePort(p) {
  try {
    const pids = execSync(`lsof -ti :${p}`, { encoding: 'utf8' }).trim()
    if (pids) execSync(`kill -9 ${pids.split('\n').join(' ')}`)
  } catch {
    /* free */
  }
}

/** Stale ngrok agents break Expo tunnel ("remote gone away"). */
function killStaleNgrok() {
  for (const name of ['ngrok', 'ngrok.exe']) {
    try {
      execSync(`pkill -f "${name}" 2>/dev/null || true`, { shell: true })
    } catch {
      /* ignore */
    }
  }
}

function waitForApi(port = 8002, attempts = 20) {
  return new Promise((resolve, reject) => {
    let n = 0
    const tick = () => {
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        res.resume()
        if (res.statusCode === 200) resolve()
        else if (++n >= attempts) reject(new Error('API health check failed'))
        else setTimeout(tick, 500)
      })
      req.on('error', () => {
        if (++n >= attempts) {
          reject(new Error(
            `Backend not running on port ${port}. Start it first:\n` +
            '  cd .. && ./scripts/start-all.sh',
          ))
        } else setTimeout(tick, 500)
      })
      req.setTimeout(2000, () => req.destroy())
    }
    tick()
  })
}

async function probeTunnel(url) {
  return new Promise((resolve) => {
    const lib = url.startsWith('https') ? require('https') : http
    const req = lib.get(`${url.replace(/\/$/, '')}/health`, { timeout: 15000 }, (res) => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.on('timeout', () => {
      req.destroy()
      resolve(false)
    })
  })
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
    if (msg.includes('ERR_NGROK_316') || msg.includes('ACL policy')) {
      return 'warn'
    }
    console.error('\n  ✗ ngrok token check failed:', msg)
    return false
  }
}

async function main() {
  const token = requireToken()
  freePort(8081)
  killStaleNgrok()

  console.log('\n══════════════════════════════════════════════════════')
  console.log('  Remote mode — ANY phone / ANY network')
  console.log('══════════════════════════════════════════════════════')

  console.log('\n  Verifying ngrok token (for Expo tunnel)...')
  const tokenOk = await verifyNgrokToken(token)
  if (tokenOk === false) {
    console.error('\n  Get a new token: https://dashboard.ngrok.com/get-started/your-authtoken')
    console.error('  Then: npm run sync:ngrok\n')
    process.exit(1)
  }
  if (tokenOk === 'warn') {
    console.log('  ⚠ ngrok token has ACL limits — continuing anyway')
  } else {
    console.log('  ✓ ngrok token OK')
  }

  console.log('\n  Checking backend on :8002...')
  await waitForApi()

  console.log('  Opening API tunnel (localtunnel — ngrok reserved for Expo)...')
  const api = await startApiTunnel({ reserveNgrokForExpo: true })
  writeEnvRemoteMode(api.url, token)

  let tunnelOk = await probeTunnel(api.url)
  if (!tunnelOk) {
    await new Promise((r) => setTimeout(r, 3000))
    tunnelOk = await probeTunnel(api.url)
  }
  if (!tunnelOk) {
    console.warn('\n  ⚠  API tunnel slow to respond — reload Expo Go after Metro starts')
  } else {
    console.log('  ✓ API reachable via tunnel')
  }

  console.log(`\n  API (${api.kind}): ${api.url}`)
  console.log('\n  Starting Expo ngrok tunnel (may take 30–60s)...')
  console.log('  Scan QR in Expo Go on each phone (NOT iPhone Camera)')
  console.log('\n  When done: Ctrl+C restores LAN .env for npm run start')
  console.log('══════════════════════════════════════════════════════\n')

  killStaleNgrok()

  const env = {
    ...process.env,
    NGROK_AUTHTOKEN: token,
    EXPO_PUBLIC_API_URL: api.url,
    EXPO_PUBLIC_FORCE_TUNNEL: '1',
  }

  const child = spawn(
    'npx',
    ['expo', 'start', '--clear', '--go', '--tunnel'],
    { stdio: 'inherit', cwd: mobileRoot, env, shell: false },
  )

  let cleaned = false
  const cleanup = async () => {
    if (cleaned) return
    cleaned = true
    try {
      await api.close()
    } catch {
      /* ignore */
    }
    restoreLanEnv()
  }

  child.on('exit', async (code) => {
    if (code !== 0) {
      console.error('\n══════════════════════════════════════════════════════')
      console.error('  Expo tunnel failed')
      console.error('══════════════════════════════════════════════════════')
      console.error('  Try:')
      console.error('    1. npm run verify:ngrok')
      console.error('    2. New token → npm run sync:ngrok')
      console.error('    3. Kill other ngrok apps / VPN off')
      console.error('    4. ACL error? New token at dashboard.ngrok.com → npm run sync:ngrok')
      console.error('    5. https://status.ngrok.com/')
      console.error('    6. npm run start:remote   (retry)\n')
    }
    await cleanup()
    process.exit(code ?? 0)
  })

  process.on('SIGINT', async () => {
    child.kill('SIGINT')
    await cleanup()
  })
}

main().catch((e) => {
  console.error(e.message || e)
  process.exit(1)
})
