import Phaser from 'phaser'
import { isTrace } from '../data/traceMeta'
import type { Controller } from '../data/controller'
import type { Decision, JobView, Priority, SimEvent, SimState } from '../data/types'
import {
  COUNTER_C, DOOR, H, MANAGER_POS, W, ZONE_A, ZONE_B, ZONE_C, ZONE_D,
  gpusFromConfig, slotPos, stationFocus, stationLayout, type StationPos,
} from './layout'
import { pixelText, textKey } from './pixel'
import { bubbleTexture, chefKey, generateAllTextures, personTexture, type ChefLook } from './sprites'

const hash = (s: string) => {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  return h >>> 0
}
const groupSize = (vram: number) => (vram <= 16 ? 0 : vram <= 32 ? 1 : vram <= 56 ? 2 : 3)
const groupSizeGpus = (g: number) => (g <= 1 ? 0 : g <= 2 ? 1 : g <= 4 ? 2 : 3)
const REDUCED = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

interface Cust {
  key: string
  jobId: string
  ghost: boolean
  c: Phaser.GameObjects.Container
  body: Phaser.GameObjects.Image
  bar: Phaser.GameObjects.Graphics
  mood: Phaser.GameObjects.Image | null
  tx: number
  ty: number
  prio: Priority
  skin: number
  hair: number
  leaving: boolean
  step: number
  lastBar: string
}

interface StationView {
  pos: StationPos
  chef?: Phaser.GameObjects.Image
  flames: Phaser.GameObjects.Image[]
  pan?: Phaser.GameObjects.Image
  thermo?: Phaser.GameObjects.Graphics
  tint?: Phaser.GameObjects.Rectangle
  sign?: Phaser.GameObjects.Image
  signKind: string
  nextPuff: number
  lastHealth: string
  lastThermo: string
  gear?: Phaser.GameObjects.Image
  zzz?: Phaser.GameObjects.Image
}

export class RestaurantScene extends Phaser.Scene {
  private ctl: Controller
  private stations = new Map<string, StationPos>()
  private views = new Map<string, StationView>()
  private custs = new Map<string, Cust>()
  private pendingFx: SimEvent[] = []
  private spawnAtDoor = new Set<string>()
  private lastVersion = -1
  private manager!: Phaser.GameObjects.Image
  private coinText!: Phaser.GameObjects.Image
  private coinIcon!: Phaser.GameObjects.Image
  private lastCoins = -1
  private puffs: Phaser.GameObjects.Image[] = []
  private transient: Phaser.GameObjects.GameObject[] = []
  private pointing: Phaser.GameObjects.GameObject[] = []
  private unsubs: (() => void)[] = []
  private builtFor = ''

  constructor(ctl: Controller) {
    super('restaurant')
    this.ctl = ctl
  }

  private get speed() { return this.ctl.meta.speed }
  private get snap() { return REDUCED || this.speed >= 4 }
  /** cosmetic durations shrink when sim runs fast */
  private dur(ms: number) { return ms / Math.min(Math.max(this.speed, 1), 4) }

  create() {
    this.views.clear()
    this.custs.clear()
    this.puffs = []
    this.transient = []
    this.pointing = []
    this.unsubs.forEach((u) => u())
    this.unsubs = []
    this.lastVersion = -1
    generateAllTextures(this)
    this.cameras.main.setBackgroundColor('#2a1f1a')
    this.buildWorld()
    this.unsubs.push(
      this.ctl.onEvents((evs) => {
        // a huge batch means a fast-forward: keep arrivals/completions, drop one-off decorations
        this.pendingFx.push(...evs.filter((e) => e.type !== 'GPU_TELEMETRY' && e.type !== 'METRICS'))
        if (this.pendingFx.length > 200) this.pendingFx.splice(0, this.pendingFx.length - 200)
      }),
      this.ctl.onReset(() => this.hardReset()),
    )
    this.events.once('shutdown', () => this.unsubs.forEach((u) => u()))
    ;(window as unknown as { __restaurant: unknown }).__restaurant = this.debugApi()
  }

