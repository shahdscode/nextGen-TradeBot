#!/usr/bin/env node
/** Expose backend :8002 on a public URL (keeps running). */
const { writeEnvRemoteMode, loadNgrokToken } = require('./ngrokEnv')
const { startApiTunnel } = require('./tunnelLib')

async function main() {
  const token = loadNgrokToken()
  console.log('Opening API tunnel...')
  const api = await startApiTunnel()
  writeEnvRemoteMode(api.url, token || 'localtunnel')
  console.log(`\nAPI (${api.kind}): ${api.url}`)
  console.log('Keep this terminal open. In another: npm run share\n')

  const shutdown = async () => {
    await api.close()
    process.exit(0)
  }
  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)
}

main().catch((e) => {
  console.error(e.message || e)
  process.exit(1)
})
