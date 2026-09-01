// API 客户端 (只读投影 + 受控干预). 见 docs/FRONTEND_DESIGN.md §0
// 场景/冲击预设从 /api/meta 拉取, 不再前端硬编码.

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
  nominal_gdp: number
  inflation_yoy: number
  unemployment_rate: number
  policy_rate: number
  avg_wage: number
  total_consumption: number
  total_output: number
  housing_price: number | null
}

export interface SeriesData {
  t: number[]
  real_gdp: number[]
  nominal_gdp: number[]
  inflation_yoy: number[]
  unemployment_rate: number[]
  policy_rate: number[]
  avg_wage: number[]
  total_consumption: number[]
  total_output: number[]
  housing_price: (number | null)[]
  price_level: (number | null)[]
}

export interface FirmRow {
  id: string; sector: string; employees: number; price: number
  deposits: number; debt: number; last_sales: number; is_bankrupt: boolean
}

export interface BankRow {
  id: string; capital: number; car: number | null; reserves: number
  loans_to_firms: number; loans_to_households: number; is_failed: boolean
}

export interface AssetLiabilityView {
  sector: string; id: string
  assets: Record<string, number>
  liabilities?: Record<string, number>
  net_worth?: number
  capital?: number
  car?: number | null
  operational?: Record<string, unknown>
  is_failed?: boolean
}

export interface ShockLogEntry {
  t: number; name: string; channel: string; magnitude: number
}

// ── /api/meta ──
export interface ScenarioInfo {
  id: string; name: string; description: string
}
export interface ShockPresetInfo {
  id: string; channel: string; magnitude: number
  duration: number; one_shot: boolean; description: string
}
export interface MetaInfo {
  scenarios: ScenarioInfo[]
  shock_presets: ShockPresetInfo[]
  custom_channels: string[]
}

// ── 扩展投影 ──
export interface SectorSheet {
  label: string
  assets: Record<string, number>
  liabilities: Record<string, number>
  capital: number
  total_assets: number
  total_liabilities: number
  net_worth: number
  balanced: boolean
}
export interface SectorsMatrix {
  t: number
  sectors: Record<string, SectorSheet>
}

export interface HouseholdsStats {
  t: number; n: number
  employment_rate: number | null
  gini_wealth: number; gini_income: number
  wealth_quintiles: number[]; income_quintiles: number[]
  top10_wealth_share: number | null
  homeownership_rate: number | null
  mortgagors: number
  mortgage_missed_share: number | null
  negative_equity_share: number | null
  unemployed: number
  avg_unemployment_duration: number
  wealth_histogram: { bin_edges: number[]; counts: number[] }
  unemployment_duration_histogram: { counts: number[] }
}

export interface GovernmentView {
  t: number
  assets: Record<string, number>
  liabilities: Record<string, number>
  net_worth: number
  flows: Record<string, number>
  parameters: Record<string, number>
}

export interface CentralBankView {
  t: number
  assets: Record<string, number>
  liabilities: Record<string, number>
  capital: number
  policy: Record<string, number>
  monetary_base: number
}

export interface NetworkData {
  t: number; kind: string
  nodes: {
    id: string; capital?: number; car?: number | null
    failed?: boolean; core?: boolean
    is_firm?: boolean; degree_value?: number
  }[]
  edges: { source: string; target: string; value: number
           bidirectional?: boolean }[]
}

export interface StressView {
  t: number
  fire_sale_pressure: number
  housing_expectations_factor: number
  failed_banks: string[]
  failed_banks_now: number
  bankrupt_firms: number
  bank_car: { min: number | null; max: number | null; mean: number | null
              below_requirement: number }
  housing: {
    price: number; rent: number | null; rental_yield: number | null
    sales_volume_month: number | null; cumulative_default_units: number | null
  }
  stock_price: number
}

export interface SfcDetail {
  total_count: number
  detail: { t: number; errors: string[] }[]
}

// ── 错误对象: FastAPI detail → 用户可读 ──
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status}`
    try {
      const body = await r.json()
      const d = body?.detail
      if (typeof d === 'string') msg = d
      else if (Array.isArray(d) && d[0]?.msg) msg = d[0].msg
      else msg = JSON.stringify(body).slice(0, 200)
    } catch { msg = `${r.status}: ${await r.text().catch(() => '')}` }
    throw new ApiError(r.status, msg)
  }
  return r.json()
}

const post = (url: string, body: unknown) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const api = {
  async metaInfo(): Promise<MetaInfo> {
    return j(await fetch('/api/meta'))
  },
  async createSim(scenario: string): Promise<string> {
    return ((await j<{ sim_id: string }>(await post('/api/sims', {
      scenario, autostart_speed: 0,
    }))).sim_id)
  },
  listSims: () => fetch('/api/sims').then((r) => j<SimMeta[]>(r)),
  meta: (id: string) => fetch(`/api/sims/${id}`).then((r) => j<SimMeta>(r)),
  series: (id: string) =>
    fetch(`/api/sims/${id}/series`).then((r) => j<SeriesData>(r)),
  seriesSlice: (id: string, fromT: number) =>
    fetch(`/api/sims/${id}/series?from_t=${fromT}`)
      .then((r) => j<SeriesData>(r)),
  closeSim: (id: string) =>
    fetch(`/api/sims/${id}`, { method: 'DELETE' }).then((r) => j(r)),
  command: (id: string, cmd: { speed?: number; step?: number }) =>
    post(`/api/sims/${id}/command`, cmd).then((r) => j(r)),
  interventions: (id: string) =>
    fetch(`/api/sims/${id}/interventions`)
      .then((r) => j<ShockLogEntry[]>(r)),
  intervention: (
    id: string,
    body: {
      preset?: string; channel?: string; magnitude?: number
      trigger_offset: number; duration?: number
    },
  ) => post(`/api/sims/${id}/interventions`, body).then((r) => j(r)),
  agentsTable: {
    firms: (id: string) =>
      fetch(`/api/sims/${id}/agents/firms`).then((r) => j<FirmRow[]>(r)),
    banks: (id: string) =>
      fetch(`/api/sims/${id}/agents/banks`).then((r) => j<BankRow[]>(r)),
  },
  agentDetail: (id: string, sector: string, agentId: string) =>
    fetch(`/api/sims/${id}/agent/${sector}/${agentId}`)
      .then((r) => j<AssetLiabilityView>(r)),
  // ── 扩展投影 ──
  sectors: (id: string) =>
    fetch(`/api/sims/${id}/sectors`).then((r) => j<SectorsMatrix>(r)),
  households: (id: string) =>
    fetch(`/api/sims/${id}/households`).then((r) => j<HouseholdsStats>(r)),
  government: (id: string) =>
    fetch(`/api/sims/${id}/agents/government`)
      .then((r) => j<GovernmentView>(r)),
  centralBank: (id: string) =>
    fetch(`/api/sims/${id}/agents/central_bank`)
      .then((r) => j<CentralBankView>(r)),
  network: (id: string, kind: 'interbank' | 'cross_holdings') =>
    fetch(`/api/sims/${id}/network/${kind}`)
      .then((r) => j<NetworkData>(r)),
  stress: (id: string) =>
    fetch(`/api/sims/${id}/stress`).then((r) => j<StressView>(r)),
  sfc: (id: string) =>
    fetch(`/api/sims/${id}/sfc`).then((r) => j<SfcDetail>(r)),
}