  // ---------------------------------------------------------------- world
  private buildWorld() {
    const cfg = this.ctl.config
    const gpus = cfg ? gpusFromConfig(cfg) : Object.values(this.ctl.state.gpus)
    this.builtFor = gpus.map((g) => g.id).join(',')
    this.stations.clear()
    stationLayout(gpus).forEach((s) => this.stations.set(s.id, s))

    const ts = (x: number, y: number, w: number, h: number, key: string, depth = 0) =>
      this.add.tileSprite(x, y, w, h, key).setOrigin(0, 0).setDepth(depth)

    // floors
    ts(0, 0, W, H, 'tile_path', -100)
    ts(ZONE_A.x, 18, ZONE_A.w, ZONE_A.h - 18, 'tile_wood', -90)
    ts(ZONE_A.x, 18, ZONE_A.w, 34, 'tile_check', -89)
    ts(ZONE_A.x, 0, ZONE_A.w, 18, 'tile_wall', -90)
    ts(ZONE_B.x, 0, ZONE_B.w, ZONE_B.h, 'tile_grass', -90)
    ts(ZONE_B.x + 4, 18, ZONE_B.w - 8, 34, 'tile_patio', -89)
    ts(ZONE_B.x + 4, 52, ZONE_B.w - 8, ZONE_B.h - 52, 'tile_patio', -89)
    ts(ZONE_D.x, ZONE_D.y, ZONE_D.w, ZONE_D.h, 'tile_rug', -90)
    ts(ZONE_C.x, ZONE_C.y, ZONE_C.w, ZONE_C.h, 'tile_check', -90)

    // borders
    const g = this.add.graphics().setDepth(-80)
    g.lineStyle(1, 0x3b2a20, 1)
    g.strokeRect(ZONE_A.x + 0.5, 0.5, ZONE_A.w - 1, ZONE_A.h)
    g.strokeRect(ZONE_B.x + 0.5, 0.5, ZONE_B.w - 1, ZONE_B.h)
    g.strokeRect(ZONE_D.x + 0.5, ZONE_D.y + 0.5, ZONE_D.w - 1, ZONE_D.h - 1)
    g.strokeRect(ZONE_C.x + 0.5, ZONE_C.y + 0.5, ZONE_C.w - 1, ZONE_C.h - 1)
    // outdoor fence (zone B is outside)
    g.fillStyle(0xf4ead2, 1)
    for (let x = ZONE_B.x + 2; x < ZONE_B.x + ZONE_B.w - 2; x += 6) g.fillRect(x, ZONE_B.h - 4, 3, 4)
    g.fillRect(ZONE_B.x + 2, ZONE_B.h - 3, ZONE_B.w - 4, 1)

    // decor
    this.add.image(64, 2, 'window').setOrigin(0.5, 0).setDepth(-70)
    this.add.image(190, 2, 'tree').setOrigin(0.5, 0).setDepth(-70)
    this.add.image(255, 2, 'tree').setOrigin(0.5, 0).setDepth(-70)
    this.add.image(312, 4, 'tree').setOrigin(0.5, 0).setDepth(-70)
    this.add.image(122, 80, 'plant').setOrigin(0.5, 1).setDepth(80)
    this.add.image(ZONE_D.x + 26, ZONE_D.y + 14, 'bench').setDepth(-60)
    this.add.image(ZONE_D.x + 72, ZONE_D.y + 14, 'bench').setDepth(-60)
    this.add.image(ZONE_D.x + 49, ZONE_D.y + 56, 'bike').setDepth(-60).setAlpha(0.95)
    this.add.image(ZONE_C.x + ZONE_C.w / 2, ZONE_C.y + 6, 'awning').setDepth(-60)
    this.add.image(ZONE_C.x + ZONE_C.w / 2 - 28, ZONE_C.y + 6, 'cloudlogo').setDepth(-59)
    this.add.image(ZONE_C.x + ZONE_C.w / 2 + 28, ZONE_C.y + 6, 'cloudlogo').setDepth(-59)
    this.add.image(COUNTER_C.x + 43, COUNTER_C.y + 7, 'counterC').setDepth(-58)
    this.add.image(0, 116, 'door').setOrigin(0, 0).setDepth(-60)
    for (const x of [22, 50, 78, 106]) {
      this.add.image(x, 158, 'rope').setOrigin(0.5, 1).setDepth(158)
    }
    this.add.rectangle(22, 155, 84, 1, 0xb8860b).setOrigin(0, 0).setDepth(157)

    // zone banners
    const banner = (x: number, y: number, t: string, fg = '#ffd84a') => pixelText(this, x, y, t, { color: fg, bg: '#3b2a20', pad: 2 }).setDepth(200)
    banner(64, 92, isTrace() ? 'A KITCHEN' : 'A PREMIUM KITCHEN')          // in trace mode chefs are real GPU types, not price tiers
    banner(225, 92, isTrace() ? 'B KITCHEN' : 'B STANDARD KITCHEN')
    banner(275, ZONE_C.y + 21, 'C CLOUD TAKEAWAY', '#bfe3f5')
    banner(177, ZONE_D.y + 6, 'D WAITING AREA', '#e4d0a8')
    banner(34, 112, 'ENTRANCE', '#ffffff')
    pixelText(this, 160, 107, 'AI MANAGER', { color: '#3b2a20', bg: '#fff3c4', pad: 1 }).setDepth(200)
    pixelText(this, 38, 175, 'SIMULATED DATA', { color: '#ffffff', shadow: '#3b2a20' }).setDepth(200).setAlpha(0.85)

    // stations
    for (const st of this.stations.values()) this.buildStation(st)

    // manager
    this.manager = this.add.image(MANAGER_POS.x, MANAGER_POS.y, 'manager').setOrigin(0.5, 1).setDepth(MANAGER_POS.y + 1)
    this.tweens.add({ targets: this.manager, scaleY: 1.04, duration: 900, yoyo: true, repeat: -1, ease: 'Sine.inOut' })

    // coin counter
    this.add.rectangle(276, 91, 42, 11, 0x3b2a20).setOrigin(0, 0).setDepth(199)
    this.coinIcon = this.add.image(283, 96, 'coin').setDepth(200)
    this.coinText = pixelText(this, 315, 96, 'X0', { color: '#ffd84a' }).setOrigin(1, 0.5).setDepth(200)
    this.lastCoins = -1
  }

