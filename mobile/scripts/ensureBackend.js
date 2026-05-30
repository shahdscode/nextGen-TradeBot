#!/usr/bin/env node
const http = require('http')
const path = require('path')
const { execSync } = require('child_process')

const repoRoot = path.join(__dirname, '..', '..')
const script = path.join(repoRoot, 'scripts', 'start-backend-only.sh')

function healthOk() {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:8002/health', { timeout: 3000 }, (res) => {
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

async function waitForApi(attempts = 30) {
  for (let i = 0; i < attempts; i++) {
    if (await healthOk()) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

/** Start FastAPI if needed (never kills Metro :8081). */
async function ensureBackend() {
  if (await healthOk()) return

  console.log('\n  Starting backend API on :8002...')
  try {
    execSync(`bash "${script}"`, { stdio: 'inherit', cwd: repoRoot })
  } catch (e) {
    throw new Error(
      'Could not start backend. From repo root run:\n' +
      '  python3.11 -m venv .venv && pip install -r requirements.txt\n' +
      '  ./scripts/start-backend-only.sh',
    )
  }

  if (!(await waitForApi())) {
    throw new Error('Backend did not become healthy on port 8002')
  }
}

module.exports = { ensureBackend, healthOk }
