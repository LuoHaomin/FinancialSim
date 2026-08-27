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

export async function openStream(id: string) {
  closeStream()
  simId.set(id)
  resetSeries()
  await refreshMeta(id)
  await refreshShocks(id)
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(
    `${proto}://${location.host}/api/sims/${id}/ws`)
  ws.onmessage = async (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.type === 'tick') {
      const s = get(series)
      if (msg.t > s.t[s.t.length - 1] ?? -1) {
        if (msg.t > (s.t[s.t.length - 1] ?? -1) + 1) {
          await backfill(id)                       // 缺口 → 补数
        } else {
          pushFrame(msg.t, msg.macro)
        }
      }
    }
  }
  ws.onclose = () => { /* Svelte 组件层负责重连 */ }
}

export function closeStream() {
  if (ws) { ws.close(); ws = null }
}

export async function refreshMeta(id: string) {
  meta.set(await api.meta(id))
}

export async function refreshShocks(id: string) {
  const log = await api.interventions(id)
  shocks.set(log.map((e) => ({ t: e.t, name: e.name, channel: e.channel })))
}
