import Phaser from 'phaser'
import type { Controller } from '../data/controller'
import { H, W } from './layout'
import { RestaurantScene } from './RestaurantScene'

export function createGame(parent: HTMLElement, ctl: Controller): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: W,
    height: H,
    pixelArt: true,
    roundPixels: true,
    antialias: false,
    backgroundColor: '#2a1f1a',
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    scene: [new RestaurantScene(ctl)],
    banner: false,
    audio: { noAudio: true },
  })
}
