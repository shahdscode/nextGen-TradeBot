#!/usr/bin/env node
const { loadNgrokToken, persistEnv, envPath } = require('./ngrokEnv')

const token = loadNgrokToken()
if (!token) {
  console.error('No ngrok token found.')
  console.error('Add NGROK_AUTHTOKEN to mobile/.env or run Expo tunnel once (saves ~/.expo/ngrok.yml)')
  process.exit(1)
}
persistEnv(token)
console.log('OK —', envPath, 'now has NGROK_AUTHTOKEN')
console.log('Run: npm run verify:ngrok && npm run start:remote')
