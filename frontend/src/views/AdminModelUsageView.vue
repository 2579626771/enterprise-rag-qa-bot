<template>
  <main class="model-usage-page">
    <div class="usage-head">
      <div>
        <h1>模型监控 <span class="pill">仅管理员</span></h1>
        <p>监控向量模型、问答大模型、研判、改写与重排的调用、token、延迟和异常</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <section class="usage-filters">
      <label>
        时间范围
        <select v-model.number="filters.days" class="select" @change="refresh">
          <option :value="1">最近 1 天</option>
          <option :value="7">最近 7 天</option>
          <option :value="30">最近 30 天</option>
        </select>
      </label>
      <label>
        用户
        <select v-model="selectedUser" class="select" @change="refresh">
          <option value="all">全部用户</option>
          <option v-for="u in users" :key="u.id" :value="String(u.id)">
            {{ u.display_name || u.username }} #{{ u.id }}
          </option>
        </select>
      </label>
      <label>
        模型类型
        <select v-model="filters.model_type" class="select" @change="refresh">
          <option value="all">全部类型</option>
          <option value="embedding">向量 embedding</option>
          <option value="chat">问答大模型</option>
          <option value="judge">答案研判</option>
          <option value="query_rewrite">查询改写</option>
          <option value="rerank">检索重排</option>
        </select>
      </label>
    </section>

    <p v-if="error" class="msg error">{{ error }}</p>

    <section class="kpi-grid">
      <article class="kpi-card">
        <span>总调用</span>
        <strong>{{ fmtNumber(overall.call_count) }}</strong>
        <small>成功 {{ fmtNumber(overall.success_count) }} / 失败 {{ fmtNumber(overall.failed_count) }}</small>
      </article>
      <article class="kpi-card">
        <span>成功率</span>
        <strong>{{ percent(overall.success_rate) }}</strong>
        <small>失败率 {{ percent(overall.error_rate) }}</small>
      </article>
      <article class="kpi-card">
        <span>总 Token</span>
        <strong>{{ fmtNumber(overall.total_tokens) }}</strong>
        <small>输入 {{ fmtNumber(overall.prompt_tokens) }} / 输出 {{ fmtNumber(overall.completion_tokens) }}</small>
      </article>
      <article class="kpi-card">
        <span>平均延迟</span>
        <strong>{{ fmtLatency(overall.avg_latency_ms) }}</strong>
        <small>P95 {{ fmtLatency(overall.p95_latency_ms) }} / 最大 {{ fmtLatency(overall.max_latency_ms) }}</small>
      </article>
    </section>

    <section class="alert-card">
      <div class="section-head">
        <h2>异常告警</h2>
        <span>{{ alerts.length }} 条</span>
      </div>
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="alerts.length === 0" class="table-empty ok">暂无异常告警</div>
      <div v-else class="alert-list">
        <article v-for="a in alerts" :key="`${a.type}-${a.model_type}-${a.user_id}`" :class="['alert-item', a.severity]">
          <strong>{{ a.title }}</strong>
          <p>{{ a.message }}</p>
          <small v-if="a.username">归属用户：{{ a.display_name || a.username }} #{{ a.user_id }}</small>
        </article>
      </div>
    </section>

    <div class="usage-grid">
      <section class="usage-card">
        <div class="section-head">
          <h2>按模型类型</h2>
        </div>
        <div v-if="loading" class="table-empty">加载中…</div>
        <table v-else class="doc-table compact-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>调用</th>
              <th>Token</th>
              <th>平均延迟</th>
              <th>失败率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in summary?.by_model_type || []" :key="m.model_type">
              <td><strong>{{ modelLabel(m.model_type) }}</strong></td>
              <td>{{ fmtNumber(m.call_count) }}</td>
              <td>{{ fmtNumber(m.total_tokens) }}</td>
              <td>{{ fmtLatency(m.avg_latency_ms) }}</td>
              <td><span :class="['status-badge', m.failed_count ? 'pending' : 'resolved']">{{ percent(m.error_rate) }}</span></td>
            </tr>
            <tr v-if="!loading && (summary?.by_model_type.length || 0) === 0"><td colspan="5" class="table-empty">暂无数据</td></tr>
          </tbody>
        </table>
      </section>

      <section class="usage-card">
        <div class="section-head">
          <h2>按用户归因</h2>
        </div>
        <div v-if="loading" class="table-empty">加载中…</div>
        <table v-else class="doc-table compact-table">
          <thead>
            <tr>
              <th>用户</th>
              <th>调用</th>
              <th>Token</th>
              <th>平均延迟</th>
              <th>失败</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in summary?.by_user || []" :key="u.user_id ?? 'unknown'">
              <td><strong>{{ userLabel(u) }}</strong></td>
              <td>{{ fmtNumber(u.call_count) }}</td>
              <td>{{ fmtNumber(u.total_tokens) }}</td>
              <td>{{ fmtLatency(u.avg_latency_ms) }}</td>
              <td><span :class="['status-badge', u.failed_count ? 'pending' : 'resolved']">{{ fmtNumber(u.failed_count) }}</span></td>
            </tr>
            <tr v-if="!loading && (summary?.by_user.length || 0) === 0"><td colspan="5" class="table-empty">暂无数据</td></tr>
          </tbody>
        </table>
      </section>
    </div>

    <section class="usage-card records-card">
      <div class="section-head">
        <h2>最近调用明细</h2>
        <span>最多 100 条</span>
      </div>
      <div v-if="loading" class="table-empty">加载中…</div>
      <table v-else class="doc-table records-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>用户</th>
            <th>类型</th>
            <th>模型</th>
            <th>场景</th>
            <th>Token</th>
            <th>延迟</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in records" :key="r.id">
            <td class="muted-cell">{{ r.created_at || '—' }}</td>
            <td>{{ userLabel(r) }}</td>
            <td>{{ modelLabel(r.model_type) }}</td>
            <td><small>{{ r.provider }} / {{ r.model_name || '—' }}</small></td>
            <td>{{ operationLabel(r.operation) }}</td>
            <td>{{ fmtNumber(r.total_tokens) }}</td>
            <td>{{ fmtLatency(r.latency_ms) }}</td>
            <td>
              <span :class="['status-badge', r.success ? 'resolved' : 'pending']">{{ r.success ? '成功' : '失败' }}</span>
              <small v-if="!r.success" class="error-tip">{{ r.error_type || r.error_message }}</small>
            </td>
          </tr>
          <tr v-if="records.length === 0"><td colspan="8" class="table-empty">暂无调用记录</td></tr>
        </tbody>
      </table>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  extractErrorMessage,
  fetchModelUsageRecords,
  fetchModelUsageSummary,
  listUsers,
  type AuthUser,
  type ModelUsageByUser,
  type ModelUsageRecord,
  type ModelUsageSummary,
} from '../api/client'

