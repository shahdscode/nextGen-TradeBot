#!/usr/bin/env node
/** Writes current Mac Wi‑Fi IP into mobile/.env for EXPO_PUBLIC_API_URL */
const fs = require('fs')
const path = require('path')
const { getBestLanIp } = require('./networkUtils')

const ip = getBestLanIp()
if (!ip) {
  console.error('No LAN IP found. Connect Mac to Wi‑Fi first.')
  process.exit(1)
}

const envPath = path.join(__dirname, '..', '.env')
let existing = ''
if (fs.existsSync(envPath)) {
  existing = fs.readFileSync(envPath, 'utf8')
}

const tokenLine = existing.match(/^NGROK_AUTHTOKEN=.+$/m)
const lines = [
  '# Auto-synced LAN API (phones on same Wi‑Fi as Mac)',
  '# Do NOT use loca.lt here for same-Wi‑Fi — use npm run start:share for tunnels',
  `EXPO_PUBLIC_API_URL=http://${ip}:8002`,
  'EXPO_PUBLIC_FORCE_TUNNEL=0',
  tokenLine ? tokenLine[0] : '# NGROK_AUTHTOKEN=  # for npm run start:share',
  '',
]
fs.writeFileSync(envPath, lines.join('\n'))
console.log('Updated', envPath)
console.log(`EXPO_PUBLIC_API_URL=http://${ip}:8002`)
