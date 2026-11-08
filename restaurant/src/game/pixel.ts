import Phaser from 'phaser'

/** Parse '#rrggbb' to 0xrrggbb. */
export const hex = (s: string) => parseInt(s.slice(1), 16)

export type Palette = Record<string, string | null>

/**
 * Draw an ASCII pixel map into a texture via Graphics.generateTexture.
 * '.' (or any key mapped to null / missing) is transparent. Pixels are 1x1 and the game
 * uses pixelArt:true (nearest-neighbour), so the art stays chunky when the canvas is scaled.
 */
export function pixelTexture(scene: Phaser.Scene, key: string, rows: string[], pal: Palette) {
  if (scene.textures.exists(key)) return
  const g = scene.make.graphics({ x: 0, y: 0 }, false)
  const w = Math.max(...rows.map((r) => r.length))
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const c = pal[row[x]]
      if (!c) continue
      g.fillStyle(hex(c), 1)
      g.fillRect(x, y, 1, 1)
    }
  })
  g.generateTexture(key, w, rows.length)
  g.destroy()
}

/** Procedural texture with a callback drawing on a Graphics object. */
export function drawTexture(scene: Phaser.Scene, key: string, w: number, h: number, fn: (g: Phaser.GameObjects.Graphics) => void) {
  if (scene.textures.exists(key)) return
  const g = scene.make.graphics({ x: 0, y: 0 }, false)
  fn(g)
  g.generateTexture(key, w, h)
  g.destroy()
}

/** Filled pixel disc (no anti-aliasing) used for steam, clouds, sparkle glow. */
export function discPixels(g: Phaser.GameObjects.Graphics, cx: number, cy: number, r: number, color: string) {
  g.fillStyle(hex(color), 1)
  for (let y = -r; y <= r; y++) {
    for (let x = -r; x <= r; x++) if (x * x + y * y <= r * r + r * 0.6) g.fillRect(cx + x, cy + y, 1, 1)
  }
}

// ---- 3x5 pixel font, generated into canvas textures on demand ----
// Each glyph: 5 rows of 3 chars separated by '/'. X = ink.
const RAW: Record<string, string> = {
  A: '.X./X.X/XXX/X.X/X.X', B: 'XX./X.X/XX./X.X/XX.', C: '.XX/X../X../X../.XX', D: 'XX./X.X/X.X/X.X/XX.',
  E: 'XXX/X../XX./X../XXX', F: 'XXX/X../XX./X../X..', G: '.XX/X../X.X/X.X/.XX', H: 'X.X/X.X/XXX/X.X/X.X',
  I: 'XXX/.X./.X./.X./XXX', J: '..X/..X/..X/X.X/.X.', K: 'X.X/X.X/XX./X.X/X.X', L: 'X../X../X../X../XXX',
  M: 'X.X/XXX/XXX/X.X/X.X', N: 'XXX/X.X/X.X/X.X/X.X', O: '.X./X.X/X.X/X.X/.X.', P: 'XX./X.X/XX./X../X..',
  Q: '.X./X.X/X.X/XX./.XX', R: 'XX./X.X/XX./X.X/X.X', S: '.XX/X../.X./..X/XX.', T: 'XXX/.X./.X./.X./.X.',
  U: 'X.X/X.X/X.X/X.X/XXX', V: 'X.X/X.X/X.X/X.X/.X.', W: 'X.X/X.X/XXX/XXX/X.X', X: 'X.X/X.X/.X./X.X/X.X',
  Y: 'X.X/X.X/.X./.X./.X.', Z: 'XXX/..X/.X./X../XXX',
  '0': 'XXX/X.X/X.X/X.X/XXX', '1': '.X./XX./.X./.X./XXX', '2': 'XX./..X/.X./X../XXX', '3': 'XX./..X/.X./..X/XX.',
  '4': 'X.X/X.X/XXX/..X/..X', '5': 'XXX/X../XX./..X/XX.', '6': '.XX/X../XXX/X.X/XXX', '7': 'XXX/..X/.X./.X./.X.',
  '8': 'XXX/X.X/XXX/X.X/XXX', '9': 'XXX/X.X/XXX/..X/XX.',
  '.': '.../.../.../.../.X.', '-': '.../.../XXX/.../...', '!': '.X./.X./.X./.../.X.', '?': 'XX./..X/.X./.../.X.',
  ':': '.../.X./.../.X./...', '%': 'X.X/..X/.X./X../X.X', '$': '.XX/XX./.X./.XX/XX.', '+': '.../.X./XXX/.X./...',
  '>': 'X../.X./..X/.X./X..', '/': '..X/..X/.X./X../X..', ' ': '.../.../.../.../...',
}
const GLYPHS: Record<string, string> = Object.fromEntries(Object.entries(RAW).map(([k, v]) => [k, v.split('/').join('')]))

export interface TextOpts {
  color?: string
  bg?: string | null
  shadow?: string | null
  pad?: number
  scale?: number
}

/** Returns a texture key for the string, generating (and caching) it on first use. */
export function textKey(scene: Phaser.Scene, text: string, o: TextOpts = {}): string {
  const color = o.color ?? '#ffffff'
  const scale = o.scale ?? 1
  const key = `txt|${text}|${color}|${o.bg ?? ''}|${o.shadow ?? ''}|${o.pad ?? 0}|${scale}`
  if (scene.textures.exists(key)) return key
  const chars = text.toUpperCase().split('')
  const pad = o.pad ?? 0
  const w = (chars.length * 4 - 1) * scale + pad * 2
  const h = 5 * scale + pad * 2 + (o.shadow ? scale : 0)
  const tex = scene.textures.createCanvas(key, Math.max(1, w), h)!
  const ctx = tex.getContext()
  if (o.bg) { ctx.fillStyle = o.bg; ctx.fillRect(0, 0, w, h) }
  const draw = (col: string, dy: number) => {
    ctx.fillStyle = col
    chars.forEach((ch, i) => {
      const gl = GLYPHS[ch] ?? GLYPHS['?']
      for (let k = 0; k < 15; k++)
        if (gl[k] === 'X') ctx.fillRect(pad + (i * 4 + (k % 3)) * scale, pad + dy + Math.floor(k / 3) * scale, scale, scale)
    })
  }
  if (o.shadow) draw(o.shadow, scale)
  draw(color, 0)
  tex.refresh()
  return key
}

export function pixelText(scene: Phaser.Scene, x: number, y: number, text: string, o: TextOpts = {}) {
  return scene.add.image(x, y, textKey(scene, text, o)).setOrigin(0.5, 0.5)
}
