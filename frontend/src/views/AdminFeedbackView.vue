<template>
  <main class="admin-feedback-page">
    <div class="admin-feedback-head">
      <div>
        <h1>反馈处理 <span class="pill">仅管理员</span></h1>
        <p>查看用户问题反馈，回复解决方法并流转处理状态</p>
      </div>
      <div class="head-actions">
        <select v-model="statusFilter" class="select" @change="refresh">
          <option value="all">全部状态</option>
          <option value="pending">待处理</option>
          <option value="processing">处理中</option>
          <option value="resolved">已回复</option>
          <option value="closed">已关闭</option>
        </select>
        <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
          <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
        </button>
      </div>
    </div>

    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="tickets.length === 0" class="table-empty">暂无反馈</div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th>反馈人</th>
            <th>标题</th>
            <th>状态</th>
            <th>问题描述</th>
            <th>截图</th>
            <th>更新时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tickets" :key="t.id">
            <td><strong>#{{ t.user_id }}</strong></td>
            <td><strong>{{ t.title }}</strong><small>#{{ t.id }}</small></td>
            <td><span :class="['status-badge', t.status]">{{ statusLabel(t.status) }}</span></td>
            <td class="feedback-text">{{ t.content || '—' }}</td>
            <td>
              <span v-if="t.attachments?.length" class="attach-count">
                <i class="fa-regular fa-image"></i>{{ t.attachments.length }} 张
              </span>
              <span v-else class="muted-cell">—</span>
            </td>
            <td class="muted-cell">{{ t.updated_at || t.created_at || '—' }}</td>
            <td class="col-op">
              <button class="op-link" type="button" @click="openHandle(t)">
                <i class="fa-solid fa-pen-to-square"></i> 处理
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error admin-feedback-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice admin-feedback-msg">{{ notice }}</p>

    <div v-if="handling" class="modal-mask" @click.self="handling = null">
      <div class="modal wide">
        <div class="modal-head">
          <h3>处理反馈 · {{ handling.title }}</h3>
          <button class="modal-close" type="button" @click="handling = null">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="detail-body">
          <div class="feedback-detail">
            <b>用户 #{{ handling.user_id }} 的问题描述</b>
            <p>{{ handling.content || '—' }}</p>
          </div>
          <div v-if="handling.attachments?.length" class="form-row">
            <label class="form-label">用户截图</label>
            <div class="attachment-list">
              <button
                v-for="a in handling.attachments"
                :key="a.id"
                class="attachment-link"
                type="button"
                @click="openAttachment(handling, a.id)"
              >
                <i class="fa-regular fa-image"></i>{{ a.filename }} · {{ formatSize(a.size) }}
              </button>
            </div>
          </div>
          <div class="form-row">
            <label class="form-label req">处理状态</label>
            <select v-model="handleForm.status" class="select full">
              <option value="processing">处理中</option>
              <option value="resolved">已解决/已回复</option>
              <option value="closed">直接关闭</option>
            </select>
          </div>
          <div class="form-row">
            <label class="form-label" :class="{ req: handleForm.status === 'resolved' }">处理回复</label>
            <textarea
              v-model="handleForm.reply"
              class="textarea"
              rows="6"
              maxlength="4000"
              placeholder="写给用户看的处理说明、解决方法或后续建议"
            ></textarea>
          </div>
          <p v-if="handleErr" class="msg error">{{ handleErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="handling = null">取消</button>
          <button class="primary" type="button" :disabled="saving" @click="onSave">
            {{ saving ? '保存中…' : '保存处理结果' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  extractErrorMessage,
  listAdminFeedback,
  openFeedbackAttachment,
  updateAdminFeedback,
  type FeedbackStatus,
  type FeedbackTicket,
} from '../api/client'

const tickets = ref<FeedbackTicket[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const statusFilter = ref<FeedbackStatus | 'all'>('all')
const handling = ref<FeedbackTicket | null>(null)
const saving = ref(false)
const handleErr = ref('')
const handleForm = reactive<{ status: Exclude<FeedbackStatus, 'pending'>; reply: string }>({
  status: 'processing',
  reply: '',
})

function statusLabel(status: FeedbackStatus): string {
  return {
    pending: '待处理',
    processing: '处理中',
    resolved: '已回复',
    closed: '已关闭',
  }[status]
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${Math.round((size / 1024 / 1024) * 10) / 10} MB`
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    tickets.value = await listAdminFeedback(statusFilter.value)
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function openHandle(ticket: FeedbackTicket) {
  handling.value = ticket
  handleForm.status = ticket.status === 'pending' ? 'processing' : ticket.status
  handleForm.reply = ticket.admin_reply || ''
  handleErr.value = ''
}

async function openAttachment(ticket: FeedbackTicket, attachmentId: number) {
  handleErr.value = ''
  try {
    const url = await openFeedbackAttachment(ticket.id, attachmentId)
    window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    handleErr.value = extractErrorMessage(e)
  }
}

async function onSave() {
  if (!handling.value || saving.value) return
  if (handleForm.status === 'resolved' && !handleForm.reply.trim()) {
    handleErr.value = '标记已解决时必须填写处理回复'
    return
  }
  saving.value = true
  handleErr.value = ''
  try {
    await updateAdminFeedback(handling.value.id, handleForm.status, handleForm.reply.trim())
    notice.value = `已更新反馈 #${handling.value.id}`
    handling.value = null
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    handleErr.value = extractErrorMessage(e)
  } finally {
    saving.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.admin-feedback-page { padding: 26px 30px; overflow-y: auto; }
.admin-feedback-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.admin-feedback-head h1 { margin: 0 0 4px; font-size: 22px; }
.admin-feedback-head p { margin: 0; color: var(--muted); font-size: 13px; }
.head-actions { display: flex; gap: 10px; align-items: center; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.admin-feedback-msg { margin-top: 14px; }
.feedback-text { max-width: 300px; white-space: pre-wrap; line-height: 1.6; color: #3a4147; }
td strong { display: block; margin-bottom: 4px; }
td small { color: var(--muted); font-size: 12px; }
.modal.wide { width: 640px; max-width: 92vw; }
.feedback-detail { background: #f7f9fb; border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; }
.feedback-detail b { display: block; margin-bottom: 8px; color: var(--blue); }
.feedback-detail p { margin: 0; white-space: pre-wrap; line-height: 1.7; color: #3a4147; }
.attach-count { display: inline-flex; align-items: center; gap: 6px; color: var(--blue); font-size: 13px; }
.attachment-list { display: flex; flex-direction: column; gap: 8px; }
.attachment-link { text-align: left; color: var(--blue); font-size: 13px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; }
.attachment-link i { margin-right: 6px; }
.attachment-link:hover { background: #f2f6fb; }
</style>
