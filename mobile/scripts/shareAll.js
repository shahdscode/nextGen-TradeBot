#!/usr/bin/env node
/** @deprecated use npm start — kept as alias */
require('./runDev').main().catch((e) => {
  console.error(e.message || e)
  process.exit(1)
})
