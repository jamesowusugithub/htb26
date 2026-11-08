import Phaser from 'phaser'
import type { Priority } from '../data/types'
import { discPixels, drawTexture, hex, pixelTexture, type Palette } from './pixel'

export const SHIRT: Record<Priority, { main: string; shade: string }> = {
  low: { main: '#9aa0a6', shade: '#757b82' },
  medium: { main: '#3f7fe0', shade: '#2d5fb0' },
  high: { main: '#f08a24', shade: '#c26a12' },
  vip: { main: '#f5c518', shade: '#c79a08' },
}
export const SKINS = ['#f2c9a0', '#d9a273', '#a86f46', '#f7dcc0']
export const HAIRS = ['#3b2a20', '#8a4b1f', '#1f1f28', '#d6a43a', '#b5452a']
export const OUTLINE = '#3b2a20'

const pad = (r: string) => r.padEnd(16, '.')

const HEAD = [
  '................',
  '.....OOOOOO.....',
  '....OHHHHHHO....',
  '....OHHHHHHO....',
  '....OHSSSSHO....',
  '....OSESSESO....',
  '....OSSSSSSO....',
  '.....OSSSSO.....',
]
const BODY = [
  '...OOBBBBBBOO...',
  '..OSOBBBBBBOSO..',
  '..OSOBBbbBBOSO..',
  '...OOBBBBBBOO...',
  '....OBBBBBBO....',
]
const LEGS: Record<number, string[]> = {
  0: ['....OLLOOLLO....', '....OLLOOLLO....', '....OFFOOFFO....'],
  1: ['....OLLOOLLO....', '...OLLO..OLLO...', '...OFFO..OFFO...'],
  2: ['....OLLOOLLO....', '....OLLO.OLLO...', '...OFFO...OFFO..'],
}

export function personTexture(scene: Phaser.Scene, prio: Priority, skin: number, hair: number, pose: number): string {
  const key = `cust|${prio}|${skin}|${hair}|${pose}`
  pixelTexture(scene, key, [...HEAD, ...BODY, ...LEGS[pose]].map(pad), {
    O: OUTLINE, H: HAIRS[hair], S: SKINS[skin], E: '#26211f', B: SHIRT[prio].main, b: SHIRT[prio].shade, L: '#4b5563', F: '#2b2523',
  })
  return key
}

export type ChefLook = 'normal' | 'hot' | 'closed'
const CHEF = (look: ChefLook, frame: number) => {
  const rows = [
    '....OOOOOOOO....',
    '...OWWWWWWWWO...',
    '...OWWWWWWWWO...',
    '....OWwWWwWO....',
    '....OWWWWWWO....',
    '....OSSSSSSO....',
    '....OSESSESO....',
    '....OSSMMSSO....',
    '.....OSSSSO.....',
    '...OOWWWWWWOO...',
    frame ? '..OSOWWWWWWOSO..' : '..OOOWWWWWWOOO..',
    frame ? '..OOOWWPPWWOOO..' : '..OSOWWPPWWOSO..',
    '...OOWWPPWWOO...',
    '....OWWPPWWO....',
    '....OLLOOLLO....',
    '....OFFOOFFO....',
  ]
  if (look === 'hot') {
    rows[5] = '....OSBSSBSO....' // angry brows
    rows[7] = '....OSMMMMSO....' // open mouth
  }
  if (look === 'closed') rows[6] = '....OEESSEEO....' // shut eyes
  return rows
}
const CHEF_PAL = (look: ChefLook): Palette =>
  look === 'closed'
    ? { O: '#4a4a4a', W: '#b9b9b9', w: '#9a9a9a', S: '#a8a8a8', E: '#555555', M: '#555555', B: '#555555', P: '#8d8d8d', L: '#777777', F: '#555555' }
    : look === 'hot'
      ? { O: OUTLINE, W: '#fff6ea', w: '#e8d6c0', S: '#e8584a', E: '#26211f', M: '#4a1d1d', B: '#7a1f17', P: '#d6453a', L: '#4b5563', F: '#2b2523' }
      : { O: OUTLINE, W: '#ffffff', w: '#e5e1da', S: '#f2c9a0', E: '#26211f', M: '#b0492f', B: '#26211f', P: '#e5533d', L: '#4b5563', F: '#2b2523' }

