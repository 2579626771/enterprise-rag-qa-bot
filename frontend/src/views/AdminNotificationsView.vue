<template>
  <main class="admin-notifications-page">
    <div class="admin-notifications-head">
      <div>
        <h1>通知下发 <span class="pill">仅管理员</span></h1>
        <p>向全部用户或指定用户下发系统通知，并查看已读统计</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refreshHistory">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <div class="notice-grid">
      <section class="notice-card">
        <h2>新建通知</h2>
        <div class="form-row">
          <label class="form-label req">标题</label>
          <input v-model="form.title" class="text-input" maxlength="120" placeholder="如：系统维护通知" />
        </div>
        <div class="form-row">
          <label class="form-label">内容</label>
          <textarea v-model="form.content" class="textarea" rows="6" maxlength="4000" placeholder="填写需要用户查看的通知内容"></textarea>
        </div>
        <div class="form-row">
          <label class="form-label req">发送范围</label>
          <div class="radio-row">
            <label><input v-model="form.sendToAll" type="radio" :value="true" /> 全部用户</label>
            <label><input v-model="form.sendToAll" type="radio" :value="false" /> 指定用户</label>
          </div>
        </div>
        <div v-if="!form.sendToAll" class="form-row">
          <label class="form-label req">目标用户</label>
          <div class="target-toolbar">
            <input v-model="targetSearch" class="text-input" placeholder="搜索用户名 / 显示名 / 用户ID" />
            <select v-model="targetRoleFilter" class="select">
              <option value="all">全部角色</option>
              <option value="admin">管理员</option>
              <option value="user">普通用户</option>
            </select>
          </div>
          <div class="batch-row">
            <span>已选 {{ form.userIds.length }} 人，当前筛选 {{ filteredTargetUsers.length }} 人</span>
            <div>
              <button type="button" @click="selectFilteredUsers">全选筛选结果</button>
              <button type="button" @click="clearSelectedUsers">清空选择</button>
            </div>
          </div>
          <div class="user-picker">
            <label v-for="u in filteredTargetUsers" :key="u.id" class="user-check">
              <input v-model="form.userIds" type="checkbox" :value="u.id" />
              <span>{{ u.display_name || u.username }} <small>#{{ u.id }} · {{ u.role === 'admin' ? '管理员' : '用户' }}</small></span>
            </label>
            <div v-if="filteredTargetUsers.length === 0" class="picker-empty">没有匹配的用户</div>
          </div>
        </div>
        <p v-if="error" class="msg error">{{ error }}</p>
        <p v-if="notice" class="msg notice">{{ notice }}</p>
        <div class="form-actions">
          <button class="primary" type="button" :disabled="sending || !canSend" @click="onSend">
            {{ sending ? '发送中…' : '发送通知' }}
          </button>
        </div>
      </section>

      <section class="notice-card history-card">
        <h2>下发历史</h2>
        <div v-if="loading" class="table-empty">加载中…</div>
        <div v-else-if="history.length === 0" class="table-empty">暂无通知历史</div>
        <table v-else class="doc-table">
          <thead>
            <tr>
              <th>标题</th>
              <th>范围</th>
              <th>收件</th>
              <th>未读</th>
              <th>已读</th>
              <th>关闭</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="n in history" :key="n.id">
              <td><strong>{{ n.title }}</strong><small>{{ n.content || '—' }}</small></td>
              <td>{{ n.target_type === 'all' ? '全部' : '指定' }}</td>
              <td>{{ n.recipient_count }}</td>
              <td><span class="status-badge pending">{{ n.unread_count }}</span></td>
              <td><span class="status-badge resolved">{{ n.read_count }}</span></td>
              <td><span class="status-badge closed">{{ n.closed_count }}</span></td>
              <td class="muted-cell">{{ n.created_at || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  extractErrorMessage,
  listAdminNotifications,
  listUsers,
  sendAdminNotification,
  type AdminNotificationSummary,
  type AuthUser,
} from '../api/client'

const users = ref<AuthUser[]>([])
const history = ref<AdminNotificationSummary[]>([])
const loading = ref(false)
const sending = ref(false)
const error = ref('')
const notice = ref('')
const targetSearch = ref('')
const targetRoleFilter = ref<'all' | 'admin' | 'user'>('all')
const form = reactive({ title: '', content: '', sendToAll: true, userIds: [] as number[] })

const canSend = computed(() => form.title.trim() && (form.sendToAll || form.userIds.length > 0))
const filteredTargetUsers = computed(() => {
  const keyword = targetSearch.value.trim().toLowerCase()
  return users.value.filter((u) => {
    if (targetRoleFilter.value !== 'all' && u.role !== targetRoleFilter.value) return false
    if (!keyword) return true
    return [String(u.id), u.username, u.display_name || '']
      .some((value) => value.toLowerCase().includes(keyword))
  })
})

async function refreshHistory() {
  loading.value = true
  error.value = ''
  try {
    history.value = await listAdminNotifications()
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

function selectFilteredUsers() {
  const merged = new Set(form.userIds)
  filteredTargetUsers.value.forEach((u) => merged.add(u.id))
  form.userIds = Array.from(merged)
}

function clearSelectedUsers() {
  form.userIds = []
}

async function onSend() {
  if (sending.value || !canSend.value) return
  sending.value = true
  error.value = ''
  notice.value = ''
  try {
    await sendAdminNotification({
      title: form.title.trim(),
      content: form.content.trim(),
      send_to_all: form.sendToAll,
      user_ids: form.sendToAll ? [] : form.userIds,
    })
    form.title = ''
    form.content = ''
    form.sendToAll = true
    form.userIds = []
    notice.value = '通知已下发'
    await refreshHistory()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    sending.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadUsers(), refreshHistory()])
})
</script>

<style scoped>
.admin-notifications-page { padding: 26px 30px; overflow-y: auto; }
.admin-notifications-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.admin-notifications-head h1 { margin: 0 0 4px; font-size: 22px; }
.admin-notifications-head p { margin: 0; color: var(--muted); font-size: 13px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.notice-grid { display: grid; grid-template-columns: minmax(320px, 420px) minmax(0, 1fr); gap: 18px; align-items: start; }
.notice-card { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 18px; }
.notice-card h2 { margin: 0 0 16px; font-size: 16px; }
.radio-row { display: flex; gap: 18px; font-size: 14px; color: #3a4147; }
.radio-row label { display: inline-flex; align-items: center; gap: 6px; }
.target-toolbar { display: grid; grid-template-columns: 1fr 120px; gap: 8px; margin-bottom: 8px; }
.batch-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 12px; color: var(--muted); }
.batch-row div { display: flex; gap: 8px; }
.batch-row button { color: var(--blue); font-size: 12px; }
.batch-row button:hover { text-decoration: underline; }
.user-picker { max-height: 240px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.user-check { display: flex; align-items: center; gap: 8px; padding: 7px 6px; border-radius: 6px; font-size: 13px; }
.user-check:hover { background: #f2f6fb; }
.user-check small { color: var(--muted); margin-left: 4px; }
.picker-empty { padding: 18px; text-align: center; color: var(--muted); font-size: 13px; }
.form-actions { display: flex; justify-content: flex-end; margin-top: 14px; }
.history-card { min-width: 0; overflow-x: auto; }
td strong { display: block; margin-bottom: 4px; }
td small { display: block; max-width: 260px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1100px) { .notice-grid { grid-template-columns: 1fr; } }
</style>