  private buildStation(st: StationPos) {
    const v: StationView = { pos: st, flames: [], signKind: '', nextPuff: 0, lastHealth: 'normal', lastThermo: '' }
    if (st.tier === 'cloud') {
      v.gear = this.add.image(COUNTER_C.x + 76, COUNTER_C.y - 5, 'gear').setDepth(COUNTER_C.y).setVisible(false)
      this.tweens.add({ targets: v.gear, angle: 360, duration: 1200, repeat: -1 })
      this.views.set(st.id, v)
      return
    }
    const { cx } = st
    v.tint = this.add.rectangle(cx - 30, 0, 60, 88, 0xff2b1a, 0).setOrigin(0, 0).setDepth(300)
    v.chef = this.add.image(cx, 46, chefKey('normal', 0)).setOrigin(0.5, 1).setDepth(40)
    this.add.image(cx - 23, 42, 'station').setOrigin(0, 0).setDepth(41)
    pixelText(this, cx, 54, st.label, { color: '#fff3c4' }).setDepth(42)
    for (const dx of [-12, 12]) {
      const f = this.add.image(cx + dx, 46, 'flame0').setOrigin(0.5, 1).setDepth(43).setVisible(false)
      v.flames.push(f)
    }
    v.pan = this.add.image(cx + 12, 43, 'pan').setOrigin(0, 0.5).setDepth(43).setVisible(false)
    v.thermo = this.add.graphics().setDepth(44)
    v.zzz = this.add.image(cx + 9, 18, 'zzz').setDepth(45).setVisible(false)
    this.views.set(st.id, v)
  }

  private hardReset() {
    for (const c of this.custs.values()) c.c.destroy()
    this.custs.clear()
    this.spawnAtDoor.clear()
    this.pendingFx = []
    this.transient.forEach((o) => o.destroy())
    this.transient = []
    this.puffs.forEach((p) => p.destroy())
    this.puffs = []
    this.lastVersion = -1
    this.lastCoins = -1
    for (const v of this.views.values()) { v.lastHealth = 'normal'; v.lastThermo = '' }
  }

  // ---------------------------------------------------------------- frame
  update(time: number, deltaMs: number) {
    const state = this.ctl.state
    const dt = deltaMs / 1000
    // layout can change when config arrives after boot
    const ids = Object.keys(state.gpus).join(',')
    if (ids && ids !== this.builtFor && (this.ctl.config || state.gpuOrder.length)) {
      this.scene.restart()
      return
    }
    this.processFx()
    if (this.ctl.version !== this.lastVersion) {
      this.lastVersion = this.ctl.version
      this.reconcile(state)
    }
    this.moveCustomers(dt)
    this.updateStations(state, time)
    this.updateCoins(state)
  }

  private placeOf(jv: JobView): string | null {
    switch (jv.status) {
      case 'arrived': return 'queue'
      case 'held': return 'D'
      case 'done': case 'failed': return null
      default: {
        const first = jv.gpuIds[0]
        if (!first) return jv.status === 'cloud' ? 'C' : 'D'
        const st = this.stations.get(first)
        return !st || st.tier === 'cloud' ? 'C' : `g:${first}`
      }
    }
  }

