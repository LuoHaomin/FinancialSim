<script lang="ts">
  // L2 部门列表 (企业/银行/政府/央行) + L3 单主体资产负债表下钻
  import { api, type FirmRow, type BankRow, type AssetLiabilityView,
    type GovernmentView, type CentralBankView } from './api'
  import { simId } from './stores/connection'

  type Tab = 'firms' | 'banks' | 'government' | 'central_bank'
  let tab = $state<Tab>('firms')
  let firms = $state<FirmRow[]>([])
  let banks = $state<BankRow[]>([])
  let gov = $state<GovernmentView | null>(null)
  let cb = $state<CentralBankView | null>(null)
  let detail = $state<AssetLiabilityView | null>(null)
  let error = $state('')
  let search = $state('')
  let hideBankrupt = $state(false)
  let sortKey = $state<string>('')
  let sortAsc = $state(true)
  let page = $state(0)
  const PAGE_SIZE = 20
  const id = $derived($simId)

  $effect(() => {
    if (id) refresh()
  })

  async function refresh() {
    if (!id) return
    error = ''
    try {
      if (tab === 'firms') firms = await api.agentsTable.firms(id)
      else if (tab === 'banks') banks = await api.agentsTable.banks(id)
      else if (tab === 'government') gov = await api.government(id)
      else cb = await api.centralBank(id)
    } catch (e) { error = String(e) }
  }

  async function openDetail(aid: string) {
    if (!id) return
    try { detail = await api.agentDetail(id, tab === 'banks' ? 'banks' : 'firms', aid) }
    catch (e) { detail = null; error = String(e) }
  }

  const fmt = (v: number | null | undefined) =>
    v === null || v === undefined ? '—'
      : Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k'
      : v.toFixed(2)

  // 企业: 搜索 + 破产筛选 + 排序 + 分页
  const filteredFirms = $derived.by(() => {
    let rows = firms.filter((f) =>
      !hideBankrupt || !f.is_bankrupt)
    const q = search.trim().toLowerCase()
    if (q) rows = rows.filter((f) =>
      f.id.toLowerCase().includes(q) || f.sector.toLowerCase().includes(q))
    if (sortKey) {
      const key = sortKey as keyof FirmRow
      rows = [...rows].sort((a, b) => {
        const va = a[key], vb = b[key]
        const c = typeof va === 'number' && typeof vb === 'number'
          ? va - vb : String(va).localeCompare(String(vb))
        return sortAsc ? c : -c
      })
    }
    return rows
  })
  const pagedFirms = $derived(
    filteredFirms.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE))
  const totalPages = $derived(
    Math.max(1, Math.ceil(filteredFirms.length / PAGE_SIZE)))

  function sortBy(k: string) {
    if (sortKey === k) sortAsc = !sortAsc
    else { sortKey = k; sortAsc = true }
  }
  const arrow = (k: string) => sortKey === k ? (sortAsc ? ' ↑' : ' ↓') : ''

  function switchTab(t: Tab) {
    tab = t; detail = null; page = 0; search = ''
    refresh()
  }
</script>

