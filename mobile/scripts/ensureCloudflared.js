#!/usr/bin/env node
const { execSync } = require('child_process')

function hasCloudflared() {
  try {
    execSync('command -v cloudflared', { encoding: 'utf8', stdio: 'pipe' })
    return true
  } catch {
    return false
  }
}

function hasBrew() {
  try {
    execSync('command -v brew', { encoding: 'utf8', stdio: 'pipe' })
    return true
  } catch {
    return false
  }
}

/** Prefer cloudflared over loca.lt for API tunnel stability. */
function ensureCloudflared() {
  if (hasCloudflared()) {
    return true
  }

  console.log('\n  cloudflared not found — API tunnel will use localtunnel (less reliable).')
  if (!hasBrew()) {
    console.log('  Install for best results: brew install cloudflared')
    console.log('  https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/\n')
    return false
  }

  console.log('  Installing cloudflared via Homebrew (one-time)...')
  try {
    execSync('brew install cloudflared', { stdio: 'inherit' })
    return hasCloudflared()
  } catch {
    console.warn('  brew install cloudflared failed — continuing with fallback tunnel.\n')
    return false
  }
}

module.exports = { ensureCloudflared, hasCloudflared }