  private reconcile(state: SimState) {
    const wanted = new Map<string, { jv: JobView; place: string; ghost: boolean; extra: string }>()
    const jobs = Object.values(state.jobs).sort((a, b) => a.arrivedSeq - b.arrivedSeq || a.job.id.localeCompare(b.job.id))
    const counts = new Map<string, number>()
    for (const jv of jobs) {
      const place = this.placeOf(jv)
      if (!place) continue
      wanted.set(jv.job.id, { jv, place, ghost: false, extra: '' })
      // a split job also shows a ghost at each additional GPU
      if ((jv.status === 'running' || jv.status === 'assigned') && jv.gpuIds.length > 1) {
        jv.gpuIds.slice(1).forEach((gid, i) => {
          const st = this.stations.get(gid)
          wanted.set(`${jv.job.id}#${i + 1}`, { jv, place: !st || st.tier === 'cloud' ? 'C' : `g:${gid}`, ghost: true, extra: gid })
        })
      }
    }
    for (const [key, w] of wanted) {
      const k = counts.get(w.place) ?? 0
      counts.set(w.place, k + 1)
      const pos = slotPos(w.place, k, this.stations)
      let c = this.custs.get(key)
      if (!c) {
        const fromDoor = !w.ghost && this.spawnAtDoor.has(w.jv.job.id)
        c = this.makeCust(key, w.jv, w.ghost, fromDoor ? DOOR.x : pos.x, fromDoor ? DOOR.y : pos.y)
        this.custs.set(key, c)
        this.spawnAtDoor.delete(w.jv.job.id)
      }
      c.tx = pos.x
      c.ty = pos.y
      this.paintCust(c, w.jv, state)
    }
    for (const [key, c] of this.custs) {
      if (!wanted.has(key) && !c.leaving) {
        c.c.destroy()
        this.custs.delete(key)
      }
    }
  }

  private makeCust(key: string, jv: JobView, ghost: boolean, x: number, y: number): Cust {
    const h = hash(jv.job.id)
    const prio = jv.job.priority
    const skin = h % 4
    const hair = (h >> 3) % 5
    const c = this.add.container(x, y)
    const body = this.add.image(0, 0, personTexture(this, prio, skin, hair, 0)).setOrigin(0.5, 1)
    const mates = isTrace() ? groupSizeGpus(jv.job.gpus ?? jv.job.vram_gb) : groupSize(jv.job.vram_gb)
    const parts: Phaser.GameObjects.GameObject[] = []
    for (let i = 0; i < mates; i++) {
      const m = this.add.image((i % 2 ? 1 : -1) * (6 + 3 * Math.floor(i / 2)), -1 - Math.floor(i / 2), personTexture(this, prio, (skin + i + 1) % 4, (hair + i + 2) % 5, 0))
        .setOrigin(0.5, 1).setScale(0.78)
      parts.push(m)
    }
    parts.push(body)
    if (prio === 'vip') parts.push(this.add.image(0, -16, 'crown').setOrigin(0.5, 1))
    parts.push(this.add.image(10, 0, textKey(this, isTrace() ? `${jv.job.gpus ?? jv.job.vram_gb}GPU` : `${jv.job.vram_gb}G`, { color: '#3b2a20', bg: '#fff3c4', pad: 1 })).setOrigin(0.5, 1))
    const bar = this.add.graphics()
    parts.push(bar)
    c.add(parts)
    if (ghost) c.setAlpha(0.55).setScale(0.9)
    return { key, jobId: jv.job.id, ghost, c, body, bar, mood: null, tx: x, ty: y, prio, skin, hair, leaving: false, step: 0, lastBar: '' }
  }

