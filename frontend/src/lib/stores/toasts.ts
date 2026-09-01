// toast 通知系统: 替代散落的瞬时 ✓/✗ 文本
import { writable } from 'svelte/store'

export interface Toast {
  id: number
  kind: 'ok' | 'err' | 'info'
  text: string
}

export const toasts = writable<Toast[]>([])

let nextId = 1

export function toast(text: string, kind: Toast['kind'] = 'info',
                      ttl = 3500) {
  const id = nextId++
  toasts.update((ts) => [...ts, { id, kind, text }])
  setTimeout(() => {
    toasts.update((ts) => ts.filter((t) => t.id !== id))
  }, ttl)
}

export function dismissToast(id: number) {
  toasts.update((ts) => ts.filter((t) => t.id !== id))
}
