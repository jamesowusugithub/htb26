import type { Config, GpuView } from '../data/types'

export const W = 320
export const H = 180
export const DOOR = { x: 14, y: 150 }
export const MANAGER_POS = { x: 160, y: 102 }
export const ZONE_A = { x: 2, y: 0, w: 126, h: 86 }
export const ZONE_B = { x: 132, y: 0, w: 186, h: 86 }
export const ZONE_C = { x: 232, y: 104, w: 86, h: 74 }
export const ZONE_D = { x: 128, y: 114, w: 98, h: 64 }
export const COUNTER_C = { x: 232, y: 130 }

export interface StationPos { id: string; tier: 'premium' | 'standard' | 'cloud'; cx: number; label: string }

/** Evenly spread the GPUs of each tier across their zone. */
export function stationLayout(gpus: Pick<GpuView, 'id' | 'tier'>[]): StationPos[] {
  const out: StationPos[] = []
  const place = (tier: 'premium' | 'standard', zone: { x: number; w: number }) => {
    const list = gpus.filter((g) => g.tier === tier)
    const step = zone.w / Math.max(1, list.length)
    list.forEach((g, i) => out.push({ id: g.id, tier, cx: Math.round(zone.x + step * (i + 0.5)), label: g.id.toUpperCase() }))
  }
  place('premium', ZONE_A)
  place('standard', ZONE_B)
  for (const g of gpus.filter((x) => x.tier === 'cloud')) out.push({ id: g.id, tier: 'cloud', cx: 275, label: 'CLOUD' })
  return out
}

export const gpusFromConfig = (c: Config) => c.nodes.flatMap((n) => n.gpus)

/** Feet position of the k-th customer at a place. */
export function slotPos(place: string, k: number, stations: Map<string, StationPos>): { x: number; y: number } {
  if (place === 'queue') {
    const row = Math.floor(k / 8)
    return { x: 26 + (k % 8) * 14, y: row > 1 ? 166 : 150 + row * 16 }
  }
  if (place === 'D') {
    const i = Math.min(k, 14)
    return { x: 142 + (i % 5) * 19, y: 148 + Math.floor(i / 5) * 14 }
  }
  if (place === 'C') {
    const i = Math.min(k, 9)
    return { x: 245 + (i % 5) * 17, y: 164 + Math.floor(i / 5) * 12 }
  }
  const st = stations.get(place.slice(2))
  const cx = st?.cx ?? 100
  const i = Math.min(k, 8)
  return { x: cx + ((i % 3) - 1) * 20, y: 74 + Math.floor(i / 3) * 10 }
}

/** Where the chef/counter of a GPU is (for pointing, fx). */
export function stationFocus(id: string, stations: Map<string, StationPos>): { x: number; y: number } {
  const st = stations.get(id)
  if (!st) return { x: 160, y: 60 }
  return st.tier === 'cloud' ? { x: 275, y: 136 } : { x: st.cx, y: 46 }
}
