#!/usr/bin/env node
/** Pick the Mac Wi‑Fi/LAN IP phones should use (not Docker/VPN). */
const os = require('os')
const { execSync } = require('child_process')

function isUsableLanIp(ip) {
  if (!ip || ip === '127.0.0.1') return false
  if (ip.startsWith('169.254.')) return false
  if (ip.startsWith('192.168.')) return true
  if (ip.startsWith('10.')) return true
  const m = ip.match(/^172\.(\d+)\./)
  if (m) {
    const n = Number(m[1])
    // Docker Desktop often uses 172.17–172.31
    if (n >= 17 && n <= 31) return false
    return true
  }
  return false
}

function ipFromIfconfig(iface) {
  try {
    const ip = execSync(`ipconfig getifaddr ${iface}`, { encoding: 'utf8' }).trim()
    return isUsableLanIp(ip) ? ip : null
  } catch {
    return null
  }
}

function getBestLanIp() {
  for (const iface of ['en0', 'en1', 'wlan0', 'eth0']) {
    const ip = ipFromIfconfig(iface)
    if (ip) return ip
  }

  let nets = {}
  try {
    nets = os.networkInterfaces()
  } catch {
    return null
  }
  for (const name of ['en0', 'en1', 'wlan0', 'eth0']) {
    for (const addr of nets[name] || []) {
      if (addr.family === 'IPv4' && !addr.internal && isUsableLanIp(addr.address)) {
        return addr.address
      }
    }
  }

  for (const ifaces of Object.values(nets)) {
    for (const addr of ifaces || []) {
      if (addr.family === 'IPv4' && !addr.internal && isUsableLanIp(addr.address)) {
        return addr.address
      }
    }
  }
  return null
}

module.exports = { getBestLanIp, isUsableLanIp }
