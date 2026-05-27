#!/usr/bin/env node
const { getBestLanIp } = require('./networkUtils')

const ip = getBestLanIp() || 'YOUR_MAC_WIFI_IP'
const port = process.env.EXPO_PORT || '8081'

console.log('\n--- Expo Go (each phone) ---')
console.log('1. Open Expo Go (not iPhone Camera)')
console.log('2. Scan QR from terminal OR Enter URL manually:')
console.log(`\n   exp://${ip}:${port}`)
console.log(`\n   API: http://${ip}:8002`)
console.log('\nOther phones fail on LAN? Run: npm run start:share')
console.log('Then in another terminal: npm run tunnel:api\n')
