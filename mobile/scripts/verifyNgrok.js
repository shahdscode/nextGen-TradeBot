#!/usr/bin/env node
/** Check NGROK_AUTHTOKEN (needed for Expo `start --tunnel`). */
const { loadNgrokToken } = require('./ngrokEnv')

async function main() {
  const token = loadNgrokToken()
  if (!token) {
    console.error('No NGROK_AUTHTOKEN. Run: npm run sync:ngrok')
    process.exit(1)
  }

  console.log('Checking ngrok token...')
  try {
    const ngrok = require('@ngrok/ngrok')
    const listener = await ngrok.forward({ addr: 19999, authtoken: token })
    const url = listener.url()
    await listener.close()
    if (url) {
      console.log('✓ ngrok token is valid')
      process.exit(0)
    }
  } catch (e) {
    const msg = String(e.message || e)
    if (msg.includes('ERR_NGROK_316') || msg.includes('ACL policy')) {
      console.warn('⚠ ngrok token has domain ACL limits (ERR_NGROK_316)')
      console.warn('  Expo tunnel may fail. Fix in ngrok dashboard:')
      console.warn('  https://dashboard.ngrok.com/domains')
      console.warn('  → create a new authtoken or allow ephemeral *.ngrok.app domains')
      console.warn('\n  Will still try npm run start:remote …')
      process.exit(0)
    }
    console.error('✗ ngrok token failed:', msg)
    console.error('\nFix:')
    console.error('  1. New token: https://dashboard.ngrok.com/get-started/your-authtoken')
    console.error('  2. npm run sync:ngrok')
    process.exit(1)
  }
}

main()
