<script lang="ts">
  // L1 宏观看板: KPI 卡片 + 主时序 (dataZoom/悬停含冲击参数) + 副面板
  import ChartFrame, { CHART_COLORS as C } from './ChartFrame.svelte'
  import { series, shocks, meta } from '../stores/connection'
  import { api, type StressView } from '../api'
  import type { EChartsOption } from 'echarts'

  const fmtPct = (v: number | null | undefined, d = 1) =>
    v === null || v === undefined ? '—' : (v * 100).toFixed(d) + '%'
  const fmtNum = (v: number | null | undefined) =>
    v === null || v === undefined ? '—'
      : Math.abs(v) >= 10000 ? (v / 1000).toFixed(1) + 'k'
      : v.toFixed(1)

  const last = (k: string): number | null => {
    const col = $series[k] ?? []
    const v = col[col.length - 1]
    return v === null || v === undefined ? null : v
  }

  const kpis = $derived([
    { label: '实际 GDP', value: fmtNum(last('real_gdp')), sub: '月度产出' },
    { label: '名义 GDP', value: fmtNum(last('nominal_gdp')), sub: '当期价格' },
    { label: '失业率', value: fmtPct(last('unemployment_rate')),
      sub: '劳动力占比',
      tone: (last('unemployment_rate') ?? 0) > 0.08 ? 'bad' : '' },
    { label: '通胀 (同比)', value: fmtPct(last('inflation_yoy')),
      sub: 'CPI 口径',
      tone: Math.abs(last('inflation_yoy') ?? 0) > 0.05 ? 'warn' : '' },
    { label: '政策利率', value: fmtPct(last('policy_rate'), 2), sub: 'Taylor 规则' },
    { label: '房价指数', value: fmtNum(last('housing_price')), sub: '均价/单位' },
  ])

  // 主图: 悬停 tooltip 附带该月的冲击事件与参数
  const mainOption = $derived.by(() => {
    const s = $series
    const shockAt = new Map($shocks.map((m) => [m.t, m]))
    return {
      animation: false,
      tooltip: {
        trigger: 'axis',
        formatter: (params: { axisValue: number; seriesName: string
          value: number | null }[]) => {
          const t = params[0]?.axisValue
          const lines = params
            .filter((p) => p.value !== null && p.value !== undefined)
            .map((p) => `${p.seriesName}: ${fmtNum(p.value)}`)
          const m = shockAt.get(t as number)
          if (m) {
            lines.push('',
              `⚡ ${m.name} (${m.channel}${m.magnitude !== undefined
                ? ', ' + m.magnitude : ''})`)
          }
          return `<b>t=${t}</b><br/>` + lines.join('<br/>')
        },
      },
      legend: { top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 56, right: 56, top: 32, bottom: 56 },
      xAxis: { type: 'category', data: s.t, name: '月', boundaryGap: false },
      yAxis: [
        { type: 'value', name: '水平值', scale: true },
        { type: 'value', name: '比率', scale: true,
          axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) + '%' } },
      ],
      dataZoom: [
        { type: 'inside' },
        { type: 'slider', height: 18, bottom: 8 },
      ],
      series: [
        { name: 'GDP', type: 'line', yAxisIndex: 0, showSymbol: false,
          itemStyle: { color: C.gdp }, lineStyle: { width: 1.6 },
          data: s.real_gdp,
          // 冲击标记线挂在首系列上 (label 显示完整事件名)
          ...($shocks.length > 0 ? { markLine: {
            symbol: 'none', silent: true,
            label: { show: true, fontSize: 9, color: C.shock,
                     formatter: (p: { name?: string }) => p.name ?? '' },
            data: $shocks.map((m) => ({
              xAxis: m.t, name: m.name, lineStyle: {
                color: C.shock, type: 'dashed' as const } })),
          } } : {}) },
        { name: '房价', type: 'line', yAxisIndex: 0, showSymbol: false,
          itemStyle: { color: C.housing }, lineStyle: { width: 1.6 },
          data: s.housing_price },
        { name: '失业率', type: 'line', yAxisIndex: 1, showSymbol: false,
          itemStyle: { color: C.unemployment }, lineStyle: { width: 1.6 },
          data: s.unemployment_rate },
        { name: '通胀(同比)', type: 'line', yAxisIndex: 1, showSymbol: false,
          itemStyle: { color: C.inflation }, lineStyle: { width: 1.6 },
          data: s.inflation_yoy },
        { name: '政策利率', type: 'line', yAxisIndex: 1, showSymbol: false,
          itemStyle: { color: C.policy }, lineStyle: { width: 1.6 },
          data: s.policy_rate },
        { name: '平均工资', type: 'line', yAxisIndex: 0, showSymbol: false,
          itemStyle: { color: C.wage }, lineStyle: { width: 1.2 },
          data: s.avg_wage },
      ],
    } as unknown as EChartsOption
  })

  // 副图 1: 消费 / 产出 / 工资
  const flowOption = $derived.by(() => {
    const s = $series
    return {
      animation: false,
      title: { text: '消费 / 产出 / 工资', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 16, top: 34, bottom: 24 },
      xAxis: { type: 'category', data: s.t, boundaryGap: false },
      yAxis: { type: 'value', scale: true },
      series: [
        { name: '消费', type: 'line', showSymbol: false,
          itemStyle: { color: C.consumption }, data: s.total_consumption },
        { name: '产出', type: 'line', showSymbol: false,
          itemStyle: { color: C.output }, data: s.total_output },
      ],
    } as EChartsOption
  })

  // 压力遥测 (10s 轮询)
  let stress = $state<StressView | null>(null)
  $effect(() => {
    const id = $meta?.sim_id
    if (!id) return
    let alive = true
    const tick = () => api.stress(id)
      .then((v) => { if (alive) stress = v })
      .catch(() => {})
    tick()
    const timer = setInterval(tick, 10000)
    return () => { alive = false; clearInterval(timer) }
  })
