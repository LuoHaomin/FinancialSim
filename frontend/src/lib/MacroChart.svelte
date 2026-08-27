<script lang="ts">
  // ECharts 宏观双轴时序: 量级差异大的指标分左右轴
  import { onMount, onDestroy } from 'svelte'
  import * as echarts from 'echarts'
  import { series, shocks } from './stores'

  let el: HTMLDivElement
  let chart: echarts.ECharts | null = null
  let timer: ReturnType<typeof setInterval>

  const SERIES_DEF = [
    { key: 'real_gdp', name: 'GDP', axis: 0, color: '#4a90d9' },
    { key: 'unemployment_rate', name: '失业率', axis: 1, color: '#d94a4a',
      fmt: (v: number) => (v * 100).toFixed(1) + '%' },
    { key: 'inflation_yoy', name: '通胀(同比)', axis: 1, color: '#e6a23c',
      fmt: (v: number) => (v * 100).toFixed(1) + '%' },
    { key: 'policy_rate', name: '政策利率', axis: 1, color: '#67c23a',
      fmt: (v: number) => (v * 100).toFixed(2) + '%' },
    { key: 'housing_price', name: '房价', axis: 0, color: '#8b5cf6' },
  ]

  function render() {
    if (!chart) return
    const s = $series
    const markers = $shocks.map((m) => ({
      xAxis: m.t,
      lineStyle: { color: '#ff7875', type: 'dashed' as const },
      label: { show: true, formatter: m.name.slice(0, 10),
               fontSize: 9, color: '#ff7875' },
    }))
    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis' },
      legend: { data: SERIES_DEF.map((d) => d.name), top: 0 },
      grid: { left: 60, right: 60, top: 30, bottom: 40 },
      xAxis: { type: 'category', data: s.t,
               name: '月', boundaryGap: false },
      yAxis: [
        { type: 'value', name: '水平值', scale: true },
        { type: 'value', name: '比率', scale: true,
          axisLabel: {
            formatter: (v: number) => (v * 100).toFixed(0) + '%' } },
      ],
      series: SERIES_DEF.map((d) => ({
        name: d.name,
        type: 'line',
        yAxisIndex: d.axis,
        showSymbol: false,
        itemStyle: { color: d.color },
        lineStyle: { color: d.color, width: 1.6 },
        data: s[d.key].map((v) => (v === null || Number.isNaN(v)
          ? null : v)),
      })),
      ...(markers.length > 0 ? { markLine: {
        symbol: 'none', silent: true, data: markers } } : {}),
    }, { notMerge: false })
  }

  onMount(() => {
    chart = echarts.init(el)
    render()
    timer = setInterval(render, 500)   // 半秒聚合刷新, 避免逐帧重绘
    const ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el)
    return () => { clearInterval(timer); ro.disconnect() }
  })
  onDestroy(() => chart?.dispose())
</script>

<div bind:this={el} style="width:100%;height:100%;min-height:420px"></div>
