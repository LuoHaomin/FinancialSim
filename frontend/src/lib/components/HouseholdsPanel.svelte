<script lang="ts">
  // 家庭部门面板: 分布统计 (Gini/五分位/住房/就业), 服务端聚合
  import ChartFrame from './ChartFrame.svelte'
  import { api, type HouseholdsStats } from '../api'
  import { simId } from '../stores/connection'
  import type { EChartsOption } from 'echarts'

  let st = $state<HouseholdsStats | null>(null)
  let error = $state('')
  let auto = $state(true)

  const pct = (v: number | null | undefined, d = 1) =>
    v === null || v === undefined ? '—' : (v * 100).toFixed(d) + '%'
  const fmt = (v: number | null | undefined) =>
    v === null || v === undefined ? '—' : v.toFixed(2)

  async function refresh() {
    const id = $simId
    if (!id) return
    try { st = await api.households(id); error = '' }
    catch (e) { error = String(e) }
  }

  $effect(() => {
    const id = $simId
    if (!id) return
    refresh()
    if (!auto) return
    const timer = setInterval(refresh, 8000)
    return () => clearInterval(timer)
  })

  const quintileOption = $derived.by(() => {
    if (!st) return {} as EChartsOption
    return {
      animation: false,
      title: { text: '财富五分位 (组均值)', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 16, top: 34, bottom: 26 },
      xAxis: { type: 'category',
               data: ['Q1 (最穷)', 'Q2', 'Q3', 'Q4', 'Q5 (最富)'] },
      yAxis: { type: 'value' },
      series: [
        { type: 'bar', name: '财富', data: st.wealth_quintiles,
          itemStyle: { color: '#58a6ff' } },
      ],
    } as EChartsOption
  })

  const histOption = $derived.by(() => {
    if (!st) return {} as EChartsOption
    return {
      animation: false,
      title: { text: '财富分布直方图', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 16, top: 34, bottom: 26 },
      xAxis: { type: 'category',
               data: st.wealth_histogram.bin_edges.slice(0, -1)
                 .map((e, i) => Math.round(e) + '~'
                   + Math.round(st!.wealth_histogram.bin_edges[i + 1])) },
      yAxis: { type: 'value', name: '家庭数' },
      series: [
        { type: 'bar', data: st.wealth_histogram.counts,
          itemStyle: { color: '#bc8cff' }, barCategoryGap: '10%' },
      ],
    } as EChartsOption
  })
</script>

<div class="card">
  <div class="row">
    <h3>家庭部门 · t = {st?.t ?? '—'}</h3>
    <span class="sep"></span>
    <button onclick={refresh}>刷新</button>
    <label class="hint"><input type="checkbox" bind:checked={auto} /> 自动 (8s)</label>
  </div>
  {#if error}<p class="err">{error}</p>{/if}
  {#if st}
    <div class="kpi-grid" style="margin-top:10px">
      <div class="kpi">
        <div class="kpi-label">家庭数</div>
        <div class="kpi-value">{st.n}</div>
        <div class="kpi-sub">就业率 {pct(st.employment_rate)}</div>
      </div>
      <div class="kpi tone-warn">
        <div class="kpi-label">财富 Gini</div>
        <div class="kpi-value">{st.gini_wealth.toFixed(3)}</div>
        <div class="kpi-sub">收入 Gini {st.gini_income.toFixed(3)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Top 10% 财富份额</div>
        <div class="kpi-value">{pct(st.top10_wealth_share)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">住房自有率</div>
        <div class="kpi-value">{pct(st.homeownership_rate)}</div>
        <div class="kpi-sub">{st.mortgagors} 户有按揭</div>
      </div>
      <div class="kpi tone-{(st.mortgage_missed_share ?? 0) > 0.05 ? 'bad' : 'good'}">
        <div class="kpi-label">按揭断供压力</div>
        <div class="kpi-value">{pct(st.mortgage_missed_share)}</div>
        <div class="kpi-sub">负资产占比 {pct(st.negative_equity_share)}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">失业</div>
        <div class="kpi-value">{st.unemployed}</div>
        <div class="kpi-sub">平均失业 {fmt(st.avg_unemployment_duration)} 月</div>
      </div>
    </div>
    <div class="grid-2" style="margin-top:12px">
      <ChartFrame option={quintileOption} />
      <ChartFrame option={histOption} />
    </div>
  {:else}
    <p class="hint">加载中…</p>
  {/if}
</div>
