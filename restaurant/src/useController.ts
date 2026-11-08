import { useSyncExternalStore } from 'react'
import type { Controller } from './data/controller'

/** Re-render whenever the controller state/meta changes. Returns the controller itself. */
export function useController(ctl: Controller) {
  useSyncExternalStore(ctl.subscribe, ctl.getVersion)
  return ctl
}
