// Backend unreachable: auto mode falls back to the LABELLED synthetic demo; explicit backend mode shows an error and shows no invented data.
import { serveDist, launch, openRoom, sleep } from './harness.mjs';
const results = [];
const check = (n, ok, d = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? '  — ' + d : ''}`); };
const { server, port } = await serveDist();
const browser = await launch();
const dead = 'http://127.0.0.1:9';   // nothing listens here
try {
  let { page } = await openRoom(browser, `http://127.0.0.1:${port}/index.html?api=${encodeURIComponent(dead)}`);
  await sleep(1500);
  let r = await page.evaluate(() => ({ mode: document.querySelector('.gpu-ui').dataset.mode, footer: document.querySelector('.evidence-strip')?.textContent, event: document.querySelector('.latest-event')?.textContent }));
  check('auto mode with no backend falls back to the synthetic demo', r.mode === 'synthetic', r.mode);
  check('the fallback is labelled synthetic and says why', /synthetic/i.test(r.footer) && /not reachable/i.test(r.footer), r.footer.slice(0, 150));
  await page.close();
  ({ page } = await openRoom(browser, `http://127.0.0.1:${port}/index.html?mode=backend&api=${encodeURIComponent(dead)}`));
  await sleep(1500);
  r = await page.evaluate(() => { const s = window.gpuLab.engine.snapshot(); return { mode: document.querySelector('.gpu-ui').dataset.mode, status: s.status, error: s.error, running: s.stats.running, temps: s.gpus.map(g => g.temperature).filter(t => t != null).length, banner: document.querySelector('.status-banner')?.textContent }; });
  check('explicit backend mode with no backend shows an error', r.mode === 'backend' && r.status === 'error' && /not reachable/i.test(r.error), r.error?.slice(0, 80));
  check('and shows no scheduling data or measurements at all', r.running === 0 && r.temps === 0, `running=${r.running} temps=${r.temps}`);
  check('error banner is visible to the user', /not reachable/i.test(r.banner || ''), (r.banner || '').slice(0, 60));
} finally { await browser.close(); server.close(); }
process.exit(results.every(Boolean) ? 0 : 1);
