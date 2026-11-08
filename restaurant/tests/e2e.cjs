// Acceptance script. Needs `npm run build && npx vite preview --port 5174` running.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')
const BASE = process.env.BASE || 'http://127.0.0.1:5174'
const OUT = path.join(__dirname, '..', 'shots')
fs.mkdirSync(OUT, { recursive: true })
const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8')

let fails = 0
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  [' + extra + ']' : ''}`); if (!ok) fails++ }

;(async () => {
  const browser = await chromium.launch()
  for (const [w, h] of [[1440, 820], [820, 1100], [390, 844]]) {
    console.log(`\n=== viewport ${w}x${h} ===`)
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 })
    const errors = []
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
    page.on('pageerror', (e) => errors.push(String(e)))
    await page.goto(`${BASE}/?source=replay`)
    await page.waitForFunction(() => window.__restaurant, null, { timeout: 15000 })
    const api = (fn, ...a) => page.evaluate(([fn, a]) => { const r = window.__restaurant; return typeof r[fn] === 'function' ? r[fn](...a) : r[fn] }, [fn, a])
    const text = (sel) => page.locator(sel).first().innerText()

    check('SOURCE badge says REPLAY', /REPLAY/.test(await text('[data-testid=source-badge]')))
    check('scheduler label is red FALLBACK, NOT RL', /FALLBACK, NOT RL/.test(await text('[data-testid=scheduler-label]')))

    // NEGATIVE proofs first: at tick 5 nothing is hot or closed, so these assertions must report "absent"
    await api('seek', 5); await page.waitForTimeout(900)
    let chefs = await api('chefs')
    check('NEG: tick 5 premium-0 is NOT hot', !/hot/.test(chefs.find((c) => c.id === 'premium-0').texture))
    check('NEG: tick 5 standard-1 is NOT closed', !/closed/.test(chefs.find((c) => c.id === 'standard-1').texture))
    check('NEG: tick 5 no big steam', (await api('steam')).big === 0)
    await page.screenshot({ path: `${OUT}/replay-${w}-t05-normal.png` })

    // critical tick: premium-0 first critical at t15
    await api('seek', 16)
    let big = 0
    for (let i = 0; i < 20 && !big; i++) { await page.waitForTimeout(150); big = (await api('steam')).big }
    check('steam sprite visible at critical tick', big > 0, `big puffs=${big}`)
    chefs = await api('chefs')
    const p0 = chefs.find((c) => c.id === 'premium-0')
    check('premium-0 chef is in angry/hot look + TOO HOT sign + red tint', /hot/.test(p0.texture) && p0.sign === 'hot' && p0.tint > 0, JSON.stringify(p0))
    await page.waitForTimeout(500)
    await page.screenshot({ path: `${OUT}/replay-${w}-t16-critical.png` })

    // disable: standard-1 down at t42..53
    await api('seek', 46); await page.waitForTimeout(1200)
    chefs = await api('chefs')
    const s1 = chefs.find((c) => c.id === 'standard-1')
    check('standard-1 chef greyed + CLOSED sign after disable', /closed/.test(s1.texture) && s1.sign === 'closed', JSON.stringify(s1))
    check('other chefs not greyed', chefs.filter((c) => c.id !== 'standard-1').every((c) => !/closed/.test(c.texture)))
    check('GPU card shows down', /down/i.test(await text('[data-testid=gpu-standard-1]')))
    await page.screenshot({ path: `${OUT}/replay-${w}-t46-disabled.png` })

    // reconcile-from-snapshot: after a seek the sprite count must equal live jobs in state
    await api('seek', 30); await page.waitForTimeout(600)
    const st = await api('state')
    const live = Object.values(st.jobs).filter((j) => j.status !== 'done' && j.status !== 'failed').length
    check('sprites reconcile to state after seek', (await api('customers')) === live, `sprites=${await api('customers')} jobs=${live}`)

    // NEG proof for the snap check: at 1x, walking customers DO lag behind their target
    await api('seek', 0)
    let maxSeen = 0
    for (let i = 0; i < 40; i++) { await page.waitForTimeout(100); maxSeen = Math.max(maxSeen, await api('maxLag')) }
    check('NEG: at 1x customers visibly walk (lag > 0 seen)', maxSeen > 0, `max lag=${maxSeen.toFixed(1)}px`)
    // speed >= 4 snaps instead of walking
    await page.getByRole('button', { name: '16x' }).click()
    await page.waitForTimeout(1500)
    check('speed 16: sprites snap (no walking lag)', (await api('maxLag')) === 0, `lag=${await api('maxLag')}`)
    await page.getByRole('button', { name: '1x' }).click()

    // controls disabled in replay
    check('traffic/spike/VIP disabled in replay', await page.getByRole('button', { name: /Spike/ }).isDisabled() && await page.getByRole('button', { name: /VIP/ }).isDisabled())

    // layout
    const ov = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }))
    check('no horizontal overflow', ov.sw <= ov.iw, `scrollWidth=${ov.sw} innerWidth=${ov.iw}`)

    // axe
    await page.evaluate(axeSrc)
    const ax = await page.evaluate(() => window.axe.run(document, { runOnly: ['wcag2a', 'wcag2aa'] }))
    check('axe wcag2a/aa: 0 violations', ax.violations.length === 0, ax.violations.map((v) => `${v.id}x${v.nodes.length}`).join(' '))
    ax.violations.forEach((v) => console.log('   axe:', v.id, v.help, v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')))

    check('no console errors', errors.length === 0, errors.slice(0, 3).join(' || '))
    await page.screenshot({ path: `${OUT}/replay-${w}-final-full.png`, fullPage: true })
    await page.close()
  }

  // fallback path: live requested, backend absent -> banner + REPLAY badge
  console.log('\n=== live requested, no backend ===')
  const page = await browser.newPage({ viewport: { width: 1440, height: 820 }, deviceScaleFactor: 1 })
  await page.goto(`${BASE}/?source=live`)
  await page.waitForSelector('.banner', { timeout: 15000 })
  check('fallback banner text', (await page.locator('.banner').innerText()) === 'backend offline — replay mode')
  check('badge says REPLAY (never LIVE) under fallback', /REPLAY/.test(await page.locator('[data-testid=source-badge]').innerText()))
  await page.screenshot({ path: `${OUT}/fallback-1440.png` })
  await browser.close()
  console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED')
  process.exit(fails ? 1 : 0)
})()
