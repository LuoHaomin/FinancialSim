<script lang="ts">
  // 应用外壳: 控制条 + 视图路由 (宏观/部门矩阵/家庭/下钻/网络) + 干预 + 审计
  import MacroPanel from './lib/components/MacroPanel.svelte'
  import AgentsView from './lib/AgentsView.svelte'
  import SectorsMatrix from './lib/components/SectorsMatrix.svelte'
  import HouseholdsPanel from './lib/components/HouseholdsPanel.svelte'
  import NetworkView from './lib/components/NetworkView.svelte'
  import { api, type MetaInfo, type SimMeta, ApiError } from './lib/api'
  import {
    simId, meta, wsStatus, series, shocks,
    openStream, closeStream, resetSeries,
    setSpeed, pause, stepOnce, runTo, refreshMeta, refreshShocks,
  } from './lib/stores/connection'
  import { toasts, toast, dismissToast } from './lib/stores/toasts'

  type View = 'dashboard' | 'sectors' | 'households' | 'agents' | 'network'
  let view = $state<View>('dashboard')

  let scenario = $state('baseline')
  let error = $state('')
  let busy = $state(false)
  let speedSlider = $state(0)
  let runToT = $state(0)

  // 元数据 (场景/预设来自后端, 不再硬编码)
  let metaInfo = $state<MetaInfo | null>(null)
  $effect(() => { api.metaInfo().then((m) => metaInfo = m).catch(() => {}) })

  // 多实例管理
  let sims = $state<SimMeta[]>([])
  async function refreshSims() {
    try { sims = await api.listSims() } catch { /* 服务重启 */ }
  }
  $effect(() => {
    if ($simId) refreshSims()
    const timer = setInterval(refreshSims, 5000)
    return () => clearInterval(timer)
  })

  async function createSim() {
    error = ''
    busy = true
    try {
      // 新建前关闭旧实例引用 (由服务端 TTL 兜底回收; 列表可手动切换)
      const id = await api.createSim(scenario)
      await openStream(id)
      speedSlider = 0
      toast(`仿真已创建 (${scenario})`, 'ok')
    } catch (e) {
      error = e instanceof ApiError ? e.message : String(e)
      toast('创建失败: ' + error, 'err')
    } finally { busy = false }
  }

  async function switchSim(id: string) {
    await openStream(id)
    speedSlider = $meta?.speed ?? 0
    toast(`已切换到 ${id.slice(0, 8)}`, 'info')
  }

  async function closeCurrent() {
    const id = $simId
    if (!id) return
    try { await api.closeSim(id) } catch { /* 已被服务端清理 */ }
    closeStream()
    simId.set(null)
    meta.set(null)
    resetSeries()
    refreshSims()
  }

  async function applySpeed(v: number) {
    speedSlider = v
    await setSpeed(v)
  }

  const resume = () => applySpeed(Math.max(4, speedSlider || 4))

  // SFC 警报详情
  let sfcOpen = $state(false)
  let sfcDetail = $state<{ t: number; errors: string[] }[]>([])
  async function toggleSfc() {
    sfcOpen = !sfcOpen
    if (sfcOpen && $simId) {
      try { sfcDetail = (await api.sfc($simId)).detail } catch { /* 忽略 */ }
    }
  }

  // 干预面板
  let shockPreset = $state('')
  let customMode = $state(false)
  let customChannel = $state('policy_rate')
  let customMagnitude = $state(0.01)
  let shockOffset = $state(0)
  let shockDuration = $state(6)

  async function injectShock() {
    const id = $simId
    if (!id) return
    try {
      await api.intervention(id, customMode ? {
        channel: customChannel, magnitude: customMagnitude,
        trigger_offset: Math.max(0, shockOffset),
        duration: Math.max(1, shockDuration),
      } : {
        preset: shockPreset || metaInfo?.shock_presets[0]?.id || '',
        trigger_offset: Math.max(0, shockOffset),
        duration: Math.max(1, shockDuration),
      })
      toast('冲击已注入 (经 ShockEvent 网关)', 'ok')
      await refreshShocks(id)
    } catch (e) {
      toast('注入失败: ' + (e instanceof ApiError ? e.message : String(e)),
        'err')
    }
  }

  const presetLabel = (pid: string) =>
    metaInfo?.shock_presets.find((p) => p.id === pid)?.description ?? pid

  const wsBadge = $derived(
    $wsStatus === 'open' ? { cls: 'good', text: 'WS 实时' }
      : $wsStatus === 'connecting' ? { cls: 'warn', text: 'WS 连接中' }
      : $wsStatus === 'closed' ? { cls: 'bad', text: 'WS 断开 · REST 兜底' }
      : { cls: 'neutral', text: 'WS 未启动' })
</script>

