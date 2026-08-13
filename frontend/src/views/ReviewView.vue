<template>
  <main class="review-page">
    <div class="review-head">
      <div>
        <h1>配额申请审批 <span class="pill">仅管理员</span></h1>
        <p>审批用户提交的额外知识库配额申请</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="requests.length === 0" class="table-empty">暂无待审批申请</div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th>申请人ID</th>
            <th>申请数量</th>
            <th>理由</th>
            <th>提交时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in requests" :key="r.id">
            <td><strong>#{{ r.user_id }}</strong></td>
            <td>+{{ r.amount }}</td>
            <td>{{ r.reason || '—' }}</td>
            <td class="muted-cell">{{ r.created_at || '—' }}</td>
            <td class="col-op">
              <button class="op-link" type="button" :disabled="busyId === r.id" @click="onApprove(r)">
                <i class="fa-solid fa-check"></i> 通过
              </button>
              <button class="op-link danger" type="button" :disabled="busyId === r.id" @click="onReject(r)">
                <i class="fa-solid fa-xmark"></i> 驳回
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error review-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice review-msg">{{ notice }}</p>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  pendingQuotaRequests,
  approveQuotaRequest,
  rejectQuotaRequest,
  extractErrorMessage,
  type QuotaRequest,
} from '../api/client'

const requests = ref<QuotaRequest[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busyId = ref<number | null>(null)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    requests.value = await pendingQuotaRequests()
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function onApprove(r: QuotaRequest) {
  busyId.value = r.id
  error.value = ''
  try {
    await approveQuotaRequest(r.id)
    notice.value = `已通过申请 #${r.id}（用户 #${r.user_id} +${r.amount}）`
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    busyId.value = null
  }
}

async function onReject(r: QuotaRequest) {
  busyId.value = r.id
  error.value = ''
  try {
    await rejectQuotaRequest(r.id)
    notice.value = `已驳回申请 #${r.id}`
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    busyId.value = null
  }
}

onMounted(refresh)
</script>

<style scoped>
.review-page { padding: 26px 30px; overflow-y: auto; }
.review-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.review-head h1 { margin: 0 0 4px; font-size: 22px; }
.review-head p { margin: 0; color: var(--muted); font-size: 13px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.review-msg { margin-top: 14px; }
</style>
