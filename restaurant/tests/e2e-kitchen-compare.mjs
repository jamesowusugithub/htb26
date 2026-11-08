// Browser test: custom kitchen (GPU types + counts), an order for a chosen type, and the all-policy comparison charts.
//   BASE=http://127.0.0.1:5174 API=http://127.0.0.1:8020 PUPPETEER=.../puppeteer-core node tests/e2e-kitchen-compare.mjs
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
const puppeteer = createRequire(import.meta.url)(process.env.PUPPETEER || 'puppeteer-core')
const BASE = process.env.BASE || 'http://127.0.0.1:5174', API = process.env.API || 'http://127.0.0.1:8020', OUT = process.env.OUT || 'shots'
mkdirSync(OUT, { recursive: true })
const results = []; const check = (n, ok, d = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  - ' + d : ''}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms)), text = (p) => p.evaluate(() => document.body.innerText)
const click = (p, label) => p.evaluate((l) => { const x = [...document.querySelectorAll('button')].find((e) => e.textContent.trim().includes(l) && !e.disabled); if (!x) throw new Error('no enabled button: ' + l); x.click() }, label)
const b = await puppeteer.launch({ executablePath: process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: 'new', protocolTimeout: 180000,
  args: ['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'], defaultViewport: { width: 1500, height: 1300 } })
try {
  const p = await b.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(e.message))
  await p.goto(`${BASE}/?trace=rl_ppo&api=${encodeURIComponent(API)}`, { waitUntil: 'domcontentloaded' })
  await p.waitForSelector('canvas', { timeout: 60000 }); await sleep(2500)
  check('kitchen editor and compare panel are offered with a backend', /Kitchen:/i.test(await text(p)) && /Compare all managers/i.test(await text(p)))
  // chef 1 -> A10 x1, chef 2 -> H800 x8, chef 3 -> series 1 x2
  await p.evaluate(() => {
    const set = (label, v) => { const el = document.querySelector(`select[aria-label="${label}"]`); const d = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value'); d.set.call(el, v); el.dispatchEvent(new Event('change', { bubbles: true })) }
    set('Chef 1 GPU type', 'a10'); set('Chef 1 GPUs', '1'); set('Chef 2 GPU type', 'h800'); set('Chef 3 GPU type', 'series1'); set('Chef 3 GPUs', '2')
  })
  await click(p, 'Apply kitchen'); await p.waitForFunction(() => /A10 x1/.test(document.body.innerText) || /Alibaba GPU series 1/.test(document.body.innerText), { timeout: 120000, polling: 400 }).catch(() => {})
  await sleep(2500)
  const t = await text(p)
  check('the kitchen was rebuilt with the chosen GPU types (A10, H800, series 1)', /A10/.test(t) && /H800/.test(t) && /series 1/i.test(t), (t.match(/Kitchen: [^\n]*/) || [''])[0])
  const meta = await fetch(`${API}/restaurant/compare`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ kitchen: [{ pool: 'a10', gpus: 1 }, { pool: 'h800', gpus: 8 }, { pool: 'series1', gpus: 2 }, { pool: 'a100', gpus: 8 }, { pool: 'a100', gpus: 8 }], cloud: { nodes: 1 } }) }).then((r) => r.json())
  check('backend runs all four managers on the custom kitchen', ['fifo', 'priority_fifo', 'sjf_hint', 'rl_ppo'].every((k) => meta.policies?.[k]?.received > 0))
  await p.select('select[aria-label="GPU type for the order"]', 'h800')
  await click(p, 'Place order'); await p.waitForFunction(() => /1 placed/i.test(document.body.innerText), { timeout: 120000, polling: 300 })
  check('an order for a chosen GPU type is accepted', true)
  await click(p, 'Compare all managers'); await p.waitForSelector('.cmp .bar-row', { timeout: 180000 })
  const bars = await p.evaluate(() => ({ charts: document.querySelectorAll('.cmp-chart').length, rows: document.querySelectorAll('.bar-row').length, scatter: document.querySelectorAll('.scatter circle').length, text: document.querySelector('.cmp').innerText }))
  check('four bar charts (4 managers each) and the predicted-vs-actual scatter are drawn', bars.charts >= 5 && bars.rows === 16 && bars.scatter > 3, JSON.stringify({ c: bars.charts, r: bars.rows, s: bars.scatter }))
  check('the comparison says its numbers are simulated', /simulated/i.test(bars.text))
  await p.evaluate(() => document.querySelector('#h-compare').scrollIntoView()); await sleep(500)
  await p.screenshot({ path: `${OUT}/kitchen-compare.png` })
  check('no page errors', errs.length === 0, errs.slice(0, 2).join(' | '))
} catch (e) { check('test ran without exception', false, String(e.stack || e).slice(0, 400)) } finally { await b.close() }
console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`); process.exit(results.every(Boolean) ? 0 : 1)
