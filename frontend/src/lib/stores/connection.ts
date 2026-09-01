// 连接层: WS 协议 v1 为主通道 (tick/ack/intervention), REST 只做
// 启动回填 + 断线兜底 (设计 §5.2). 同 seed 同干预逐位复现不受影响.
import { writable, get } from 'svelte/store'
import { api, type MacroFrame, type SimMeta } from '../api'

export const simId = writable<string | null>(null)
export const meta = writable<SimMeta | null>(null)
export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed'
export const wsStatus = writable<WsStatus>('idle')

export interface ShockMark {
  t: number
  name: string
  channel: string
  magnitude?: number
}

const EMPTY: Record<string, (number | null)[]> = {
  t: [], real_gdp: [], nominal_gdp: [], inflation_yoy: [],
  unemployment_rate: [], policy_rate: [], avg_wage: [],
  total_consumption: [], total_output: [], housing_price: [],
  price_level: [],
}

// 指标序列 (与后端 series 列对齐; 列长一致)
export const series = writable<Record<string, (number | null)[]>>({ ...EMPTY })
export const shocks = writable<ShockMark[]>([])

let ws: WebSocket | null = null
let reconnectDelay = 500          // 指数退避: 0.5s → 最大 8s
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let currentId: string | null = null

export function resetSeries() {
  series.set({ ...EMPTY, t: [], real_gdp: [], nominal_gdp: [],
    inflation_yoy: [], unemployment_rate: [], policy_rate: [],
    avg_wage: [], total_consumption: [], total_output: [],
    housing_price: [], price_level: [] })
  shocks.set([])
}

// ── 序列合并 (REST backfill 与 WS tick 共用) ──
function appendRows(data: Record<string, (number | null)[]>) {
  if (!data.t?.length) return
  series.update((cur) => {
    const out: Record<string, (number | null)[]> = { ...cur }
    for (const k of Object.keys(EMPTY)) {
      const incoming = data[k] ?? []
      out[k] = [...(cur[k] ?? []), ...incoming]
    }
    return out
  })
}

// WS tick 帧: state.t 已自增, 对应快照标签 t-1 (后端测试注释锁定的语义)
type TickMacro = MacroFrame & { speed_hint?: number }
function onTickFrame(t: number, m: TickMacro, eventsFired: string[],
                     sfcCount: number) {
  const label = t - 1
  const cur = get(series)
  if (label >= 0 &&
      (!cur.t.length || label > (cur.t[cur.t.length - 1] as number))) {
    appendRows({
      t: [label],
      real_gdp: [m.real_gdp], nominal_gdp: [m.nominal_gdp],
      inflation_yoy: [m.inflation_yoy],
      unemployment_rate: [m.unemployment_rate],
      policy_rate: [m.policy_rate], avg_wage: [m.avg_wage],
      total_consumption: [m.total_consumption],
      total_output: [m.total_output],
      housing_price: [m.housing_price], price_level: [null],
    })
  }
  meta.update((mm) => mm
    ? { ...mm, t, speed: m.speed_hint ?? mm.speed,
        sfc_violations: sfcCount }
    : mm)
  if (eventsFired.length > 0) refreshShocks(get(simId)!)
  // 每 25 tick 全量重同步一次 (补 price_level 等 WS 帧缺失的派生列)
  if (label > 0 && label % 25 === 0 && get(simId)) {
    resyncSeries(get(simId)!).catch(() => {})
  }
}

function connectWs(id: string) {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  wsStatus.set('connecting')
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  try {
    ws = new WebSocket(`${proto}://${location.host}/api/sims/${id}/ws`)
  } catch {
    scheduleReconnect(id)
    return
  }
  ws.onopen = () => {
    reconnectDelay = 500
    wsStatus.set('open')
  }
  ws.onmessage = (ev) => {
    let msg: Record<string, unknown>
    try { msg = JSON.parse(ev.data) } catch { return }
    if (msg.type === 'tick') {
      // speed 从帧顶层读 (macro 里没有)
      const frame = msg as unknown as {
        t: number; macro: MacroFrame & { speed?: number }
        events_fired: string[]; sfc_violations: number
      }
      onTickFrame(frame.t, { ...frame.macro, speed_hint: frame.macro.speed },
        frame.events_fired, frame.sfc_violations)
    }
    // ack / intervention_ack: 命令确认, 无需处理 (REST 同步路径已刷新 meta)
  }
  ws.onclose = () => {
    ws = null
    if (currentId === id) scheduleReconnect(id)
  }
  ws.onerror = () => { /* onclose 会接手 */ }
}

function scheduleReconnect(id: string) {
  wsStatus.set('closed')
  if (currentId !== id) return
  // 兜底: 断线期间用 REST 补数
  pollOnce(id).catch(() => {})
  if (reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (currentId === id) connectWs(id)
  }, reconnectDelay)
  reconnectDelay = Math.min(8000, reconnectDelay * 2)
}

// 全量重同步 (周期性调用, 修补 WS tick 只能填 null 的派生列如 price_level)
export async function resyncSeries(id: string) {
  const data = await api.series(id)
  series.set(data as unknown as Record<string, (number | null)[]>)
}

// REST 兜底补数 (仅在 WS 断开时使用)
async function pollOnce(id: string) {
  const s = get(series)
  const last = (s.t[s.t.length - 1] as number) ?? -1
  const data = await api.seriesSlice(id, last + 1)
  appendRows(data as unknown as Record<string, (number | null)[]>)
  await refreshMeta(id).catch(() => {})
}

export async function openStream(id: string) {
  closeStream()
  currentId = id
  simId.set(id)
  resetSeries()
  await refreshMeta(id)
  await refreshShocks(id)
  // 初始全量历史回填 (REST)
  try {
    const data = await api.series(id)
    appendRows(data as unknown as Record<string, (number | null)[]>)
  } catch { /* 后端瞬断: WS/重连会补 */ }
  connectWs(id)
}

export function closeStream() {
  currentId = null
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws) { ws.onclose = null; ws.close(); ws = null }
  wsStatus.set('idle')
}

// ── 播放控制: WS 优先, REST 兜底 ──
export async function setSpeed(v: number) {
  const id = get(simId)
  if (!id) return
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ cmd: 'set_speed', value: v }))
  } else {
    await api.command(id, { speed: v }).catch(() => {})
  }
  meta.update((m) => m ? { ...m, speed: v, paused: v === 0 } : m)
}

export async function pause() { await setSpeed(0) }

export async function stepOnce(n = 1) {
  const id = get(simId)
  if (!id) return
  if (ws && ws.readyState === WebSocket.OPEN) {
    for (let i = 0; i < n; i++) ws.send(JSON.stringify({ cmd: 'step' }))
  } else {
    await api.command(id, { step: n }).catch(() => {})
  }
  await refreshMeta(id).catch(() => {})
}

export async function runTo(t: number) {
  const id = get(simId)
  if (!id) return
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ cmd: 'run_to', t }))
  }
  await refreshMeta(id).catch(() => {})
}

export async function refreshMeta(id: string) {
  meta.set(await api.meta(id))
}

export async function refreshShocks(id: string) {
  const log = await api.interventions(id)
  shocks.set(log.map((e) => ({
    t: e.t, name: e.name, channel: e.channel, magnitude: e.magnitude,
  })))
}

// e2e 冒烟可读取 (window.__fsim.series.t.length)
if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__fsim = {
    get series() { return get(series) },
    get meta() { return get(meta) },
    get wsStatus() { return get(wsStatus) },
  }
}