  /** deadline-slack/progress bar + question mark while waiting for the manager */
  private paintCust(c: Cust, jv: JobView, state: SimState) {
    const remaining = jv.status === 'running' && jv.etaT !== undefined ? Math.max(0, jv.etaT - state.t) : jv.job.duration_s
    // real-trace mode has no deadlines: the bar over a waiting party is a plain wait timer (30 min scale, a display convention)
    const slack = isTrace() ? 30 - (state.t - (jv.job.arrival_t ?? state.t)) : jv.job.deadline_t - state.t - remaining
    const prog = jv.status === 'running' && jv.etaT !== undefined ? 1 - remaining / Math.max(1, jv.job.duration_s) : -1
    const sig = `${Math.round(slack)}|${prog.toFixed(2)}`
    if (sig !== c.lastBar) {
      c.lastBar = sig
      c.bar.clear()
      const yb = c.prio === 'vip' ? -24 : -19
      if (prog >= 0) {
        c.bar.fillStyle(0x3b2a20, 1).fillRect(-7, yb, 14, 3)
        c.bar.fillStyle(0x53d36b, 1).fillRect(-6, yb + 1, Math.round(12 * Math.min(1, prog)), 1)
      } else {
        const col = slack < 0 ? 0xd6453a : slack < 6 ? 0xf0b429 : 0x53d36b
        c.bar.fillStyle(0x3b2a20, 1).fillRect(-5, yb + 1, 10, 3)
        c.bar.fillStyle(col, 1).fillRect(-4, yb + 2, Math.max(1, Math.min(8, Math.round(slack / 3))), 1)
      }
    }
    const wantQ = jv.status === 'arrived'
    if (wantQ && !c.mood) c.mood = this.add.image(0, -26, 'question').setOrigin(0.5, 1)
    else if (!wantQ && c.mood && !c.leaving) { c.mood.destroy(); c.mood = null }
    if (c.mood && wantQ && !c.c.list.includes(c.mood)) c.c.add(c.mood)
  }

  private moveCustomers(dt: number) {
    const speedPx = 62 * Math.max(0.8, Math.min(this.speed, 4))
    for (const [key, c] of this.custs) {
      const dx = c.tx - c.c.x
      const dy = c.ty - c.c.y
      const dist = Math.hypot(dx, dy)
      const walking = dist > 0.5
      if (walking) {
        if (this.snap) { c.c.x = c.tx; c.c.y = c.ty }
        else {
          const s = Math.min(dist, speedPx * dt)
          c.c.x += (dx / dist) * s
          c.c.y += (dy / dist) * s
        }
      }
      c.c.setDepth(c.c.y)
      if (walking && !this.snap) {
        c.step += dt * 9
        c.body.setTexture(personTexture(this, c.prio, c.skin, c.hair, 1 + (Math.floor(c.step) % 2)))
        c.body.y = -Math.abs(Math.sin(c.step)) * 1.5
        if (dx !== 0) c.body.setFlipX(dx < 0)
      } else {
        c.body.setTexture(personTexture(this, c.prio, c.skin, c.hair, 0))
        if (c.body.y !== 0 && !this.tweens.isTweening(c.body)) c.body.y = 0
        if (c.leaving && dist <= 0.5) { c.c.destroy(); this.custs.delete(key) }
      }
    }
  }