</script>

<div class="kpi-grid">
  {#each kpis as k}
    <div class="kpi {k.tone}">
      <div class="kpi-label">{k.label}</div>
      <div class="kpi-value">{k.value}</div>
      <div class="kpi-sub">{k.sub}</div>
    </div>
  {/each}
</div>

<div class="card" style="margin-top:12px">
  <ChartFrame option={mainOption} />
</div>

<div class="grid-2" style="margin-top:12px">
  <div class="card">
    <ChartFrame option={flowOption} />
  </div>
  <div class="card">
    <h3>金融压力遥测</h3>
    {#if stress}
      <div class="kpi-grid" style="margin-top:8px">
        <div class="kpi tone-{stress.fire_sale_pressure > 0.3 ? 'bad' : 'good'}">
          <div class="kpi-label">Fire-sale 压力</div>
          <div class="kpi-value">{stress.fire_sale_pressure.toFixed(2)}</div>
        </div>
        <div class="kpi tone-{stress.housing_expectations_factor > 1.15 ? 'warn' : ''}">
          <div class="kpi-label">房价泡沫因子</div>
          <div class="kpi-value">
            {stress.housing_expectations_factor.toFixed(2)}</div>
        </div>
        <div class="kpi tone-{(stress.bank_car.below_requirement ?? 0) > 0 ? 'warn' : 'good'}">
          <div class="kpi-label">银行 CAR 均值</div>
          <div class="kpi-value">
            {stress.bank_car.mean === null ? '—'
              : (stress.bank_car.mean * 100).toFixed(1) + '%'}</div>
          <div class="kpi-sub">
            {stress.bank_car.below_requirement} 家低于监管线</div>
        </div>
        <div class="kpi tone-{stress.failed_banks_now > 0 ? 'bad' : 'good'}">
          <div class="kpi-label">失败银行 / 破产企业</div>
          <div class="kpi-value">{stress.failed_banks_now} / {stress.bankrupt_firms}</div>
        </div>
      </div>
      <div class="hint" style="margin-top:8px">
        房租 {fmtNum(stress.housing.rent)} · 租金收益率 {fmtPct(stress.housing.rental_yield)}
        · 月成交 {fmtNum(stress.housing.sales_volume_month)} 单位 ·
        累计断供 {stress.housing.cumulative_default_units ?? '—'} 套
      </div>
    {:else}
      <p class="hint">加载中…</p>
    {/if}
  </div>
</div>