export const chefKey = (look: ChefLook, frame: number) => `chef|${look}|${frame}`

const MANAGER = [
  ...HEAD.map((r, i) => (i === 5 ? '....OGGSSGGO....' : r)),
  '...OOBBWWBBOO...',
  '..OSOBWRRWBOSO..',
  '..OSOBBRRBBOSO..',
  '...OOBBRRBBOO...',
  '....OBBRRBBO....',
  ...LEGS[0],
]

const FLAT = (g: Phaser.GameObjects.Graphics, color: string, x: number, y: number, w: number, h: number) => {
  g.fillStyle(hex(color), 1)
  g.fillRect(x, y, w, h)
}

/** Generate every static texture once, at boot. All art is drawn in code; nothing is loaded. */
export function generateAllTextures(scene: Phaser.Scene) {
  for (const look of ['normal', 'hot', 'closed'] as ChefLook[])
    for (const f of [0, 1]) pixelTexture(scene, chefKey(look, f), CHEF(look, f).map(pad), CHEF_PAL(look))

  pixelTexture(scene, 'manager', MANAGER.map(pad), {
    O: OUTLINE, H: '#1f1f28', S: '#f2c9a0', E: '#26211f', G: '#26211f', B: '#27304f', b: '#1d2440', W: '#ffffff', R: '#d6453a', L: '#1d2440', F: '#2b2523',
  })

  // pan, flame, plate, coin, crown, sparkle, gear, hand, door
  pixelTexture(scene, 'pan', ['.........', 'OOOOOOO..', 'ODDDDDOOO', 'OOOOOOO..'].map((r) => r.padEnd(9, '.')), { O: '#2b2523', D: '#4b4f57' })
  pixelTexture(scene, 'flame0', ['..Y..', '.YOY.', '.YOY.', 'YOOOY', 'ORRRO'], { Y: '#ffd84a', O: '#f08a24', R: '#d6453a' })
  pixelTexture(scene, 'flame1', ['.Y...', '.YOY.', 'YOOOY', 'YOOOY', 'ORRRO'], { Y: '#ffd84a', O: '#f08a24', R: '#d6453a' })
  pixelTexture(scene, 'plate', ['....OOOO....', '..OOWWWWOO..', '.OWWwWWWWWO.', 'OWWWWWWWWWWO', '.OOOOOOOOOO.', '..SSSSSSSS..'].map((r) => r.padEnd(12, '.')), { O: '#6b7280', W: '#f4f6f8', w: '#ffffff', S: '#cbd2d9' })
  pixelTexture(scene, 'coin', ['.OOOO.', 'OYYYYO', 'OYwYYO', 'OYYYYO', '.OOOO.'].map((r) => r.padEnd(6, '.')), { O: '#9a6a00', Y: '#ffcf33', w: '#fff3b0' })
  pixelTexture(scene, 'crown', ['O.O.O.O', 'OYOYOYO', 'OYYYYYO', 'OOOOOOO'], { O: '#7a5a00', Y: '#ffd84a' })
  pixelTexture(scene, 'sparkle', ['...Y...', '...Y...', '..YWY..', 'YYWWWYY', '..YWY..', '...Y...', '...Y...'], { Y: '#ffe066', W: '#ffffff' })
  pixelTexture(scene, 'sparkle_s', ['..Y..', '..Y..', 'YYWYY', '..Y..', '..Y..'], { Y: '#ffe066', W: '#ffffff' })
  pixelTexture(scene, 'gear', ['..OO..', '.OWWO.', 'OWOOWO', 'OWOOWO', '.OWWO.', '..OO..'], { O: '#4b5563', W: '#cbd5e1' })
  pixelTexture(scene, 'hand', ['..WWW...', '.WWWWOO.', 'WWWWWWWO', '.WWWWOO.', '..OOO...'], { W: '#ffffff', O: '#3b2a20' })
  pixelTexture(scene, 'dot', ['YY', 'YY'], { Y: '#ffffff' })
  pixelTexture(scene, 'tick_x', ['O...O', '.O.O.', '..O..', '.O.O.', 'O...O'], { O: '#d6453a' })
  pixelTexture(scene, 'zzz', ['WWW.', '..W.', '.W..', 'WWW.'], { W: '#e5e7eb' })
  pixelTexture(scene, 'cloudlogo', ['..OOO...', '.OWWWOO.', 'OWWWWWWO', 'OWWWWWWO', '.OOOOOO.'].map((r) => r.padEnd(8, '.')), { O: '#7aa7d8', W: '#ffffff' })
  pixelTexture(scene, 'sadcloud', [
    '....OOOO........',
    '..OOGGGGOOO.....',
    '.OGGGGGGGGGOO...',
    'OGGGEGGGGEGGGO..',
    'OGGGGGGGGGGGGO..',
    'OGGGGOOOOGGGGO..',
    '.OGGGGGGGGGGO...',
    '..OOOOOOOOOO....',
    '...B..B...B.....',
    '....B..B........',
  ].map((r) => r.padEnd(16, '.')), { O: '#4b5563', G: '#aab4c3', E: '#26211f', B: '#4a90d9' })
  pixelTexture(scene, 'heart', ['.OO.OO.', 'ORRORRO', 'ORRRRRO', '.ORRRO.', '..ORO..', '...O...'], { O: '#8f1d2c', R: '#ff5a76' })
  pixelTexture(scene, 'question', ['.OOO.', 'O...O', '...O.', '..O..', '.....', '..O..'].map((r) => r.padEnd(5, '.')), { O: '#3b2a20' })
  pixelTexture(scene, 'bike', [
    '...........OO...',
    '.....OOOOOOORR..',
    '....OBBBBBBBR...',
    '..OOOBBBBBBO....',
    '.OWWOOOOOOOOWWO.',
    'OWOOWO....OWOOWO',
    '.OOWO......OWOO.',
  ].map((r) => r.padEnd(16, '.')), { O: '#3b2a20', B: '#e5533d', R: '#ffd84a', W: '#9ca3af' })

  // tiles (16x16), deterministic noise
  const noise = (x: number, y: number, s: number) => {
    const n = Math.sin(x * 12.9898 + y * 78.233 + s * 37.719) * 43758.5453
    return n - Math.floor(n)
  }
  drawTexture(scene, 'tile_wood', 16, 16, (g) => {
    FLAT(g, '#c28a54', 0, 0, 16, 16)
    for (let r = 0; r < 4; r++) {
      FLAT(g, r % 2 ? '#b97e49' : '#c9925c', 0, r * 4, 16, 3)
      FLAT(g, '#9d6a3b', 0, r * 4 + 3, 16, 1)
      FLAT(g, '#9d6a3b', (r * 7) % 16, r * 4, 1, 3)
      for (let i = 0; i < 3; i++) if (noise(i, r, 1) > 0.5) FLAT(g, '#d6a06a', Math.floor(noise(i, r, 2) * 14), r * 4 + 1, 2, 1)
    }
  })
  drawTexture(scene, 'tile_check', 16, 16, (g) => {
    FLAT(g, '#f3e5c8', 0, 0, 16, 16)
    FLAT(g, '#e4d0a8', 0, 0, 8, 8)
    FLAT(g, '#e4d0a8', 8, 8, 8, 8)
  })
  drawTexture(scene, 'tile_grass', 16, 16, (g) => {
    FLAT(g, '#7dba5a', 0, 0, 16, 16)
    for (let i = 0; i < 14; i++) {
      FLAT(g, noise(i, 3, 3) > 0.5 ? '#6aa84a' : '#8fcb68', Math.floor(noise(i, 1, 4) * 15), Math.floor(noise(i, 2, 5) * 15), 1, 2)
    }
  })
  drawTexture(scene, 'tile_patio', 16, 16, (g) => {
    FLAT(g, '#dcd2c0', 0, 0, 16, 16)
    FLAT(g, '#c8bca6', 0, 7, 16, 1)
    FLAT(g, '#c8bca6', 7, 0, 1, 7)
    FLAT(g, '#c8bca6', 12, 8, 1, 8)
  })
  drawTexture(scene, 'tile_path', 16, 16, (g) => {
    FLAT(g, '#e7d9bd', 0, 0, 16, 16)
    FLAT(g, '#d6c5a2', 0, 15, 16, 1)
    FLAT(g, '#d6c5a2', 15, 0, 1, 16)
    for (let i = 0; i < 3; i++) FLAT(g, '#efe4cc', Math.floor(noise(i, 9, 6) * 12), Math.floor(noise(i, 8, 7) * 12), 2, 1)
  })
  drawTexture(scene, 'tile_rug', 16, 16, (g) => {
    FLAT(g, '#6c86b8', 0, 0, 16, 16)
    FLAT(g, '#7a94c4', 0, 0, 8, 8)
    FLAT(g, '#7a94c4', 8, 8, 8, 8)
  })
  drawTexture(scene, 'tile_wall', 16, 16, (g) => {
    FLAT(g, '#efd9ac', 0, 0, 16, 16)
    FLAT(g, '#d9bf8a', 0, 15, 16, 1)
    FLAT(g, '#e3cb9b', 0, 7, 16, 1)
  })

  // station: hob + counter (46x16)
  drawTexture(scene, 'station', 46, 16, (g) => {
    FLAT(g, OUTLINE, 0, 0, 46, 16)
    FLAT(g, '#c78b57', 1, 1, 44, 3)
    FLAT(g, '#5b6470', 1, 4, 44, 4)
    FLAT(g, '#2b2f36', 6, 5, 10, 2)
    FLAT(g, '#2b2f36', 30, 5, 10, 2)
    FLAT(g, '#8a5a3a', 1, 8, 44, 7)
    FLAT(g, '#a06b44', 1, 8, 44, 1)
    FLAT(g, '#e5d8c0', 4, 10, 2, 2)
    FLAT(g, '#e5d8c0', 20, 10, 2, 2)
    FLAT(g, '#e5d8c0', 36, 10, 2, 2)
  })
  // table w/ umbrella (outdoor) and round table (indoor)
  drawTexture(scene, 'umbrella', 26, 22, (g) => {
    FLAT(g, '#6b4a30', 12, 8, 2, 12)
    for (let i = 0; i < 6; i++) FLAT(g, i % 2 ? '#ffffff' : '#e5533d', 1 + i * 4, 4 + (i === 0 || i === 5 ? 3 : i === 1 || i === 4 ? 1 : 0), 4, 5)
    FLAT(g, OUTLINE, 3, 3, 20, 1)
    FLAT(g, '#d6c5a2', 6, 18, 14, 3)
  })
  drawTexture(scene, 'tree', 20, 24, (g) => {
    FLAT(g, '#6b4a30', 8, 15, 4, 9)
    discPixels(g, 10, 8, 8, '#4f9a45')
    discPixels(g, 7, 6, 4, '#63b255')
    FLAT(g, '#3f7c37', 5, 13, 11, 2)
  })
  drawTexture(scene, 'plant', 8, 12, (g) => {
    FLAT(g, '#b5452a', 1, 8, 6, 4)
    FLAT(g, '#4f9a45', 3, 1, 2, 7)
    FLAT(g, '#63b255', 1, 3, 2, 3)
    FLAT(g, '#63b255', 5, 2, 2, 3)
  })
  drawTexture(scene, 'bench', 22, 8, (g) => {
    FLAT(g, OUTLINE, 0, 0, 22, 8)
    FLAT(g, '#b97c4f', 1, 1, 20, 3)
    FLAT(g, '#8a5a3a', 1, 4, 20, 2)
    FLAT(g, OUTLINE, 2, 6, 2, 2)
    FLAT(g, OUTLINE, 18, 6, 2, 2)
  })
  drawTexture(scene, 'door', 12, 32, (g) => {
    FLAT(g, OUTLINE, 0, 0, 12, 32)
    FLAT(g, '#8a5a3a', 1, 1, 10, 30)
    FLAT(g, '#a06b44', 2, 2, 8, 12)
    FLAT(g, '#a06b44', 2, 17, 8, 12)
    FLAT(g, '#ffd84a', 8, 15, 2, 2)
  })
  drawTexture(scene, 'window', 22, 16, (g) => {
    FLAT(g, OUTLINE, 0, 0, 22, 16)
    FLAT(g, '#bfe3f5', 1, 1, 20, 14)
    FLAT(g, '#e6f5fc', 2, 2, 5, 3)
    FLAT(g, OUTLINE, 10, 1, 2, 14)
    FLAT(g, OUTLINE, 1, 7, 20, 2)
  })
  drawTexture(scene, 'awning', 88, 12, (g) => {
    FLAT(g, OUTLINE, 0, 0, 88, 12)
    for (let i = 0; i < 11; i++) FLAT(g, i % 2 ? '#ffffff' : '#e5533d', 1 + i * 8, 1, 8, 8)
    for (let i = 0; i < 11; i++) FLAT(g, i % 2 ? '#ffffff' : '#e5533d', 1 + i * 8, 9, 8, 2)
    FLAT(g, '#00000033', 0, 11, 88, 1)
  })
  drawTexture(scene, 'counterC', 84, 14, (g) => {
    FLAT(g, OUTLINE, 0, 0, 84, 14)
    FLAT(g, '#d9c7a3', 1, 1, 82, 3)
    FLAT(g, '#8a5a3a', 1, 4, 82, 9)
    FLAT(g, '#a06b44', 1, 4, 82, 1)
  })
  drawTexture(scene, 'rope', 4, 8, (g) => {
    FLAT(g, '#b8860b', 1, 0, 2, 8)
    FLAT(g, '#ffd84a', 0, 0, 4, 2)
  })
  // puffs of steam. small = friendly white; big = angry.
  drawTexture(scene, 'steam_s', 10, 10, (g) => {
    discPixels(g, 5, 5, 4, '#dfe6ee')
    discPixels(g, 4, 4, 3, '#ffffff')
  })
  drawTexture(scene, 'steam_big', 20, 18, (g) => {
    discPixels(g, 10, 9, 8, '#cdd5df')
    discPixels(g, 8, 7, 6, '#ffffff')
    discPixels(g, 14, 8, 4, '#f4f6f9')
    // angry eyes + brows
    FLAT(g, '#c1121f', 5, 5, 3, 1)
    FLAT(g, '#c1121f', 12, 5, 3, 1)
    FLAT(g, '#c1121f', 4, 4, 2, 1)
    FLAT(g, '#c1121f', 14, 4, 2, 1)
    FLAT(g, '#26211f', 6, 7, 2, 2)
    FLAT(g, '#26211f', 12, 7, 2, 2)
    FLAT(g, '#c1121f', 8, 12, 4, 1)
  })
}

/** speech bubble background texture sized to content */
export function bubbleTexture(scene: Phaser.Scene, w: number, h: number): string {
  const key = `bubble|${w}|${h}`
  drawTexture(scene, key, w, h + 4, (g) => {
    FLAT(g, OUTLINE, 1, 0, w - 2, h)
    FLAT(g, OUTLINE, 0, 1, w, h - 2)
    FLAT(g, '#fffdf7', 1, 1, w - 2, h - 2)
    const cx = Math.floor(w / 2)
    FLAT(g, OUTLINE, cx - 2, h, 5, 1)
    FLAT(g, '#fffdf7', cx - 1, h, 3, 1)
    FLAT(g, OUTLINE, cx - 1, h + 1, 3, 1)
    FLAT(g, '#fffdf7', cx, h + 1, 1, 1)
    FLAT(g, OUTLINE, cx, h + 2, 1, 1)
  })
  return key
}