<section class="card">
  <div class="row">
    {#each [['firms', '企业'], ['banks', '银行'], ['government', '政府'], ['central_bank', '央行']] as [t, label]}
      <button class:tab-active={tab === t} onclick={() => switchTab(t as Tab)}>
        {label}</button>
    {/each}
    <span class="sep"></span>
    <button onclick={refresh}>刷新</button>
    {#if tab === 'firms'}
      <input type="text" placeholder="搜索 id / 部门…" bind:value={search}
             style="width:12em" />
      <label class="hint"><input type="checkbox"
              bind:checked={hideBankrupt} /> 隐藏破产</label>
    {/if}
    <span class="hint">点击行查看资产负债表</span>
  </div>

  {#if error}<p class="err">{error}</p>{/if}

  {#if tab === 'firms'}
    <table class="data">
      <thead><tr>
        <th class="sortable" onclick={() => sortBy('id')}>企业{arrow('id')}</th>
        <th class="sortable" onclick={() => sortBy('sector')}>部门{arrow('sector')}</th>
        <th class="sortable" onclick={() => sortBy('employees')}>员工{arrow('employees')}</th>
        <th class="sortable" onclick={() => sortBy('price')}>价格{arrow('price')}</th>
        <th class="sortable" onclick={() => sortBy('deposits')}>存款{arrow('deposits')}</th>
        <th class="sortable" onclick={() => sortBy('debt')}>债务{arrow('debt')}</th>
        <th class="sortable" onclick={() => sortBy('last_sales')}>上月销售{arrow('last_sales')}</th>
        <th>状态</th>
      </tr></thead>
      <tbody>
        {#each pagedFirms as f}
          <tr class="clickable" class:sel={detail?.id === f.id}
              onclick={() => openDetail(f.id)}>
            <td>{f.id}</td><td>{f.sector}</td><td>{f.employees}</td>
            <td>{fmt(f.price)}</td><td>{fmt(f.deposits)}</td>
            <td>{fmt(f.debt)}</td><td>{fmt(f.last_sales)}</td>
            <td>{f.is_bankrupt ? '💀 破产' : '运营'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="row" style="margin-top:8px">
      <button disabled={page === 0} onclick={() => (page -= 1)}>上一页</button>
      <span class="hint">第 {page + 1} / {totalPages} 页 ·
        {filteredFirms.length} 家 (筛选后)</span>
      <button disabled={page >= totalPages - 1}
              onclick={() => (page += 1)}>下一页</button>
    </div>
  {:else if tab === 'banks'}
    <table class="data">
      <thead><tr><th>银行</th><th>资本</th><th>CAR</th><th>准备金</th>
        <th>企业贷款</th><th>家庭贷款</th><th>状态</th></tr></thead>
      <tbody>
        {#each banks as b}
          <tr class="clickable" class:sel={detail?.id === b.id}
              onclick={() => openDetail(b.id)}>
            <td>{b.id}</td><td>{fmt(b.capital)}</td>
            <td>{b.car === null ? '—' : (b.car * 100).toFixed(1) + '%'}</td>
            <td>{fmt(b.reserves)}</td>
            <td>{fmt(b.loans_to_firms)}</td>
            <td>{fmt(b.loans_to_households)}</td>
            <td>{b.is_failed ? '❌ 失败' : '正常'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else if tab === 'government' && gov}
    <h4 style="margin:10px 0 6px">政府部门 · t = {gov.t}</h4>
    <div class="bs">
      <div><b>资产</b>
        <ul>{#each Object.entries(gov.assets) as [k, v]}<li>{k}: {fmt(v)}</li>{/each}</ul>
      </div>
      <div><b>负债</b>
        <ul>{#each Object.entries(gov.liabilities) as [k, v]}
          <li>{k}: {fmt(v)}</li>{/each}</ul>
        <li class="cap">净财富: {fmt(gov.net_worth)}</li>
      </div>
      <div><b>当月流量</b>
        <ul>{#each Object.entries(gov.flows) as [k, v]}<li>{k}: {fmt(v)}</li>{/each}</ul>
      </div>
      <div><b>参数</b>
        <ul>{#each Object.entries(gov.parameters) as [k, v]}
          <li>{k}: {v.toFixed(3)}</li>{/each}</ul>
      </div>
    </div>
  {:else if tab === 'central_bank' && cb}
    <h4 style="margin:10px 0 6px">中央银行 · t = {cb.t}</h4>
    <div class="bs">
      <div><b>资产</b>
        <ul>{#each Object.entries(cb.assets) as [k, v]}<li>{k}: {fmt(v)}</li>{/each}</ul>
      </div>
      <div><b>负债</b>
        <ul>{#each Object.entries(cb.liabilities) as [k, v]}
          <li>{k}: {fmt(v)}</li>{/each}</ul>
        <li class="cap">资本: {fmt(cb.capital)}</li>
      </div>
      <div><b>政策</b>
        <ul>{#each Object.entries(cb.policy) as [k, v]}
          <li>{k}: {(v * 100).toFixed(2)}%</li>{/each}</ul>
        <li class="cap">基础货币: {fmt(cb.monetary_base)}</li>
      </div>
    </div>
  {/if}

  {#if detail}
    <div class="detail">
      <h4>L3 资产负债表 · {detail.id}</h4>
      <div class="bs">
        <div>
          <b>资产</b>
          <ul>
            {#each Object.entries(detail.assets) as [k, v]}
              <li>{k}: {fmt(v as number)}</li>
            {/each}
          </ul>
        </div>
        <div>
          <b>负债{detail.capital !== undefined ? ' + 资本' : ''}</b>
          <ul>
            {#each Object.entries(detail.liabilities ?? {}) as [k, v]}
              <li>{k}: {fmt(v as number)}</li>
            {/each}
            {#if detail.capital !== undefined}
              <li class="cap">capital: {fmt(detail.capital)}</li>
            {/if}
          </ul>
        </div>
        <div>
          <b>净值/指标</b>
          <ul>
            {#if detail.net_worth !== undefined}
              <li>net_worth: {fmt(detail.net_worth)}</li>
            {/if}
            {#if detail.car !== null && detail.car !== undefined}
              <li>CAR: {(detail.car * 100).toFixed(2)}%</li>
            {/if}
            {#each Object.entries(detail.operational ?? {}) as [k, v]}
              <li>{k}: {String(v)}</li>
            {/each}
          </ul>
        </div>
      </div>
    </div>
  {/if}
</section>

<style>
  .bs { display: grid; grid-template-columns: repeat(auto-fit,
        minmax(200px, 1fr)); gap: 16px; }
  ul { list-style: none; padding-left: 0; margin: 4px 0; }
  li { padding: 2px 0; border-bottom: 1px dotted var(--border-soft);
       font-variant-numeric: tabular-nums; }
  .cap { color: var(--good); font-weight: 600; }
  .detail { border: 1px solid var(--border); border-radius: 8px;
            padding: 10px 14px; margin-top: 12px; }
</style>