const users = ref<AuthUser[]>([])
const summary = ref<ModelUsageSummary | null>(null)
const records = ref<ModelUsageRecord[]>([])
const loading = ref(false)
const error = ref('')
const selectedUser = ref('all')
const filters = reactive({ days: 7, model_type: 'all' })

const emptyMetric = {
  call_count: 0,
  success_count: 0,
  failed_count: 0,
  success_rate: 0,
  error_rate: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0,
  avg_latency_ms: 0,
  max_latency_ms: 0,
  p95_latency_ms: 0,
}
const overall = computed(() => summary.value?.overall || emptyMetric)
const alerts = computed(() => summary.value?.alerts || [])

function currentFilters() {
  return {
    days: filters.days,
    user_id: selectedUser.value === 'all' ? null : Number(selectedUser.value),
    model_type: filters.model_type,
    limit: 100,
  }
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const query = currentFilters()
    const [s, r] = await Promise.all([
      fetchModelUsageSummary(query),
      fetchModelUsageRecords(query),
    ])
    summary.value = s
    records.value = r
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function loadUsers() {
  try {
    users.value = await listUsers()
  } catch {
    users.value = []
  }
}

function fmtNumber(value: number | undefined | null): string {
  return Number(value || 0).toLocaleString('zh-CN')
}

function fmtLatency(value: number | undefined | null): string {
  const ms = Number(value || 0)
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function percent(value: number | undefined | null): string {
  return `${((Number(value || 0)) * 100).toFixed(1)}%`
}

function modelLabel(type: string): string {
  const map: Record<string, string> = {
    embedding: '向量模型',
    chat: '问答大模型',
    judge: '答案研判',
    query_rewrite: '查询改写',
    rerank: '检索重排',
  }
  return map[type] || type || '未知'
}

function operationLabel(value: string): string {
  const map: Record<string, string> = {
    rag_ask: '问答链路',
    answer: '生成回答',
    judge_answer: '研判作答',
    query_embedding: '查询向量化',
    document_embedding: '文档向量化',
    document_ingest: '文档入库',
    rechunk_docx: 'DOCX重切分',
    query_rewrite: '查询改写',
    rerank: '候选重排',
  }
  return map[value] || value || '—'
}

function userLabel(row: Pick<ModelUsageByUser | ModelUsageRecord, 'user_id' | 'username' | 'display_name'>): string {
  if (!row.user_id) return '未归因'
  return `${row.display_name || row.username || '用户'} #${row.user_id}`
}

onMounted(async () => {
  await loadUsers()
  await refresh()
})
</script>

<style scoped>
.model-usage-page { padding: 26px 30px; overflow-y: auto; }
.usage-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.usage-head h1 { margin: 0 0 4px; font-size: 22px; }
.usage-head p { margin: 0; color: var(--muted); font-size: 13px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.usage-filters { display: flex; flex-wrap: wrap; gap: 12px; padding: 14px; margin-bottom: 16px; background: #fff; border: 1px solid var(--line); border-radius: 12px; }
.usage-filters label { display: grid; gap: 6px; min-width: 160px; font-size: 12px; color: var(--muted); }
.kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.kpi-card, .usage-card, .alert-card { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
.kpi-card span { color: var(--muted); font-size: 13px; }
.kpi-card strong { display: block; margin: 8px 0 4px; font-size: 26px; color: #152536; }
.kpi-card small { color: var(--muted); }
.section-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.section-head h2 { margin: 0; font-size: 16px; }
.section-head span { color: var(--muted); font-size: 12px; }
.alert-card { margin-bottom: 16px; }
.alert-list { display: grid; gap: 10px; }
.alert-item { padding: 12px; border-radius: 10px; border: 1px solid #f3d08a; background: #fff8e5; }
.alert-item.error { border-color: #f5b5b5; background: #fff1f1; }
.alert-item strong { display: block; margin-bottom: 4px; }
.alert-item p { margin: 0 0 4px; color: #3a4147; }
.alert-item small { color: var(--muted); }
.table-empty.ok { color: #2b7a4b; }
.usage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }
.compact-table th, .compact-table td { white-space: nowrap; }
.records-card { overflow-x: auto; }
.records-table th, .records-table td { white-space: nowrap; vertical-align: top; }
.error-tip { display: block; color: #b45353; margin-top: 4px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 1100px) {
  .kpi-grid, .usage-grid { grid-template-columns: 1fr; }
}
</style>
