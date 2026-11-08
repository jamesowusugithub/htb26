const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: 1440, height: 820 }, deviceScaleFactor: 1 })
  await p.goto('http://127.0.0.1:5174/?source=replay')
  await p.waitForFunction(() => window.__restaurant)
  const clip = { x: 16, y: 62, width: 1000, height: 566 }
  const times = (process.argv[2] || '4300,4900,5600').split(',').map(Number)
  let last = 0
  for (const ms of times) { await p.waitForTimeout(ms - last); last = ms; await p.screenshot({ path: `shots/seq-${ms}.png`, clip }) }
  await b.close()
})()
