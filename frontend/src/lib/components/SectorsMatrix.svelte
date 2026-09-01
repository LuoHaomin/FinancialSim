<script lang="ts">
  // 部门资产负债表矩阵 (Godley 存量-流量视图): 7 部门 × 资产/负债/净值
  import { api, type SectorsMatrix as Matrix } from '../api'
  import { simId, meta } from '../stores/connection'

  let data = $state<Matrix | null>(null)
  let error = $state('')
  let auto = $state(true)

  const fmt = (v: number | null | undefined) =>
    v === null || v === undefined ? '—'
      : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + 'M'
      : Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k'
      : v.toFixed(1)

  async function refresh() {
    const id = $simId
    if (!id) return
    try { data = await api.sectors(id); error = '' }
    catch (e) { error = String(e) }
  }

  $effect(() => {
    const id = $simId
    if (!id) return
    refresh()
    if (!auto) return
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  })

  // 所有出现过的科目名 (跨部门求并集)
  const assetKeys = $derived(Object.keys(
    Object.assign({}, ...Object.values(data?.sectors ?? {})
      .map((s) => s.assets))))
  const liabKeys = $derived(Object.keys(
    Object.assign({}, ...Object.values(data?.sectors ?? {})
      .map((s) => s.liabilities))))
  const sectorNames = $derived(Object.keys(data?.sectors ?? {}))

  const cell = (name: string, kind: 'assets' | 'liabilities', key: string) =>
    data?.sectors[name]?.[kind]?.[key]
</script>

<div class="card">
  <div class="row">
    <h3>部门资产负债表矩阵 · t = {data?.t ?? $meta?.t ?? '—'}</h3>
    <span class="sep"></span>
    <button onclick={refresh}>刷新</button>
    <label class="hint"><input type="checkbox" bind:checked={auto} /> 自动 (5s)</label>
    <span class="hint">任一部门 A = L + NW 破坏时行首亮红 — 这就是 SFC 校验的可视化</span>
  </div>
  {#if error}<p class="err">{error}</p>{/if}
  {#if data}
    <div style="overflow-x:auto">
      <table class="data">
        <thead>
          <tr>
            <th>部门</th><th>资产端</th>
            {#each sectorNames as n}<th class="num">{data.sectors[n].label}</th>{/each}
            <th>合计</th>
          </tr>
        </thead>
        <tbody>
          {#each assetKeys as k}
            <tr>
              <td></td><td class="label">{k}</td>
              {#each sectorNames as n}
                <td class="num">{fmt(cell(n, 'assets', k))}</td>
              {/each}
              <td class="num total">{fmt(sectorNames.reduce(
                (a, n) => a + (cell(n, 'assets', k) ?? 0), 0))}</td>
            </tr>
          {/each}
          <tr class="subtotal">
            <td></td><td class="label">资产合计</td>
            {#each sectorNames as n}
              <td class="num">{fmt(data.sectors[n].total_assets)}</td>
            {/each}
            <td class="num"></td>
          </tr>
          {#each liabKeys as k}
            <tr>
              <td></td><td class="label">{k}</td>
              {#each sectorNames as n}
                <td class="num">{fmt(cell(n, 'liabilities', k))}</td>
              {/each}
              <td class="num total">{fmt(sectorNames.reduce(
                (a, n) => a + (cell(n, 'liabilities', k) ?? 0), 0))}</td>
            </tr>
          {/each}
          <tr class="subtotal">
            <td></td><td class="label">负债合计</td>
            {#each sectorNames as n}
              <td class="num">{fmt(data.sectors[n].total_liabilities)}</td>
            {/each}
            <td class="num"></td>
          </tr>
          <tr class="subtotal">
            <td>净值</td><td class="label">净财富 / 资本</td>
            {#each sectorNames as n}
              <td class="num {data.sectors[n].balanced ? '' : 'bad'}">
                {fmt(data.sectors[n].net_worth)}</td>
            {/each}
            <td class="num"></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="hint" style="margin-top:8px">
      {#each sectorNames as n}
        {#if !data.sectors[n].balanced}
          <span class="badge bad">{data.sectors[n].label} A≠L+NW</span>
        {/if}
      {/each}
      全部门 A = L + NW 一致 = 资金没有凭空出现或消失
    </p>
  {:else}
    <p class="hint">加载中…</p>
  {/if}
</div>

<style>
  td.num { text-align: right; }
  td.label { color: var(--text-dim); font-size: .82rem; }
  td.total { color: var(--text-faint); }
  tr.subtotal td { border-top: 1px solid var(--border); font-weight: 600; }
  td.bad { color: var(--bad); font-weight: 700; }
</style>
