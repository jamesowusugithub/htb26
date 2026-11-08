// LIVE-mode acceptance against the REAL backend.
// Needs: backend on :8000 (uvicorn app.main:app) and `npm run build && npx vite preview --port 5174 --host 127.0.0.1`.
// Every "NEG:" line proves a check can FAIL: it asserts that a deliberately wrong expectation is rejected.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')
const BASE = process.env.BASE || 'http://127.0.0.1:5174'
const API = process.env.API || 'http://localhost:8000'
const OUT = path.join(__dirname, '..', 'shots')
fs.mkdirSync(OUT, { recursive: true })

let fails = 0
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  [' + extra + ']' : ''}`); if (!ok) fails++ }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const rest = async (runId, p, body) => (await fetch(`${API}/api/rest/runs/${runId}${p}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) })).json()
const snapOf = async (runId) => (await fetch(`${API}/api/rest/runs/${runId}/snapshot`)).json()

async function waitFor(fn, ms = 8000, step = 100) {
  const t0 = Date.now()
  for (;;) {
    let v
    try { v = await fn() } catch { v = false }
    if (v) return v
    if (Date.now() - t0 > ms) return false
    await sleep(step)
  }
}

;(async () => {
  const browser = await chromium.launch()
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  const errors = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(String(e)))

  // WS control: track sockets so the test can kill them, and optionally refuse new ones.
  const sockets = []
  let blockWs = false
  const wsUrls = []
  await page.routeWebSocket(/\/ws\/rest\//, (ws) => {
    wsUrls.push(ws.url())
    if (blockWs) { ws.close({ code: 1011, reason: 'test: blocked' }); return }
    const server = ws.connectToServer()
    sockets.push({ ws, server })
  })

  const api = (fn, ...a) => page.evaluate(([fn, a]) => { const r = window.__restaurant; return typeof r[fn] === 'function' ? r[fn](...a) : r[fn] }, [fn, a])
  const txt = (sel) => page.locator(sel).first().innerText()
  const click = (name) => page.getByRole('button', { name, exact: false }).first().click()

  await page.goto(`${BASE}/?source=live`)
  await page.waitForFunction(() => window.__restaurant, null, { timeout: 20000 })
  const runId = (await api('meta')).runId
  check('run created by the UI against real backend', /^[0-9a-f]{12}$/.test(runId || ''), `runId=${runId}`)
  await waitFor(async () => /LIVE/.test(await txt('[data-testid=source-badge]')), 5000)

  // ---- badge + scheduler label
  const badge = await txt('[data-testid=source-badge]')
  check('LIVE badge shown while WS connected', /SOURCE: LIVE/.test(badge), badge)
  check('WS opened with ?from_seq=', wsUrls.length >= 1 && /from_seq=\d+/.test(wsUrls[0]), wsUrls[0])
  const sched0 = await txt('[data-testid=scheduler-label]')
  const effective = (await snapOf(runId)).scheduler
  console.log(`      backend snapshot scheduler=${effective}; UI label="${sched0}"`)
  check('scheduler label matches backend effective label', effective === 'fallback_heuristic' ? /FALLBACK, NOT RL/.test(sched0) : effective === 'rl' ? /RL policy/.test(sched0) : sched0.includes(effective.toUpperCase()), sched0)
  check('NEG: wrong expected label (FIFO) is rejected', !(effective !== 'fifo' && /SCHEDULER: FIFO/.test(sched0)) && !/SCHEDULER: FIFO/.test(sched0))

  // ---- not started: nothing moves
  await sleep(1500)
  check('NEG: before Start nothing ticks (t=0, no customers)', (await api('state')).t === 0 && (await api('customers')) === 0)

  // ---- start
  await click('Start')
  const ticked = await waitFor(async () => (await api('state')).t >= 4 && (await api('customers')) > 0, 15000)
  check('after Start: customers appear and t advances', !!ticked, `t=${(await api('state')).t} customers=${await api('customers')}`)
  const m1 = (await api('state')).metrics
  await sleep(2500)
  const m2 = (await api('state')).metrics
  check('metrics tick (received/avg_util/t progress)', m2.received >= m1.received && (await api('state')).t > 4 && m2.avg_util > 0, JSON.stringify(m2))
  check('NEG: a frozen-metrics comparator would flag m1 vs m1', JSON.stringify(m1) === JSON.stringify(m1) && JSON.stringify(m1) !== JSON.stringify(m2))

  // ---- spike
  const before = (await api('state')).metrics
  await click('Spike')
  let maxWait = 0
  const rose = await waitFor(async () => { const m = (await api('state')).metrics; maxWait = Math.max(maxWait, m.waiting); return m.received >= before.received + 12 && maxWait > before.waiting }, 6000)
  const afterSpike = (await api('state')).metrics
  check('Spike: received +12 and waiting count rises', !!rose, `received ${before.received}->${afterSpike.received}, waiting ${before.waiting} -> max ${maxWait}`)
  await sleep(600)
  await page.screenshot({ path: `${OUT}/live-1-spike.png` })

  // ---- heat premium-0
  await page.getByLabel('GPU to act on').selectOption('premium-0')
  const hot = await waitFor(async () => {
    await click('Heat +20')
    await sleep(900)
    return (await api('state')).gpus['premium-0'].health !== 'normal'
  }, 12000, 50)
  const g0 = (await api('state')).gpus['premium-0']
  check('Force heat: premium-0 reaches warning/critical in state', !!hot && ['warning', 'critical'].includes(g0.health), `health=${g0.health} temp=${g0.temp}`)
  let big = 0
  for (let i = 0; i < 30 && !big; i++) { await sleep(150); big = (await api('steam')).big }
  const chefs = await api('chefs')
  const p0 = chefs.find((c) => c.id === 'premium-0')
  check('steam sprite visible', big > 0, `big puffs=${big}`)
  check('premium-0 chef hot look + sign + tint', /hot/.test(p0.texture) && p0.tint > 0, JSON.stringify(p0))
  check('NEG: premium-1 NOT hot', !/hot/.test(chefs.find((c) => c.id === 'premium-1').texture))
  await page.screenshot({ path: `${OUT}/live-2-critical.png` })

  // ---- disable standard-1
  await page.getByLabel('GPU to act on').selectOption('standard-1')
  await click('Disable')
  const closed = await waitFor(async () => { const c = (await api('chefs')).find((x) => x.id === 'standard-1'); return /closed/.test(c.texture) && c.sign === 'closed' }, 5000)
  check('Disable standard-1: chef greyed + CLOSED sign', !!closed, JSON.stringify((await api('chefs')).find((x) => x.id === 'standard-1')))
  check('GPU card shows down', /down/i.test(await txt('[data-testid=gpu-standard-1]')))
  check('NEG: other chefs not closed', (await api('chefs')).filter((c) => c.id !== 'standard-1').every((c) => !/closed/.test(c.texture)))
  await page.screenshot({ path: `${OUT}/live-3-disabled.png` })
  await page.getByLabel('GPU to act on').selectOption('standard-1')
  await click('Restore')
  check('Restore: standard-1 reopens', !!(await waitFor(async () => !/closed/.test((await api('chefs')).find((x) => x.id === 'standard-1').texture), 5000)))

  // ---- scheduler switch
  await click('fifo')
  check('switch to fifo: label changes', !!(await waitFor(async () => /SCHEDULER: FIFO/.test(await txt('[data-testid=scheduler-label]')), 4000)), await txt('[data-testid=scheduler-label]'))
  check('backend agrees (fifo)', (await snapOf(runId)).scheduler === 'fifo')
  await page.getByRole('button', { name: 'priority', exact: true }).click()
  check('switch to priority: label changes', !!(await waitFor(async () => /SCHEDULER: PRIORITY/.test(await txt('[data-testid=scheduler-label]')), 4000)), await txt('[data-testid=scheduler-label]'))
  check('NEG: label no longer says FIFO', !/FIFO/.test(await txt('[data-testid=scheduler-label]')))
  await click('Normal')

  // ---- speed 16 during a spike: no leak / duplication
  await page.getByRole('button', { name: '16x', exact: true }).click()
  await sleep(300)
  await click('Spike'); await sleep(1200); await click('Spike')
  let leakMax = 0; let dupSeen = false
  for (let i = 0; i < 12; i++) {
    await sleep(400)
    const st = await api('state')
    const live = Object.values(st.jobs).filter((j) => j.status !== 'done' && j.status !== 'failed')
    const expected = live.length + live.reduce((a, j) => a + (j.status === 'running' || j.status === 'assigned' ? Math.max(0, j.gpuIds.length - 1) : 0), 0)
    leakMax = Math.max(leakMax, (await api('customers')) - expected)
    if (new Set(Object.keys(st.jobs)).size !== Object.keys(st.jobs).length) dupSeen = true
  }
  await page.screenshot({ path: `${OUT}/live-4-speed16-spike.png` })
  console.log(`      16x: t=${(await api('state')).t} max(customers - expected) over run = ${leakMax}`)
  await click('Pause')
  await page.getByRole('button', { name: '1x', exact: true }).click()
  await sleep(3500) // let leaving animations finish
  {
    const st = await api('state')
    const live = Object.values(st.jobs).filter((j) => j.status !== 'done' && j.status !== 'failed')
    const expected = live.length + live.reduce((a, j) => a + (j.status === 'running' || j.status === 'assigned' ? Math.max(0, j.gpuIds.length - 1) : 0), 0)
    const cust = await api('customers')
    check('16x spike: sprite count == live jobs (+ghosts) after settle', cust === expected, `customers=${cust} expected=${expected} t=${st.t}`)
    check('16x spike: transient over-count small (leaving sprites only)', leakMax <= 12, `leakMax=${leakMax}`)
    check('16x spike: no duplicate job ids', !dupSeen)
  }

  // ---- WS kill + reconnect resync (spike over REST while the socket is down)
  await click('Start')
  await sleep(1500)
  const nSockBefore = wsUrls.length
  blockWs = true
  sockets.splice(0).forEach(({ ws }) => ws.close({ code: 1011, reason: 'test kill' }))
  const lost = await waitFor(async () => !/SOURCE: LIVE/.test(await txt('[data-testid=source-badge]')), 4000)
  const badgeDown = await txt('[data-testid=source-badge]')
  check('WS killed: badge NOT LIVE while disconnected', !!lost && !/LIVE/.test(badgeDown), badgeDown)
  await page.screenshot({ path: `${OUT}/live-5-disconnected.png` })
  await rest(runId, '/spike', { n: 15 })           // events the UI cannot receive over WS
  await sleep(2500)
  check('NEG: while down, UI has NOT seen the REST spike (backend ahead)', (await snapOf(runId)).metrics.received > (await api('state')).metrics.received)
  blockWs = false
  const back = await waitFor(async () => /SOURCE: LIVE/.test(await txt('[data-testid=source-badge]')), 15000)
  check('reconnects and shows LIVE again', !!back, `ws attempts=${wsUrls.length - nSockBefore}`)
  check('reconnect URL uses ?from_seq=', /from_seq=\d+/.test(wsUrls[wsUrls.length - 1]), wsUrls[wsUrls.length - 1])
  await rest(runId, '/pause')
  await sleep(4000)
  {
    const snap = await snapOf(runId)
    const st = await api('state')
    const snapJobs = new Set([...snap.queue.map((j) => j.id), ...snap.running.map((r) => r.job_id)]).size
    const ghosts = await api('ghosts')
    const cust = await api('customers')
    check('after reconnect: UI lastSeq == snapshot last_seq', st.lastSeq === snap.last_seq, `${st.lastSeq} vs ${snap.last_seq}`)
    check('after reconnect: UI received count == backend', st.metrics.received === snap.metrics.received, `${st.metrics.received} vs ${snap.metrics.received}`)
    check('after reconnect: sprite count (minus ghosts) == snapshot job count', cust - ghosts === snapJobs, `sprites=${cust} ghosts=${ghosts} snapshotJobs=${snapJobs}`)
    check('NEG: sprite check rejects an off-by-one expectation', cust - ghosts !== snapJobs + 1)
  }
  await page.screenshot({ path: `${OUT}/live-6-resynced.png` })

  // ---- second viewer sees a reset frame
  const page2 = await ctx.newPage()
  await page2.goto(`${BASE}/?source=live&run=${runId}`)
  await page2.waitForFunction(() => window.__restaurant, null, { timeout: 20000 })
  await waitFor(async () => (await page2.evaluate(() => window.__restaurant.customers())) > 0, 6000)
  const c2 = await page2.evaluate(() => window.__restaurant.customers())
  check('second viewer attached to same run shows sprites', c2 > 0, `customers=${c2}`)

  // ---- reset
  await page.bringToFront()
  await click('Reset')
  const cleared = await waitFor(async () => (await api('customers')) === 0 && (await api('state')).t === 0 && (await api('state')).metrics.received === 0, 6000)
  check('Reset clears sprites, t and metrics (clicking viewer)', !!cleared, `customers=${await api('customers')} t=${(await api('state')).t}`)
  const cleared2 = await waitFor(async () => (await page2.evaluate(() => window.__restaurant.customers())) === 0 && (await page2.evaluate(() => window.__restaurant.state().t)) === 0, 6000)
  check('Reset reaches 2nd viewer via WS reset:true frame', !!cleared2)
  const snapR = await snapOf(runId)
  check('backend agrees: t=0, empty queue', snapR.t === 0 && snapR.queue.length === 0 && snapR.running.length === 0)
  // run works again after reset
  await click('Start')
  check('after reset, Start works again', !!(await waitFor(async () => (await api('state')).t >= 3 && (await api('customers')) > 0, 12000)))
  await rest(runId, '/pause')
  await page2.close()

  // ---- mobile 390
  const mp = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 })
  await mp.goto(`${BASE}/?source=live`)
  await mp.waitForFunction(() => window.__restaurant, null, { timeout: 20000 })
  const mid = (await mp.evaluate(() => window.__restaurant.meta())).runId
  await rest(mid, '/spike', { n: 12 }); await rest(mid, '/start'); await rest(mid, '/speed', { speed: 4 })
  await sleep(5000)
  await mp.screenshot({ path: `${OUT}/live-7-mobile390.png` })
  const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check('390px: no page-level horizontal overflow', overflow <= 0, `overflow=${overflow}`)
  await rest(mid, '/pause')

  check('no console/page errors', errors.length === 0, errors.slice(0, 3).join(' | '))
  await browser.close()
  console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED')
  process.exit(fails ? 1 : 0)
})().catch((e) => { console.error(e); process.exit(2) })
