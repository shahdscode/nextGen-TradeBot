#!/usr/bin/env node
/** Interactive helper — creates .env with NGROK_AUTHTOKEN placeholder */
const fs = require('fs')
const path = require('path')
const readline = require('readline')

const envPath = path.join(__dirname, '..', '.env')
const example = path.join(__dirname, '..', '.env.example')

const rl = readline.createInterface({ input: process.stdin, output: process.stdout })

console.log('\nFix B setup — ngrok token (free):')
console.log('https://dashboard.ngrok.com/get-started/your-authtoken\n')

rl.question('Paste NGROK_AUTHTOKEN (or Enter to skip): ', (token) => {
  rl.close()
  const t = (token || '').trim()
  let body = fs.existsSync(example) ? fs.readFileSync(example, 'utf8') : ''
  if (t) {
    if (body.match(/^NGROK_AUTHTOKEN=/m)) {
      body = body.replace(/^NGROK_AUTHTOKEN=.*$/m, `NGROK_AUTHTOKEN=${t}`)
    } else {
      body = `NGROK_AUTHTOKEN=${t}\n\n` + body
    }
  }
  fs.writeFileSync(envPath, body)
  console.log('\nWrote', envPath)
  if (t) {
    console.log('Run:  npm run share')
  } else {
    console.log('Add NGROK_AUTHTOKEN to .env then:  npm run share')
  }
})
