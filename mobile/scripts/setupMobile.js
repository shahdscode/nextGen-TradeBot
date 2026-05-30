#!/usr/bin/env node
/**
 * One-time mobile setup: deps, ngrok token, cloudflared.
 * Usage: npm run setup
 */
const fs = require('fs')
const path = require('path')
const { execSync } = require('child_process')
const readline = require('readline')
const { ensureCloudflared } = require('./ensureCloudflared')

const mobileRoot = path.join(__dirname, '..')
const envPath = path.join(mobileRoot, '.env')
const examplePath = path.join(mobileRoot, '.env.example')

function question(prompt) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout })
  return new Promise((resolve) => {
    rl.question(prompt, (ans) => {
      rl.close()
      resolve(ans.trim())
    })
  })
}

function loadEnvText() {
  if (fs.existsSync(envPath)) return fs.readFileSync(envPath, 'utf8')
  if (fs.existsSync(examplePath)) return fs.readFileSync(examplePath, 'utf8')
  return ''
}

function upsertEnv(key, value) {
  let body = loadEnvText()
  const line = `${key}=${value}`
  if (new RegExp(`^${key}=`, 'm').test(body)) {
    body = body.replace(new RegExp(`^${key}=.*$`, 'm'), line)
  } else {
    body = `${line}\n${body}`
  }
  fs.writeFileSync(envPath, body)
}

async function main() {
  console.log('\n══ Mobile setup (one time) ══\n')

  console.log('Installing npm packages...')
  execSync('npm install', { cwd: mobileRoot, stdio: 'inherit' })

  let token = ''
  if (fs.existsSync(envPath)) {
    const m = fs.readFileSync(envPath, 'utf8').match(/^NGROK_AUTHTOKEN=(\S+)/m)
    if (m) token = m[1]
  }

  if (!token) {
    console.log('\nExpo tunnel needs a free ngrok token:')
    console.log('  https://dashboard.ngrok.com/get-started/your-authtoken\n')
    const pasted = await question('Paste NGROK_AUTHTOKEN (required): ')
    if (!pasted) {
      console.error('\nToken required. Re-run: npm run setup\n')
      process.exit(1)
    }
    token = pasted
  }

  upsertEnv('NGROK_AUTHTOKEN', token)
  console.log('  ✓ Saved NGROK_AUTHTOKEN to .env')

  ensureCloudflared()

  console.log('\nDone. Start the app on any phone with:\n')
  console.log('  npm start\n')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