  // ---------------------------------------------------------------- stations
  private updateStations(state: SimState, time: number) {
    const running = new Set<string>()
    for (const jv of Object.values(state.jobs)) if (jv.status === 'running') jv.gpuIds.forEach((id) => running.add(id))
    for (const v of this.views.values()) {
      const gpu = state.gpus[v.pos.id]
      if (!gpu) continue
      const cooking = running.has(gpu.id) && !gpu.disabled
      if (v.pos.tier === 'cloud') {
        v.gear?.setVisible(cooking)
        continue
      }
      const critical = gpu.health === 'critical' && !gpu.disabled
      const warning = gpu.health === 'warning'
      const closed = gpu.disabled || gpu.health === 'down'
      const look: ChefLook = closed ? 'closed' : critical ? 'hot' : 'normal'
      const frame = cooking && !closed ? Math.floor(time / (critical ? 120 : 260)) % 2 : 0
      v.chef!.setTexture(chefKey(look, frame))
      v.chef!.x = v.pos.cx + (critical && !REDUCED ? Math.sin(time / 28) * 0.9 : 0)
      v.chef!.y = 46 + (cooking && !closed && frame ? -1 : 0)
      v.pan!.setVisible(cooking && !closed).setY(43 + (frame ? -2 : 0)).setRotation(frame ? -0.25 : 0)
      v.flames.forEach((f, i) => f.setVisible(cooking && !closed).setTexture(Math.floor(time / 140 + i) % 2 ? 'flame1' : 'flame0'))
      v.zzz!.setVisible(closed).setY(18 - Math.floor(time / 500) % 2)

      // kitchen tint pulses red at critical
      v.tint!.setFillStyle(0xff2b1a, critical ? 0.05 + 0.04 * (1 + Math.sin(time / 160)) : 0)

      // signs
      const want = closed ? 'closed' : critical ? 'hot' : ''
      if (want !== v.signKind) {
        v.sign?.destroy()
        v.sign = undefined
        v.signKind = want
        if (want) {
          v.sign = pixelText(this, v.pos.cx, 8, want === 'closed' ? 'CLOSED' : 'TOO HOT!', {
            color: '#ffffff', bg: want === 'closed' ? '#6b7280' : '#c1121f', pad: 2,
          }).setDepth(250)
        }
      }
      if (v.sign) v.sign.y = 8 + (want === 'hot' && !REDUCED ? Math.round(Math.sin(time / 90)) : 0)

      // thermometer
      const sig = `${Math.round(gpu.temp)}|${gpu.health}`
      if (sig !== v.lastThermo) {
        v.lastThermo = sig
        const g = v.thermo!
        g.clear()
        const x = v.pos.cx + 25
        const frac = Math.max(0, Math.min(1, (gpu.temp - 35) / 65))
        g.fillStyle(0x3b2a20, 1).fillRect(x - 2, 17, 6, 26)
        g.fillStyle(0xfff8e8, 1).fillRect(x - 1, 18, 4, 22)
        const col = closed ? 0x9ca3af : gpu.temp >= state.thresholds.critical ? 0xd6453a : gpu.temp >= state.thresholds.warning ? 0xf0b429 : 0x53d36b
        g.fillStyle(col, 1).fillRect(x, 39 - Math.round(20 * frac), 2, Math.max(1, Math.round(20 * frac)))
        g.fillStyle(col, 1).fillRect(x - 1, 40, 4, 2)
        // tick marks at warning/critical
        for (const th of [state.thresholds.warning, state.thresholds.critical]) {
          const ty = 39 - Math.round(20 * Math.max(0, Math.min(1, (th - 35) / 65)))
          g.fillStyle(0x3b2a20, 1).fillRect(x + 3, ty, 2, 1)
        }
      }

      // critical onset: one shout
      if (critical && v.lastHealth !== 'critical') this.shake(v)
      v.lastHealth = gpu.health

      // steam: scales with temperature. normal cooking = none.
      const t = gpu.temp
      if (!closed && (warning || critical) && time >= v.nextPuff) {
        const heat = Math.max(0, Math.min(1, (t - state.thresholds.warning) / 25))
        const big = critical
        v.nextPuff = time + (big ? 240 : 640) - heat * 100
        this.spawnPuff(v.pos.cx + (Math.random() < 0.5 ? -12 : 12), 40, big, 0.45 + heat * 0.45)
      }
    }
  }

  private spawnPuff(x: number, y: number, big: boolean, scale: number) {
    const p = this.add.image(x, y, big ? 'steam_big' : 'steam_s').setDepth(260).setScale(0.5).setAlpha(0.95)
    p.setData('big', big)
    this.puffs.push(p)
    const rise = big ? 24 + Math.random() * 10 : 14 + Math.random() * 6
    this.tweens.add({
      targets: p, y: y - rise, x: x + (Math.random() - 0.5) * 10, scale: big ? scale * 1.25 : scale,
      duration: big ? 1500 : 1100, ease: 'Sine.out',
      onComplete: () => {
        this.puffs = this.puffs.filter((q) => q !== p)
        p.destroy()
      },
    })
    // stay fully visible for the first part of its life, then fade
    this.tweens.add({ targets: p, alpha: 0, delay: big ? 700 : 450, duration: big ? 800 : 650 })
  }

  private shake(v: StationView) {
    if (REDUCED || !v.chef) return
    this.tweens.add({ targets: v.chef, angle: { from: -6, to: 6 }, duration: 60, yoyo: true, repeat: 5, onComplete: () => v.chef?.setAngle(0) })
  }

  private updateCoins(state: SimState) {
    if (state.coins === this.lastCoins) return
    const bump = this.lastCoins >= 0 && state.coins > this.lastCoins
    this.lastCoins = state.coins
    this.coinText.setTexture(textKey(this, `X${state.coins}`, { color: '#ffd84a' }))
    if (bump) this.tweens.add({ targets: this.coinIcon, scale: { from: 1.7, to: 1 }, duration: 260 })
  }

