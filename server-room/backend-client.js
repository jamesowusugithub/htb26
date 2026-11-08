// Client for the FastAPI scheduling backend (scheduler/api.py). Uses WebSockets; falls back to polling.
// The client only transports backend results. It never computes scheduling decisions or measurements.

const parseNdjson = text => text.split('\n').filter(Boolean).map(l => JSON.parse(l));

export class BackendClient {
  constructor(base = 'http://127.0.0.1:8000', { WebSocketImpl = globalThis.WebSocket, fetchImpl = globalThis.fetch.bind(globalThis), forcePolling = false } = {}) {
    this.base = base.replace(/\/$/, '');
    this.forcePolling = forcePolling;
    this.WebSocketImpl = WebSocketImpl;
    this.fetch = fetchImpl;
  }
  async json(path, opts) {
    const r = await this.fetch(this.base + path, opts);
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail ?? detail; } catch { /* keep status text */ }
      throw new Error(`${r.status} ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
    }
    return r.json();
  }
  health() { return this.json('/health'); }
  meta() { return this.json('/meta'); }
  presets() { return this.json('/presets'); }
  whatIf(body) { return this.json('/whatif', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }); }
  runMeta(runId) { return this.json(`/runs/${encodeURIComponent(runId)}`); }
  state(runId, t) { return this.json(`/runs/${encodeURIComponent(runId)}/state?t=${encodeURIComponent(t)}`); }
  async events(runId, from, to, types) {
    const q = new URLSearchParams({ t_from: String(from), t_to: String(to) });
    if (types) q.set('types', types);
    const r = await this.fetch(`${this.base}/runs/${encodeURIComponent(runId)}/events?${q}`);
    if (!r.ok) throw new Error(`${r.status} events`);
    return parseNdjson(await r.text());
  }
  wsUrl(runId, { start = 0, speed = 600, paused = false } = {}) {
    return `${this.base.replace(/^http/, 'ws')}/runs/${encodeURIComponent(runId)}/stream?start=${start}&speed=${speed}&paused=${paused}`;
  }

  /** Open a paced stream. Returns {send(cmd), close(), mode()}; messages are delivered to onMessage in the backend's shape. */
  openStream(runId, { start = 0, speed = 600, paused = false, onMessage, onStatus = () => {}, forcePolling = this.forcePolling, connectTimeoutMs = 4000 }) {
    let impl = null, closed = false, usingPolling = false;
    const startPolling = () => {
      if (closed || usingPolling) return;
      usingPolling = true;
      impl = new PollingStream(this, runId, { start, speed, paused, onMessage });
      onStatus({ mode: 'polling', status: 'connected' });
      impl.start();
    };
    const useWs = !forcePolling && typeof this.WebSocketImpl === 'function';
    if (!useWs) startPolling();
    else {
      let opened = false;
      let ws;
      try { ws = new this.WebSocketImpl(this.wsUrl(runId, { start, speed, paused })); } catch { startPolling(); }
      if (ws) {
        impl = ws;
        const timer = setTimeout(() => { if (!opened && !closed) { try { ws.close(); } catch {} startPolling(); } }, connectTimeoutMs);
        ws.onopen = () => { opened = true; clearTimeout(timer); onStatus({ mode: 'websocket', status: 'connected' }); };
        ws.onmessage = ev => { try { onMessage(JSON.parse(ev.data)); } catch (e) { onStatus({ mode: 'websocket', status: 'bad-message', error: String(e) }); } };
        ws.onerror = () => { if (!opened) { clearTimeout(timer); startPolling(); } };
        ws.onclose = () => { if (opened && !closed) onStatus({ mode: 'websocket', status: 'closed' }); };
      }
    }
    return {
      send: cmd => {
        if (usingPolling) impl.command(cmd);
        else if (impl?.readyState === 1) impl.send(JSON.stringify(cmd));
        else if (impl) { const wait = setInterval(() => { if (impl?.readyState === 1) { impl.send(JSON.stringify(cmd)); clearInterval(wait); } else if (closed || impl?.readyState > 1) clearInterval(wait); }, 50); }
      },
      close: () => { closed = true; try { usingPolling ? impl?.stop() : impl?.close(); } catch {} },
      mode: () => (usingPolling ? 'polling' : 'websocket'),
    };
  }
}

/** Polling fallback with the same message shape and control commands as the WebSocket. */
export class PollingStream {
  constructor(client, runId, { start, speed, paused, onMessage, intervalMs = 250 }) {
    Object.assign(this, { client, runId, onMessage, intervalMs, t: start, speed, paused, timer: null, busy: false, last: 0, end: null });
  }
  async start() {
    try { this.end = (await this.client.runMeta(this.runId)).window?.length_s ?? null; this.onMessage(await this.client.runMeta(this.runId)); } catch (e) { this.onMessage({ type: 'error', detail: String(e) }); return; }
    this.last = Date.now();
    this.timer = setInterval(() => this.poll(), this.intervalMs);
  }
  stop() { clearInterval(this.timer); this.timer = null; }
  command(cmd) {
    if (cmd.cmd === 'pause') this.paused = true;
    else if (cmd.cmd === 'resume') this.paused = false;
    else if (cmd.cmd === 'speed') this.speed = Math.max(Number(cmd.value) || 1, 1);
    else if (cmd.cmd === 'seek') this.t = Math.max(Number(cmd.t) || 0, 0);
  }
  async poll() {
    const now = Date.now(), dt = (now - this.last) / 1000;
    this.last = now;
    if (this.paused) { this.onMessage({ type: 'tick', t: this.t, paused: true, speed: this.speed }); return; }
    if (this.busy) return;
    this.busy = true;
    try {
      const t0 = this.t, t1 = t0 + this.speed * dt;
      this.t = t1;
      const items = t1 > t0 ? await this.client.events(this.runId, t0, t1 - 1e-9) : [];
      this.onMessage({ type: 'batch', t_from: t0, t_to: t1, speed: this.speed, paused: false, items });
      if (this.end != null && t1 > this.end) { this.stop(); this.onMessage({ type: 'end' }); }
    } catch (e) { this.onMessage({ type: 'error', detail: String(e) }); }
    finally { this.busy = false; }
  }
}
