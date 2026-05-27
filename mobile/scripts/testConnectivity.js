#!/usr/bin/env node
/**
 * Smoke-test API + Metro before opening Expo Go on a phone.
 * Usage: npm run test:connectivity
 */
const http = require('http')
const https = require('https')
const fs = require('fs')
const path = require('path')
const { getBestLanIp } = require('./networkUtils')

const mobileRoot = path.join(__dirname, '..')
const envPath = path.join(mobileRoot, '.env')

function loadApiUrl() {
  if (fs.existsSync(envPath)) {
    const m = fs.readFileSync(envPath, 'utf8').match(/^EXPO_PUBLIC_API_URL=(.+)$/m)
    if (m) return m[1].trim()
  }
  const ip = getBestLanIp()
  return ip ? `http://${ip}:8002` : 'http://127.0.0.1:8002'
}

function get(url, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith('https') ? https : http
    const req = lib.get(url, { timeout: timeoutMs }, (res) => {
      let body = ''
      res.on('data', (c) => { body += c })
      res.on('end', () => resolve({ status: res.statusCode, body }))
    })
    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy()
      reject(new Error('timeout'))
    })
  })
}

async function main() {
  const ip = getBestLanIp()
  const apiBase = loadApiUrl().replace(/\/$/, '')
  const metroUrl = ip ? `http://${ip}:8081/` : 'http://127.0.0.1:8081/'

  console.log('\n── Mobile connectivity test ──\n')
  console.log('LAN IP:    ', ip || '(none)')
  console.log('API URL:   ', apiBase)
  console.log('Metro URL: ', metroUrl)

  let failed = false

  for (const [name, url] of [
    ['API /health', `${apiBase}/health`],
    ['API /api/mobile/health', `${apiBase}/api/mobile/health`],
    ['API login', `${apiBase}/api/auth/login`],
    ['Metro bundler', metroUrl],
  ]) {
    try {
      const isLogin = url.includes('/login')
      if (isLogin) {
        const lib = url.startsWith('https') ? https : http
        const body = JSON.stringify({ username: 'admin', password: 'admin123' })
        const u = new URL(url)
        const res = await new Promise((resolve, reject) => {
          const req = lib.request(
            {
              hostname: u.hostname,
              port: u.port,
              path: u.pathname,
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Content-Length': body.length },
              timeout: 8000,
            },
            (r) => {
              let data = ''
              r.on('data', (c) => { data += c })
              r.on('end', () => resolve({ status: r.statusCode, body: data }))
            },
          )
          req.on('error', reject)
          req.write(body)
          req.end()
        })
        if (res.status === 200) {
          console.log(`✓ ${name} → 200`)
        } else {
          console.log(`✗ ${name} → ${res.status}`)
          failed = true
        }
      } else {
        const res = await get(url)
        if (res.status >= 200 && res.status < 400) {
          console.log(`✓ ${name} → ${res.status}`)
        } else {
          console.log(`✗ ${name} → ${res.status}`)
          failed = true
        }
      }
    } catch (e) {
      console.log(`✗ ${name} → ${e.message}`)
      failed = true
    }
  }

  if (/loca\.lt|ngrok/.test(apiBase)) {
    console.log('\n⚠  .env uses a tunnel URL. For same Wi‑Fi use: npm run sync-api-ip')
    failed = true
  }

  console.log('')
  if (failed) {
    console.log('Fix issues, then:')
    console.log('  ./scripts/start-all.sh          # API on :8002')
    console.log('  cd mobile && npm run sync-api-ip && npm run start')
    process.exit(1)
  }
  console.log('All checks passed. Open Expo Go → scan QR → exp://' + (ip || 'YOUR_IP') + ':8081')
  console.log('Login: admin / admin123\n')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