  // ---------------------------------------------------------------- fx from events
  private processFx() {
    if (!this.pendingFx.length) return
    const fx = this.pendingFx
    this.pendingFx = []
    let lastDecision: Decision | null = null
    for (const ev of fx) {
      switch (ev.type) {
        case 'JOB_ARRIVED':
          this.spawnAtDoor.add(ev.job.id)
          break
        case 'DECISION':
          lastDecision = {
            job_id: ev.job_id, action: ev.action, target_gpu_ids: ev.target_gpu_ids, scheduler: ev.scheduler,
            factors: ev.factors, mask_summary: ev.mask_summary, t: ev.t, seq: ev.seq,
          }
          break
        case 'ALLOCATION_REJECTED':
          this.fxReject(ev.gpu_id, ev.reason)
          break
        case 'JOB_COMPLETED':
          this.fxComplete(ev.job_id, ev.on_time)
          break
        case 'JOB_FAILED':
          this.fxSad(ev.job_id)
          break
        default:
      }
    }
    if (lastDecision) this.fxDecision(lastDecision)
    // events were applied to state before we got here, so sprites for new arrivals are created in reconcile()
    this.lastVersion = -1
  }

  private keep<T extends Phaser.GameObjects.GameObject>(o: T, ms: number): T {
    this.transient.push(o)
    this.time.delayedCall(ms, () => {
      o.destroy()
      this.transient = this.transient.filter((x) => x !== o)
    })
    return o
  }

  private fxDecision(d: Decision) {
    const first = d.target_gpu_ids[0]
    let target: { x: number; y: number }
    let label: string
    let zone: { x: number; y: number; w: number; h: number }
    if (d.action === 'hold' || !first) {
      target = { x: ZONE_D.x + ZONE_D.w / 2, y: ZONE_D.y + 40 }
      label = 'WAIT'
      zone = ZONE_D
    } else if (d.action === 'cloud' || this.stations.get(first)?.tier === 'cloud') {
      target = stationFocus('cloud-0', this.stations)
      label = 'CLOUD'
      zone = ZONE_C
    } else {
      const f = stationFocus(first, this.stations)
      target = { x: f.x, y: f.y + 6 }
      label = d.action === 'split' ? `SPLIT ${d.target_gpu_ids.length}` : first.toUpperCase()
      zone = { x: f.x - 30, y: 0, w: 60, h: 86 }
    }
    this.pointing.forEach((o) => o.destroy())
    this.pointing = []
    const from = { x: MANAGER_POS.x, y: MANAGER_POS.y - 10 }
    this.manager.setFlipX(target.x < MANAGER_POS.x)

    // speech bubble
    const tk = textKey(this, label, { color: '#3b2a20' })
    const tw = this.textures.get(tk).getSourceImage().width
    const bw = tw + 8
    const bubble = this.keep(this.add.container(MANAGER_POS.x, MANAGER_POS.y - 20), this.dur(1700))
    this.pointing.push(bubble)
    bubble.add([this.add.image(0, 0, bubbleTexture(this, bw, 11)).setOrigin(0.5, 1), this.add.image(0, -10, tk).setOrigin(0.5, 0.5)])
    bubble.setDepth(400)

    // pointing hand flies from the manager to the target, leaving a dotted trail
    const hand = this.keep(this.add.image(from.x, from.y, 'hand').setDepth(401).setOrigin(0.5, 0.5), this.dur(1700))
    this.pointing.push(hand)
    hand.setFlipX(target.x < from.x)
    const n = 7
    const dots: Phaser.GameObjects.Image[] = []
    for (let i = 1; i <= n; i++) {
      const dot = this.keep(this.add.image(from.x + ((target.x - from.x) * i) / (n + 1), from.y + ((target.y - from.y) * i) / (n + 1), 'dot').setDepth(399).setAlpha(0), this.dur(1700))
      dots.push(dot)
      this.pointing.push(dot)
      this.tweens.add({ targets: dot, alpha: 1, delay: this.dur(50 * i), duration: 120 })
    }
    if (this.snap) { hand.setPosition(target.x, target.y) }
    else this.tweens.add({ targets: hand, x: target.x, y: target.y, duration: this.dur(420), ease: 'Cubic.out' })

    // highlight ring on the destination
    const ring = this.keep(this.add.rectangle(zone.x, zone.y, zone.w, zone.h).setOrigin(0, 0).setDepth(350), this.dur(1500))
    this.pointing.push(ring)
    ring.setStrokeStyle(2, 0xffd84a, 1).setFillStyle(0xffd84a, 0.12)
    this.tweens.add({ targets: ring, alpha: { from: 1, to: 0.25 }, duration: this.dur(300), yoyo: true, repeat: 2 })
  }