<main>
  <header class="row">
    <h1>FinancialSim <small>ABM 宏观经济仿真器</small></h1>
    <span class="sep"></span>
    {#if $meta}
      <span class="hint">{$meta.name} · 第 <b>{$meta.t}</b> 月 ·
        {$meta.paused ? '已暂停' : $meta.speed + ' tick/s'}</span>
      <span class="badge {wsBadge.cls}">{wsBadge.text}</span>
      {#if $meta.sfc_violations > 0}
        <span class="badge bad">SFC 违反 {$meta.sfc_violations}</span>
      {:else}
        <span class="badge good">SFC 一致 ✓</span>
      {/if}
    {:else}
      <span class="hint">选择场景并新建仿真开始</span>
    {/if}
  </header>

  {#if $meta && $meta.sfc_violations > 0}
    <div class="sfc-alarm" role="button" tabindex="0"
         onclick={toggleSfc} onkeydown={(e) => e.key === 'Enter' && toggleSfc()}>
      ⚠ 检测到 {$meta.sfc_violations} 条存量-流量一致性违反 —
      点击{sfcOpen ? '收起' : '展开'}详情
      {#if sfcOpen}
        <pre>{#each sfcDetail as d}{`t=${d.t}: ${d.errors.join('; ')}\n`}{/each}</pre>
      {/if}
    </div>
  {/if}

  <section class="bar card">
    <select bind:value={scenario}>
      {#each metaInfo?.scenarios ?? [] as s}
        <option value={s.id} title={s.description}>{s.name || s.id}</option>
      {/each}
    </select>
    <button class="primary" onclick={createSim} disabled={busy}>新建仿真</button>

    {#if sims.length > 1}
      <select onchange={(e) => switchSim(e.currentTarget.value)} value={$simId ?? ''}>
        {#each sims as s}
          <option value={s.sim_id}>{s.sim_id.slice(0, 8)} ({s.name}, t={s.t})</option>
        {/each}
      </select>
    {/if}

    {#if $simId}
      <span class="sep"></span>
      {#each [['dashboard', '宏观'], ['sectors', '部门矩阵'], ['households', '家庭'],
              ['agents', '下钻'], ['network', '网络']] as [v, label]}
        <button class:tab-active={view === v} onclick={() => (view = v as View)}>
          {label}</button>
      {/each}
      <span class="sep"></span>
      <button onclick={resume} disabled={!$simId}>▶</button>
      <button onclick={pause} disabled={!$simId}>⏸</button>
      <button onclick={() => stepOnce(1)} disabled={!$simId}>+1</button>
      <label class="hint">速度
        <input type="range" min="0" max="30" step="1"
               bind:value={speedSlider}
               onchange={() => applySpeed(speedSlider)} />
        {speedSlider} t/s</label>
      <label class="hint">跳至
        <input type="number" bind:value={runToT} min="0"
               style="width:5em" /></label>
      <button onclick={() => runTo(Math.max(0, runToT))} disabled={!$simId}>▶|</button>
      <span class="sep"></span>
      <button class="danger" onclick={closeCurrent} disabled={!$simId}>✕ 关闭</button>
    {/if}
  </section>

  {#if error}<p class="err">{error}</p>{/if}

  {#if !$simId}
    <section class="card" style="text-align:center;padding:48px">
      <p class="hint">FinancialSim — 教学型宏观仿真器。<br />
        每一笔资金流在两个部门镜像记账 (SFC 校验)，
        干预经由 ShockEvent 网关注入并全量留痕。</p>
    </section>
  {:else if view === 'dashboard'}
    <MacroPanel />
  {:else if view === 'sectors'}
    <SectorsMatrix />
  {:else if view === 'households'}
    <HouseholdsPanel />
  {:else if view === 'agents'}
    <AgentsView />
  {:else}
    <NetworkView />
  {/if}

  {#if $simId}
    <section class="panel card" style="margin-top:12px">
      <h3>政策 / 冲击干预</h3>
      <div class="row">
        {#if !customMode}
          <select bind:value={shockPreset}>
            {#each metaInfo?.shock_presets ?? [] as p}
              <option value={p.id}>{p.description || p.id}</option>
            {/each}
          </select>
        {:else}
          <select bind:value={customChannel}>
            {#each metaInfo?.custom_channels ?? [] as c}<option value={c}>{c}</option>{/each}
          </select>
          <label class="hint">强度
            <input type="number" bind:value={customMagnitude} step="0.005"
                   style="width:6em" /></label>
        {/if}
        <label class="hint"><input type="checkbox" bind:checked={customMode} /> 自定义通道</label>
        <label class="hint">偏移 <input type="number" bind:value={shockOffset}
                 min="0" style="width:5em" /> 月</label>
        <label class="hint">持续 <input type="number" bind:value={shockDuration}
                 min="1" style="width:4em" /> 月</label>
        <button class="primary" onclick={injectShock} disabled={!$simId}>注入冲击</button>
      </div>
      {#if !customMode && shockPreset}
        <p class="hint">{presetLabel(shockPreset)} ·
          {metaInfo?.shock_presets.find((p) => p.id === shockPreset)?.channel}</p>
      {/if}
    </section>

    <section class="panel card" style="margin-top:12px">
      <h3>冲击日志 ({$shocks.length})</h3>
      {#if $shocks.length === 0}
        <p class="hint">尚无冲击 — 每一次干预都会记录在此并可回放.</p>
      {:else}
        <table class="data">
          <thead><tr><th>t</th><th>名称</th><th>通道</th><th>强度</th></tr></thead>
          <tbody>
            {#each $shocks.slice().reverse() as m}
              <tr><td>{m.t}</td><td>{m.name}</td><td>{m.channel}</td>
                <td>{m.magnitude?.toFixed(4) ?? '—'}</td></tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}
</main>

<div class="toast-box">
  {#each $toasts as t (t.id)}
    <div class="toast {t.kind}" role="button" tabindex="-1"
         onclick={() => dismissToast(t.id)}>{t.text}</div>
  {/each}
</div>

<style>
  main { max-width: 1280px; margin: 0 auto; padding: 14px; }
  .bar { margin: 10px 0; }
  .panel h3 { margin-bottom: 6px; }
</style>
