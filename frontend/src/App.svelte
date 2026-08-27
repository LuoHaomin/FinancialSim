<script lang="ts">
  // L1 宏观看板 (实验模式): 加载场景 → 跑 → 曲线 → 干预 → 审计闭环
  import MacroChart from './lib/MacroChart.svelte'
  import AgentsView from './lib/AgentsView.svelte'
  import { api, SCENARIOS, SHOCK_PRESETS } from './lib/api'
  import {
    simId, meta, paused, series, shocks,
    openStream, refreshMeta, refreshShocks,
  } from './lib/stores'

  let scenario = 'baseline'
  let error = ''
  let busy = false
  let view: 'dashboard' | 'agents' = 'dashboard'

  let shockPreset = SHOCK_PRESETS[0].id
  let shockOffset = 0
  let shockDuration = 6
  let shockMsg = ''

  async function createSim() {
    error = ''
    busy = true
    try {
      const id = await api.createSim(scenario)
      await openStream(id)
      pollMeta()
    } catch (e) {
      error = String(e)
    } finally { busy = false }
  }

  let pollTimer: ReturnType<typeof setInterval> | null = null
  function pollMeta() {
    if (pollTimer) clearInterval(pollTimer)
    pollTimer = setInterval(async () => {
      const id = $simId
      if (!id) return
      try { await refreshMeta(id) } catch { /* 服务重启等 */ }
    }, 1000)
  }

  async function cmd(c: { speed?: number; step?: number }) {
    const id = $simId
    if (!id) return
    await api.command(id, c)
    await refreshMeta(id)
  }
  const resume = () => cmd({ speed: 4 })
  const pause = () => cmd({ speed: 0 })
  const stepOnce = () => cmd({ step: 1 })

  async function injectShock() {
    const id = $simId
    if (!id) return
    shockMsg = ''
    try {
      await api.intervention(id, {
        preset: shockPreset,
        trigger_offset: Math.max(0, shockOffset),
        duration: Math.max(1, shockDuration),
      })
      shockMsg = '✓ 已注入'
      setTimeout(() => (shockMsg = ''), 2000)
      await refreshShocks(id)
    } catch (e) {
      shockMsg = '✗ ' + String(e).slice(0, 120)
    }
  }
</script>

<main>
  <header>
    <h1>FinancialSim <small>ABM 宏观经济仿真器</small></h1>
    {#if $meta}
    <div class="meta">
      场景: {$meta.name} · seed 固定 · 第 <b>{$meta.t}</b> 月 ·
      speed={$meta.speed}
      {#if $meta.sfc_violations > 0}
        <span class="alarm">⚠ SFC 违反 {$meta.sfc_violations}</span>
      {:else}
        <span class="ok">SFC 一致 ✓</span>
      {/if}
    </div>
    {/if}
  </header>

  <section class="bar">
    <select bind:value={scenario}>
      {#each SCENARIOS as s}
        <option value={s.id}>{s.label}</option>
      {/each}
    </select>
    <button onclick={createSim} disabled={busy}>新建仿真</button>
    <span class="sep"></span>
    {#if $simId}
    <button class:active={view === 'dashboard'}
            onclick={() => (view = 'dashboard')}>宏观</button>
    <button class:active={view === 'agents'}
            onclick={() => (view = 'agents')}>部门下钻</button>
    <span class="sep"></span>
    {/if}
    <button onclick={resume} disabled={!$simId}>▶ 继续</button>
    <button onclick={pause} disabled={!$simId}>⏸ 暂停</button>
    <button onclick={stepOnce} disabled={!$simId}>单步 +1</button>
  </section>

  {#if error}<p class="err">{error}</p>{/if}

  {#if view === 'dashboard'}
  <section class="chart">
    <MacroChart />
  </section>
  {:else}
  <AgentsView />
  {/if}

  <section class="panel" id="interventions">
    <h3>政策 / 冲击干预</h3>
    <div class="row">
      <select bind:value={shockPreset}>
        {#each SHOCK_PRESETS as p}
          <option value={p.id}>{p.label}</option>
        {/each}
      </select>
      <label>偏移 <input type="number" bind:value={shockOffset}
               min="0" style="width:5em" /> 月</label>
      <label>持续 <input type="number" bind:value={shockDuration}
               min="1" style="width:4em" /> 月</label>
      <button onclick={injectShock} disabled={!$simId}>注入冲击</button>
      <span class="hint">{shockMsg}</span>
    </div>
  </section>

  <section class="panel">
    <h3>冲击日志 ({$shocks.length})</h3>
    {#if $shocks.length === 0}
      <p class="hint">尚无冲击 — 每一次干预都会记录在此并可回放.</p>
    {:else}
      <table>
        <thead><tr><th>t</th><th>名称</th><th>通道</th></tr></thead>
        <tbody>
          {#each $shocks.slice().reverse() as m}
            <tr><td>{m.t}</td><td>{m.name}</td><td>{m.channel}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </section>
</main>

<style>
  main { max-width: 1100px; margin: 0 auto; padding: 12px;
         font-family: system-ui, sans-serif; }
  header h1 small { font-size: .55em; color: #888; font-weight: normal; }
  .meta { color: #666; font-size: .95em; }
  .ok { color: #3aa657; margin-left: .8em; }
  .alarm { background: #ffe4e4; color: #c0392b; padding: 2px 8px;
           border-radius: 4px; margin-left: .8em; }
  .bar, .row { display: flex; gap: 8px; align-items: center;
               flex-wrap: wrap; margin: 10px 0; }
  .sep { border-left: 1px solid #ddd; height: 22px; margin: 0 4px; }
  button, select { padding: 5px 12px; cursor: pointer; }
  .active { background: #d8e7ff; }
  button:disabled { cursor: not-allowed; opacity: .5; }
  .chart { border: 1px solid #eee; padding: 6px; margin: 12px 0; }
  .panel { margin-top: 14px; }
  .panel h3 { margin-bottom: 6px; font-size: 1em; }
  .err { color: #c0392b; white-space: pre-wrap; }
  .hint { color: #999; font-size: .9em; }
  table { width: 100%; border-collapse: collapse; font-size: .92em; }
  th, td { text-align: left; padding: 4px 10px;
           border-bottom: 1px solid #f0f0f0; }
  th { color: #666; font-weight: 500; }
</style>
