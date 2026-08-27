// API 客户端 (只读投影 + 受控干预). 见 docs/FRONTEND_DESIGN.md §0
export interface SimMeta {
  sim_id: string
  name: string
  t: number
  n_ticks_config: number
  speed: number
  paused: boolean
  sfc_violations: number
}

export interface MacroFrame {
  real_gdp: number
  inflation_yoy: number
  unemployment_rate: number
  policy_rate: number
  housing_price: number | null
}

export interface SeriesData {
  t: number[]
  real_gdp: number[]
  inflation_yoy: number[]
  unemployment_rate: number[]
  policy_rate: number[]
  housing_price: (number | null)[]
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`)
  return r.json()
}

export const api = {
  async createSim(scenario: string): Promise<string> {
    const r = await fetch('/api/sims', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario }),
    })
    return ((await j<{ sim_id: string }>(r)).sim_id)
  },
  meta: (id: string) => fetch(`/api/sims/${id}`).then((r) => j<SimMeta>(r)),
  series: (id: string) =>
    fetch(`/api/sims/${id}/series`).then((r) => j<SeriesData>(r)),
  command: (id: string, cmd: { speed?: number; step?: number }) =>
    fetch(`/api/sims/${id}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cmd),
    }).then((r) => j(r)),
  async interventions(id: string) {
    return j<
      { t: number; name: string; channel: string; magnitude: number }[]
    >(await fetch(`/api/sims/${id}/interventions`))
  },
  async intervention(
    id: string,
    body: {
      preset: string
      trigger_offset: number
      duration?: number
    },
  ) {
    const r = await fetch(`/api/sims/${id}/interventions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
  },
}

export const SCENARIOS = [
  { id: 'baseline', label: '基准' },
  { id: 'crisis_2008', label: '2008 危机' },
  { id: 'stagflation', label: '滞胀' },
  { id: 'housing_bust', label: '房产泡沫破裂' },
  { id: 'post_war_recovery', label: '战后复苏' },
  { id: 'tight_credit', label: '信贷紧缩' },
  { id: 'loose_credit', label: '宽松信贷' },
]

export const SHOCK_PRESETS = [
  { id: 'tightening_50bp_6m', label: '加息 50bp (6月)' },
  { id: 'easing_50bp_6m', label: '降息 50bp (6月)' },
  { id: 'fiscal_austerity_30p_12m', label: '财政紧缩 30%' },
  { id: 'fiscal_stimulus_20p_12m', label: '财政刺激 20%' },
  { id: 'tax_hike_5pp_24m', label: '加税 5pp' },
  { id: 'energy_shock_plus30p', label: '能源冲击 +30%' },
  { id: 'wage_shock_plus10p', label: '工资冲击 +10%' },
  { id: 'housing_risk_premium_spike', label: '房产风险溢价飙升' },
]