  private fxReject(gpuId: string, reason: string) {
    const f = stationFocus(gpuId, this.stations)
    const text = reason === 'memory' ? 'FULL' : reason === 'thermal' ? 'TOO HOT' : reason === 'down' ? 'CLOSED' : 'NO'
    const x = this.add.image(f.x - 12, f.y + 6, 'tick_x').setDepth(420).setScale(1.6)
    const t = this.add.image(f.x + 4, f.y + 6, textKey(this, text, { color: '#ffffff', bg: '#c1121f', pad: 1 })).setDepth(420)
    this.keep(x, this.dur(1500))
    this.keep(t, this.dur(1500))
    this.tweens.add({ targets: [x, t], y: '-=8', duration: this.dur(1200), ease: 'Sine.out' })
  }

  private fxComplete(jobId: string, onTime: boolean) {
    const jv = this.ctl.state.jobs[jobId]
    const gid = jv?.gpuIds[0]
    const st = gid ? this.stations.get(gid) : undefined
    const pos = !st || st.tier === 'cloud' ? { x: 275, y: 134 } : { x: st.cx, y: 30 }
    const c = this.custs.get(jobId)
    if (c) {
      c.leaving = true
      c.tx = DOOR.x
      c.ty = DOOR.y
      if (onTime) {
        this.tweens.add({ targets: c.body, y: -7, duration: this.dur(160), yoyo: true, repeat: 1 })
        const h = this.add.image(0, -22, 'heart').setOrigin(0.5, 1)
        c.c.add(h)
        this.time.delayedCall(this.dur(1400), () => h.destroy())
      } else {
        c.body.setTint(0x9aa0aa)
        const cl = this.add.image(0, -20, 'sadcloud').setOrigin(0.5, 1)
        c.c.add(cl)
        this.tweens.add({ targets: cl, y: -22, duration: this.dur(500), yoyo: true, repeat: -1 })
        c.mood = cl
      }
    }
    if (onTime) {
      const plate = this.keep(this.add.image(pos.x, pos.y, 'plate').setDepth(450).setScale(0.2), this.dur(1400))
      this.tweens.add({ targets: plate, scale: 1.3, y: pos.y - 14, duration: this.dur(300), ease: 'Back.out' })
      this.tweens.add({ targets: plate, alpha: 0, delay: this.dur(900), duration: this.dur(400) })
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * Math.PI * 2
        const sp = this.keep(this.add.image(pos.x, pos.y - 10, i % 2 ? 'sparkle' : 'sparkle_s').setDepth(451), this.dur(1000))
        this.tweens.add({
          targets: sp, x: pos.x + Math.cos(a) * 18, y: pos.y - 10 + Math.sin(a) * 14, alpha: 0, scale: 0.4,
          duration: this.dur(800), ease: 'Cubic.out',
        })
      }
      const coin = this.keep(this.add.image(pos.x + 10, pos.y - 8, 'coin').setDepth(452), this.dur(1300))
      this.tweens.add({ targets: coin, x: 283, y: 96, duration: this.dur(1000), ease: 'Cubic.inOut', delay: this.dur(200) })
    } else {
      const cl = this.keep(this.add.image(pos.x, pos.y - 6, 'sadcloud').setDepth(450), this.dur(1800))
      this.tweens.add({ targets: cl, y: pos.y - 16, alpha: 0, delay: this.dur(900), duration: this.dur(800) })
    }
  }

  private fxSad(jobId: string) {
    const c = this.custs.get(jobId)
    if (!c) return
    const cl = this.add.image(0, -22, 'sadcloud').setOrigin(0.5, 1)
    c.c.add(cl)
    this.time.delayedCall(this.dur(1500), () => cl.destroy())
  }

  // ---------------------------------------------------------------- debug (used by the Playwright acceptance script)
  private debugApi() {
    return {
      steam: () => {
        const vis = this.puffs.filter((p) => p.active && p.alpha > 0.15)
        return { visible: vis.length, big: vis.filter((p) => p.getData('big')).length }
      },
      chefs: () => [...this.views.values()].filter((v) => v.chef).map((v) => ({ id: v.pos.id, texture: v.chef!.texture.key, sign: v.signKind, tint: v.tint?.fillAlpha ?? 0 })),
      customers: () => this.custs.size,
      ghosts: () => [...this.custs.values()].filter((c) => c.ghost).length,
      maxLag: () => Math.max(0, ...[...this.custs.values()].map((c) => Math.hypot(c.c.x - c.tx, c.c.y - c.ty))),
      state: () => this.ctl.state,
      meta: () => this.ctl.meta,
      seek: (t: number) => this.ctl.seek(t),
    }
  }
}
