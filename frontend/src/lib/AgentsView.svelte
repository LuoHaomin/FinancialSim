<script lang="ts">
  // L2 部门列表 + L3 单主体资产负债表下钻 (点击行展开详情)
  import { api, type FirmRow, type BankRow, type AssetLiabilityView } from './api'
  import { simId } from './stores'

  // ⚠️ 组件内有 runes 用法($derived/$effect)即进入 runes 模式:
  // 所有响应式本地状态必须显式 $state
  let tab = $state<'firms' | 'banks'>('firms')
  let firms = $state<FirmRow[]>([])
  let banks = $state<BankRow[]>([])
  let detail = $state<AssetLiabilityView | null>(null)
  let error = $state('')
  const id = $derived($simId)

  // 进入视图时自动拉一次
  $effect(() => {
    if ($simId) refresh()
  })

  async function refresh() {
    if (!id) return
    error = ''
    try {
      if (tab === 'firms') firms = await api.agentsTable(id, 'firms')
      else banks = await api.agentsTable(id, 'banks')
    } catch (e) { error = String(e) }
  }

  async function openDetail(aid: string) {
    if (!id) return
    try {
      detail = await api.agentDetail(id, tab, aid)
    } catch (e) {
      detail = null; error = String(e)
    }
  }


  const fmt = (v: number | null | undefined) =>
    v === null || v === undefined ? '—'
      : Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k'
      : v.toFixed(2)
</script>

<section class="panel">
  <div class="row">
    <button class:active={tab === 'firms'}
            onclick={() => { tab = 'firms'; refresh() }}>企业</button>
    <button class:active={tab === 'banks'}
            onclick={() => { tab = 'banks'; refresh() }}>银行</button>
    <button onclick={refresh}>刷新</button>
    <span class="hint">点击行查看资产负债表</span>
  </div>

  {#if error}<p class="err">{error}</p>{/if}

  {#if tab === 'firms'}
    <table>
      <thead><tr><th>企业</th><th>部门</th><th>员工</th><th>价格</th>
        <th>存款</th><th>债务</th><th>上月销售</th><th>状态</th></tr></thead>
      <tbody>
        {#each firms as f}
          <tr class:sel={detail?.id === f.id}
              onclick={() => openDetail(f.id)}>
            <td>{f.id}</td><td>{f.sector}</td><td>{f.employees}</td>
            <td>{fmt(f.price)}</td><td>{fmt(f.deposits)}</td>
            <td>{fmt(f.debt)}</td><td>{fmt(f.last_sales)}</td>
            <td>{f.is_bankrupt ? '💀 破产' : '运营'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <table>
      <thead><tr><th>银行</th><th>资本</th><th>CAR</th><th>准备金</th>
        <th>企业贷款</th><th>家庭贷款</th><th>状态</th></tr></thead>
      <tbody>
        {#each banks as b}
          <tr class:sel={detail?.id === b.id}
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
  .panel { margin-top: 14px; }
  .row { display: flex; gap: 8px; align-items: center; }
  button { padding: 5px 12px; cursor: pointer; }
  .active { background: #d8e7ff; }
  table { width: 100%; border-collapse: collapse; font-size: .92em;
          margin-top: 6px; }
  th, td { text-align: left; padding: 4px 10px;
           border-bottom: 1px solid #f0f0f0; }
  th { color: #666; font-weight: 500; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #fafafa; }
  tr.sel { background: #eef5ff; }
  .hint { color: #999; font-size: .9em; }
  .err { color: #c0392b; white-space: pre-wrap; }
  .detail { border: 1px solid #eee; padding: 10px 14px; margin-top: 12px; }
  .bs { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
  ul { list-style: none; padding-left: 0; margin: 4px 0; }
  li { padding: 2px 0; border-bottom: 1px dotted #f5f5f5;
       font-variant-numeric: tabular-nums; }
  .cap { color: #3aa657; font-weight: 600; }
</style>
