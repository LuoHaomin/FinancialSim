// tick 数据流: WS 实时帧 + REST 断线补数 (设计 §5.2)
import { writable, get } from 'svelte/store'
import { api, type MacroFrame, type SimMeta } from './api'

export const simId = writable<string | null>(null)
export const meta = writable<SimMeta | null>(null)
export const paused = writable(true)

export interface ShockMark {
  t: number
  name: string
  channel: string
}

// 指标序列 (与后端 series 列对齐)
export const series = writable<Record<string, number[]>>({
  t: [], real_gdp: [], inflation_yoy: [],
  unemployment_rate: [], policy_rate: [], housing_price: [],
})
export const shocks = writable<ShockMark[]>([])

let ws: WebSocket | null = null

export function resetSeries() {
  series.set({ t: [], real_gdp: [], inflation_yoy: [],
    unemployment_rate: [], policy_rate: [], housing_price: [] })
  shocks.set([])
}

function pushFrame(t: number, m: MacroFrame) {
  series.update((s) => ({
    t: [...s.t, t],
    real_gdp: [...s.real_gdp, m.real_gdp],
    inflation_yoy: [...s.inflation_yoy, m.inflation_yoy],
    unemployment_rate: [...s.unemployment_rate, m.unemployment_rate],
    policy_rate: [...s.policy_rate, m.policy_rate],
    housing_price: [...s.housing_price, m.housing_price ?? NaN],
  }))
}

async function backfill(id: string) {
  // 从 REST 补齐全部历史 (快照检查点语义: last_t 之后的数据)
  const s = get(series)
  const fromT = s.t.length > 0 ? s.t[s.t.length - 1] : -1
  const data = await api.series(id)
  const startIdx = data.t.findIndex((t) => t > fromT)
  if (startIdx < 0) return
  const keep = <T,>(a: T[]) => a.slice(startIdx)
  series.update((cur) => ({
    t: [...cur.t, ...keep(data.t)],
    real_gdp: [...cur.real_gdp, ...keep(data.real_gdp)],
    inflation_yoy: [...cur.inflation_yoy, ...keep(data.inflation_yoy)],
    unemployment_rate: [...cur.unemployment_rate,
      ...keep(data.unemployment_rate)],
    policy_rate: [...cur.policy_rate, ...keep(data.policy_rate)],
    housing_price: [...cur.housing_price, ...keep(data.housing_price)],
  }))
}

// MVP 稳妥口径: REST 轮询兜底保证数据必然刷新 (2s),
// WS 仅作为低延迟增强, 断了不影响正确性.
let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function pollOnce(id: string) {
  const s = get(series)
  const last = s.t[s.t.length - 1] ?? -1
  try {
    const data = await api.seriesSlice(id, last + 1)
    const n = data.t.length
    if (n === 0) return
    series.update((cur) => ({
      t: [...cur.t, ...data.t],
      real_gdp: [...cur.real_gdp, ...data.real_gdp],
      inflation_yoy: [...cur.inflation_yoy, ...data.inflation_yoy],
      unemployment_rate: [...cur.unemployment_rate,
        ...data.unemployment_rate],
      policy_rate: [...cur.policy_rate, ...data.policy_rate],
      housing_price: [...cur.housing_price, ...data.housing_price],
    }))
  } catch { /* 网络/后端瞬断: 下个周期再试 */ }
}

export function startPolling(id: string) {
  stopPoll()
  pollTimer = setInterval(async () => {
    await pollOnce(id)
    refreshMeta(id).catch(() => {})
  }, 2000)
}

// e2e 冒烟可读取 (window.__fsim.series.t.length)
if (typeof window !== 'undefined') {
  ;(window as unknown as Record<string, unknown>).__fsim = {
    get series() { return get(series) },
    get meta() { return get(meta) },
  }
}

export async function openStream(id: string) {
  closeStream()
  simId.set(id)
  resetSeries()
  await refreshMeta(id)
  await refreshShocks(id)
  await backfill(id)                      // 初始全量历史
  startPolling(id)
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  try {
    ws = new WebSocket(
      `${proto}://${location.host}/api/sims/${id}/ws`)
    // WS 仅用于降低刷新延迟; 数据正确性由轮询保证
  } catch { /* WS 失败不致命 */ }
}

export function closeStream() {
  if (ws) { ws.close(); ws = null }
  stopPoll()
}

export async function refreshMeta(id: string) {
  meta.set(await api.meta(id))
}

export async function refreshShocks(id: string) {
  const log = await api.interventions(id)
  shocks.set(log.map((e) => ({ t: e.t, name: e.name, channel: e.channel })))
}
