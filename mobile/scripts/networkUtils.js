#!/usr/bin/env node
/** Pick the Mac Wi‑Fi/LAN IP phones should use (not Docker/VPN). */
const os = require('os')
const { execSync } = require('child_process')

/** Any RFC1918 private IPv4 (no Docker filtering — used for physical interfaces). */
function isPrivateIPv4(ip) {
  if (!ip || ip === '127.0.0.1') return false
  if (ip.startsWith('169.254.')) return false
  if (ip.startsWith('192.168.')) return true
  if (ip.startsWith('10.')) return true
  const m = ip.match(/^172\.(\d+)\./)
  if (m) {
    const n = Number(m[1])
    return n >= 16 && n <= 31 // includes 172.20.10.x (iOS Personal Hotspot)
  }
  return false
}

/**
 * Conservative filter for the "enumerate every interface" fallback, where Docker
 * virtual bridges appear. The iOS Personal Hotspot subnet (172.20.10.x) is always
 * allowed; the common Docker bridges (172.17.x / 172.18.x) are excluded.
 */
function isUsableLanIp(ip) {
  if (!isPrivateIPv4(ip)) return false
  if (ip.startsWith('172.20.10.')) return true // iOS Personal Hotspot
  if (ip.startsWith('172.17.') || ip.startsWith('172.18.')) return false // Docker
  return true
}

function ipFromIfconfig(iface) {
  try {
    // `ipconfig getifaddr` only returns a physical interface's IP (never a Docker
    // bridge), so any private IP here is trustworthy — including 172.20.10.x.
    const ip = execSync(`ipconfig getifaddr ${iface}`, { encoding: 'utf8' }).trim()
    return isPrivateIPv4(ip) ? ip : null
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
