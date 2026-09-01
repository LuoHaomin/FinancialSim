<script lang="ts" module>
  // 统一 ECharts 主题常量 (深色终端风)
  export const CHART_COLORS = {
    gdp: '#58a6ff', unemployment: '#f85149', inflation: '#d29922',
    policy: '#3fb950', housing: '#bc8cff', wage: '#39c5cf',
    consumption: '#39c5cf', output: '#8b949e', shock: '#ff7875',
  }
</script>

<script lang="ts">
  // 通用响应式 ECharts 封装: option 变化即 setOption (不再盲定时重绘)
  import { onMount, onDestroy } from 'svelte'
  import * as echarts from 'echarts'

  let { option, merge = false } = $props<{
    option: echarts.EChartsOption
    merge?: boolean
  }>()

  let el: HTMLDivElement
  let chart: echarts.ECharts | null = null

  onMount(() => {
    chart = echarts.init(el, 'dark')
    chart.setOption({ backgroundColor: 'transparent' }, true)
    const ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el)
    return () => ro.disconnect()
  })
  onDestroy(() => chart?.dispose())

  $effect(() => {
    // 依赖 option 引用变化 (父组件 $derived 每次生成新对象)
    if (chart && option) chart.setOption(option, !merge)
  })
</script>

<div bind:this={el} class="chart-box" style="height:100%"></div>
