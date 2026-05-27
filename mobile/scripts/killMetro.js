#!/usr/bin/env node
/** Free Metro/Expo ports only — never touch API port 8002. */
const { execSync } = require('child_process')

const METRO_PORTS = [8081, 19000, 19001]

for (const port of METRO_PORTS) {
  try {
    const out = execSync(`lsof -ti :${port}`, { encoding: 'utf8' }).trim()
    if (!out) continue
    for (const pid of out.split('\n').filter(Boolean)) {
      try {
        process.kill(Number(pid), 'SIGTERM')
        console.log(`Stopped process ${pid} on port ${port}`)
      } catch {
        /* already gone */
      }
    }
  } catch {
    /* port free */
  }
}

console.log('Metro ports cleared (8081). Run: npm run start')
