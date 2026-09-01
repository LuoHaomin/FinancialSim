<script lang="ts">
  // L4 网络图: 同业敞口 / 交叉持股 (d3-force 力导向, canvas 渲染)
  import { forceSimulation, forceLink, forceManyBody, forceCollide,
    forceCenter, type Simulation, type SimulationNodeDatum,
    type SimulationLinkDatum } from 'd3-force'
  import { api, type NetworkData } from '../api'
  import { simId } from '../stores/connection'

  interface Node extends SimulationNodeDatum {
    id: string
    capital?: number
    car?: number | null
    failed?: boolean
    core?: boolean
    is_firm?: boolean
    degree_value?: number
  }
  interface Link extends SimulationLinkDatum<Node> {
    value: number
  }

  let kind = $state<'interbank' | 'cross_holdings'>('interbank')
  let data = $state<NetworkData | null>(null)
  let error = $state('')
  let hover = $state<{ x: number; y: number; text: string } | null>(null)

  let canvas: HTMLCanvasElement
  let width = 800, height = 520
  let nodes = $state<Node[]>([])
  let links: Link[] = []

  const fmt = (v: number | undefined) =>
    v === undefined ? '—' : v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0)

  async function refresh() {
    const id = $simId
    if (!id) return
    try {
      data = await api.network(id, kind)
      error = ''
      build()
    } catch (e) { error = String(e) }
  }

  function build() {
    if (!data) return
    nodes = data.nodes.map((n) => ({ ...n }))
    const byId = new Map(nodes.map((n) => [n.id, n]))
    links = data.edges
      .filter((e) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({
        source: byId.get(e.source)!, target: byId.get(e.target)!,
        value: e.value,
      }))
    const maxV = Math.max(1, ...links.map((l) => l.value))
    const maxDeg = Math.max(1, ...nodes.map((n) =>
      n.capital ?? n.degree_value ?? 1))
    sim = forceSimulation(nodes)
      .force('link', forceLink<Node, Link>(links)
        .distance((l) => 60 + 120 * (1 - l.value / maxV))
        .strength(0.4))
      .force('charge', forceManyBody().strength(-240))
      .force('collide', forceCollide<Node>((n) =>
        6 + 22 * Math.sqrt((n.capital ?? n.degree_value ?? 1) / maxDeg)))
      .force('center', forceCenter(width / 2, height / 2))
      .alphaDecay(0.03)
      .on('tick', draw)
  }

  let sim: Simulation<Node, undefined> | null = null

  function draw() {
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)
    // 边
    const maxV = Math.max(1, ...links.map((l) => l.value))
    for (const l of links) {
      const s = l.source as Node, t = l.target as Node
      ctx.strokeStyle = 'rgba(139, 148, 158, 0.35)'
      ctx.lineWidth = 0.5 + 3.5 * (l.value / maxV)
      ctx.beginPath()
      ctx.moveTo(s.x ?? 0, s.y ?? 0)
      ctx.lineTo(t.x ?? 0, t.y ?? 0)
      ctx.stroke()
    }
    // 节点
    const maxDeg = Math.max(1, ...nodes.map((n) =>
      n.capital ?? n.degree_value ?? 1))
    for (const n of nodes) {
      const r = 6 + 22 * Math.sqrt((n.capital ?? n.degree_value ?? 1) / maxDeg)
      ctx.beginPath()
      ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, Math.PI * 2)
      ctx.fillStyle = n.failed ? '#f85149'
        : n.core ? '#58a6ff'
        : n.is_firm === false ? '#bc8cff'
        : '#39c5cf'
      ctx.fill()
      if (n.core) {
        ctx.strokeStyle = '#e6edf3'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }
      ctx.fillStyle = '#8b949e'
      ctx.font = '10px system-ui'
      ctx.textAlign = 'center'
      ctx.fillText(n.id, n.x ?? 0, (n.y ?? 0) + r + 11)
    }
  }

  function onMove(ev: MouseEvent) {
    const rect = canvas.getBoundingClientRect()
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top
    const hit = nodes.find((n) =>
      Math.hypot((n.x ?? 0) - mx, (n.y ?? 0) - my) < 16)
    hover = hit ? {
      x: ev.clientX - rect.left, y: ev.clientY - rect.top - 12,
      text: kind === 'interbank'
        ? `${hit.id}${hit.failed ? ' (失败)' : hit.core ? ' (核心)' : ''}`
          + ` · 资本 ${fmt(hit.capital)}`
          + ` · CAR ${hit.car === null || hit.car === undefined
            ? '—' : (hit.car * 100).toFixed(1) + '%'}`
        : `${hit.id} · 持股敞口 ${fmt(hit.degree_value)}`,
    } : null
  }

  $effect(() => {
    const id = $simId
    if (!id) return
    refresh()
    const timer = setInterval(refresh, 10000)
    return () => { clearInterval(timer); sim?.stop() }
  })

  function onResize() {
    if (!canvas.parentElement) return
    width = canvas.parentElement.clientWidth
    height = Math.max(420, Math.min(560, width * 0.55))
    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = width + 'px'
    canvas.style.height = height + 'px'
    draw()
  }

  $effect(() => {
    // canvas 挂载后初始化尺寸
    if (canvas && canvas.parentElement) onResize()
    const ro = new ResizeObserver(onResize)
    if (canvas.parentElement) ro.observe(canvas.parentElement)
    return () => ro.disconnect()
  })
</script>

<div class="card">
  <div class="row">
    <button class:tab-active={kind === 'interbank'}
            onclick={() => { kind = 'interbank'; refresh() }}>同业敞口网络</button>
    <button class:tab-active={kind === 'cross_holdings'}
            onclick={() => { kind = 'cross_holdings'; refresh() }}>交叉持股网络</button>
    <span class="sep"></span>
    <button onclick={refresh}>重排/刷新</button>
    <span class="hint">
      {kind === 'interbank'
        ? '节点大小 = 资本 · 边宽 = 敞口 · 蓝色描边 = 核心银行 · 红 = 已失败'
        : '节点大小 = 敞口规模 · 需开启 enable_cross_holdings'}
    </span>
  </div>
  {#if error}<p class="err">{error}</p>{/if}
  <div style="position:relative">
    <canvas bind:this={canvas} onmousemove={onMove}
            onmouseleave={() => (hover = null)}></canvas>
    {#if hover}
      <div class="tip" style="left:{hover.x}px;top:{hover.y}px">{hover.text}</div>
    {/if}
  </div>
  {#if data && data.nodes.length === 0}
    <p class="hint">该网络当前为空 (相应模块未开启或尚未建仓).</p>
  {/if}
</div>

<style>
  canvas { display: block; }
  .tip {
    position: absolute; pointer-events: none;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 6px; padding: 4px 8px; font-size: .78rem;
    transform: translate(-50%, -100%); white-space: nowrap;
  }
</style>
