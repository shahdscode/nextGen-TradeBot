const { spawn, execSync } = require('child_process')
const http = require('http')
const https = require('https')
const { loadNgrokToken } = require('./ngrokEnv')

const API_PORT = 8002

function tunnelRequestOptions(url) {
  const headers = { 'User-Agent': 'NextGenTradeBot-Mobile' }
  if (url.includes('loca.lt')) {
    headers['Bypass-Tunnel-Reminder'] = 'true'
    headers['bypass-tunnel-reminder'] = 'true'
  }
  return headers
}

/** Probe public API tunnel (with retries). */
function probeTunnelUrl(url, attempts = 2) {
  const target = `${url.replace(/\/$/, '')}/health`
  const lib = target.startsWith('https') ? https : http
  const headers = tunnelRequestOptions(url)

  const once = () =>
    new Promise((resolve) => {
      const req = lib.get(target, { timeout: 20000, headers }, (res) => {
        res.resume()
        resolve(res.statusCode === 200)
      })
      req.on('error', () => resolve(false))
      req.on('timeout', () => {
        req.destroy()
        resolve(false)
      })
    })

  return (async () => {
    for (let i = 0; i < attempts; i++) {
      if (await once()) return true
      await new Promise((r) => setTimeout(r, 2000))
    }
    return false
  })()
}

function startCloudflaredTunnel() {
  let bin = null
  try {
    bin = execSync('command -v cloudflared', { encoding: 'utf8' }).trim()
  } catch {
    return null
  }
  if (!bin) return null

  return new Promise((resolve) => {
    const child = spawn(bin, ['tunnel', '--url', `http://127.0.0.1:${API_PORT}`], {
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let settled = false
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true
        try {
          child.kill()
        } catch {
          /* ignore */
        }
        resolve(null)
      }
    }, 60000)

    const onData = (chunk) => {
      const text = chunk.toString()
      const m =
        text.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/i) ||
        text.match(/trycloudflare\.com[^\n]*https:\/\/[a-z0-9-]+\.trycloudflare\.com/i)
      const url = m
        ? (m[0].match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/i) || [])[0]
        : null
      if (url && !settled) {
        settled = true
        clearTimeout(timeout)
        resolve({
          url,
          kind: 'cloudflare',
          close: () =>
            new Promise((r) => {
              try {
                child.kill('SIGTERM')
              } catch {
                /* ignore */
              }
              r()
            }),
        })
      }
    }
    child.stdout.on('data', onData)
    child.stderr.on('data', onData)
    child.on('exit', () => {
      if (!settled) {
        settled = true
        clearTimeout(timeout)
        resolve(null)
      }
    })
  })
}

/**
 * Public URL for the FastAPI backend.
 * @param {{ reserveNgrokForExpo?: boolean }} opts
 */
async function startApiTunnel(opts = {}) {
  const { reserveNgrokForExpo = false } = opts
  const token = loadNgrokToken()

  if (!reserveNgrokForExpo && token) {
    try {
      const ngrok = require('@ngrok/ngrok')
      const listener = await ngrok.forward({ addr: API_PORT, authtoken: token })
      const url = listener.url()
      if (url) {
        return {
          url,
          kind: 'ngrok',
          close: async () => listener.close(),
        }
      }
    } catch {
      /* try v4 */
    }

    try {
      const ngrok = require('ngrok')
      const url = await ngrok.connect({ addr: API_PORT, authtoken: token, proto: 'http' })
      if (url) {
        return {
          url,
          kind: 'ngrok',
          close: async () => {
            await ngrok.disconnect()
            await ngrok.kill()
          },
        }
      }
    } catch {
      /* fall through */
    }
  }

  const cf = await startCloudflaredTunnel()
  if (cf) return cf

  const lt = require('localtunnel')
  const tunnel = await lt({ port: API_PORT })
  return {
    url: tunnel.url,
    kind: 'localtunnel',
    close: () =>
      new Promise((resolve) => {
        tunnel.close()
        resolve()
      }),
  }
}

module.exports = { startApiTunnel, probeTunnelUrl, API_PORT, tunnelRequestOptions }
