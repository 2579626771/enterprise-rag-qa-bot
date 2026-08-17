<template>
  <main class="feedback-page">
    <div class="feedback-head">
      <div>
        <h1>问题反馈 <span class="pill">处理闭环</span></h1>
        <p>提交使用中遇到的问题，并查看管理员回复与处理结果</p>
      </div>
      <div class="head-actions">
        <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
          <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
        </button>
        <button class="primary lg" type="button" @click="showCreate = true">
          <i class="fa-solid fa-message"></i> 提交反馈
        </button>
      </div>
    </div>

    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="tickets.length === 0" class="table-empty">暂无反馈记录，遇到问题可点击右上角提交</div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th>标题</th>
            <th>状态</th>
            <th>问题描述</th>
            <th>截图</th>
            <th>管理员回复</th>
            <th>更新时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tickets" :key="t.id">
            <td><strong>{{ t.title }}</strong><small>#{{ t.id }}</small></td>
            <td><span :class="['status-badge', t.status]">{{ statusLabel(t.status) }}</span></td>
            <td class="feedback-text">{{ t.content || '—' }}</td>
            <td>
              <div v-if="t.attachments?.length" class="attachment-list compact">
                <button
                  v-for="a in t.attachments"
                  :key="a.id"
                  class="attachment-link"
                  type="button"
                  @click="openAttachment(t, a.id)"
                >
                  <i class="fa-regular fa-image"></i>{{ a.filename }}
                </button>
              </div>
              <span v-else class="muted-cell">—</span>
            </td>
            <td class="feedback-text reply">{{ t.admin_reply || '暂未回复' }}</td>
            <td class="muted-cell">{{ t.updated_at || t.created_at || '—' }}</td>
            <td class="col-op">
              <button
                v-if="t.status === 'resolved'"
                class="op-link"
                type="button"
                :disabled="busyId === t.id"
                @click="onClose(t)"
              >
                <i class="fa-solid fa-check"></i> 确认关闭
              </button>
              <span v-else class="muted-cell">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error feedback-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice feedback-msg">{{ notice }}</p>

    <div v-if="showCreate" class="modal-mask" @click.self="closeCreateModal">
      <div class="modal">
        <div class="modal-head">
          <h3>提交问题反馈</h3>
          <button class="modal-close" type="button" @click="closeCreateModal">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="form-label req">标题</label>
            <input v-model="form.title" class="text-input" maxlength="120" placeholder="如：上传 PDF 后一直处理中" />
          </div>
          <div class="form-row">
            <label class="form-label">问题描述</label>
            <textarea
              v-model="form.content"
              class="textarea"
              rows="5"
              maxlength="4000"
              placeholder="请描述操作步骤、看到的现象、期望结果，便于管理员定位"
            ></textarea>
          </div>
          <div class="form-row">
            <label class="form-label">截图附件</label>
            <input
              class="text-input"
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp,image/gif"
              @change="onPickFiles"
            />
            <p class="attach-hint">最多 {{ maxFiles }} 张，单张不超过 {{ maxFileMb }} MB，支持 PNG/JPG/WebP/GIF。</p>
            <div v-if="selectedFiles.length" class="selected-files">
              <div v-for="(file, idx) in selectedFiles" :key="`${file.name}-${idx}`" class="selected-file">
                <span><i class="fa-regular fa-image"></i>{{ file.name }} · {{ formatSize(file.size) }}</span>
                <button type="button" @click="removeFile(idx)"><i class="fa-solid fa-xmark"></i></button>
              </div>
            </div>
          </div>
          <p v-if="createErr" class="msg error">{{ createErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="closeCreateModal">取消</button>
          <button class="primary" type="button" :disabled="submitting || !form.title.trim()" @click="onCreate">
            {{ submitting ? '提交中…' : '提交反馈' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  closeFeedback,
  createFeedback,
  extractErrorMessage,
  listMyFeedback,
  openFeedbackAttachment,
  uploadFeedbackScreenshots,
  type FeedbackStatus,
  type FeedbackTicket,
} from '../api/client'

const maxFiles = 5
const maxFileMb = 5
const maxFileBytes = maxFileMb * 1024 * 1024
const allowedTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])

const tickets = ref<FeedbackTicket[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const showCreate = ref(false)
const submitting = ref(false)
const createErr = ref('')
const busyId = ref<number | null>(null)
const selectedFiles = ref<File[]>([])
const form = reactive({ title: '', content: '' })

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

function validateFiles(files: File[]): string {
  if (files.length > maxFiles) return `最多只能上传 ${maxFiles} 张截图`
  for (const file of files) {
    if (!allowedTypes.has(file.type)) return `不支持的截图格式：${file.name}`
    if (file.size > maxFileBytes) return `截图「${file.name}」超过 ${maxFileMb} MB`
  }
  return ''
}

function onPickFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  const err = validateFiles(files)
  if (err) {
    createErr.value = err
    return
  }
  selectedFiles.value = files
  createErr.value = ''
}

function removeFile(idx: number) {
  selectedFiles.value = selectedFiles.value.filter((_, i) => i !== idx)
}

function closeCreateModal() {
  showCreate.value = false
  form.title = ''
  form.content = ''
  selectedFiles.value = []
  createErr.value = ''
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    tickets.value = await listMyFeedback()
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  if (submitting.value || !form.title.trim()) return
  const err = validateFiles(selectedFiles.value)
  if (err) {
    createErr.value = err
    return
  }
  submitting.value = true
  createErr.value = ''
  try {
    const created = await createFeedback(form.title.trim(), form.content.trim())
    let attachmentWarning = ''
    if (selectedFiles.value.length) {
      try {
        await uploadFeedbackScreenshots(created.id, selectedFiles.value)
      } catch (e) {
        attachmentWarning = `反馈已提交，但截图上传失败：${extractErrorMessage(e)}`
      }
    }
    closeCreateModal()
    notice.value = attachmentWarning || '反馈已提交，管理员处理后会在这里显示回复'
    await refresh()
    window.setTimeout(() => (notice.value = ''), 4200)
  } catch (e) {
    createErr.value = extractErrorMessage(e)
  } finally {
    submitting.value = false
  }
}

async function openAttachment(ticket: FeedbackTicket, attachmentId: number) {
  error.value = ''
  try {
    const url = await openFeedbackAttachment(ticket.id, attachmentId)
    window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

async function onClose(ticket: FeedbackTicket) {
  busyId.value = ticket.id
  error.value = ''
  try {
    await closeFeedback(ticket.id)
    notice.value = `已关闭反馈「${ticket.title}」`
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
.feedback-page { padding: 26px 30px; overflow-y: auto; }
.feedback-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.feedback-head h1 { margin: 0 0 4px; font-size: 22px; }
.feedback-head p { margin: 0; color: var(--muted); font-size: 13px; }
.head-actions { display: flex; gap: 10px; align-items: center; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.feedback-msg { margin-top: 14px; }
.feedback-text { max-width: 240px; white-space: pre-wrap; line-height: 1.6; color: #3a4147; }
.feedback-text.reply { color: var(--blue); }
td strong { display: block; margin-bottom: 4px; }
td small { color: var(--muted); font-size: 12px; }
.attach-hint { margin: 8px 0 0; color: var(--muted); font-size: 12px; }
.selected-files { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.selected-file { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; color: #3a4147; }
.selected-file span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-file i, .attachment-link i { margin-right: 6px; color: var(--blue); }
.selected-file button { color: #dc2626; }
.attachment-list { display: flex; flex-direction: column; gap: 6px; }
.attachment-list.compact { max-width: 180px; }
.attachment-link { text-align: left; color: var(--blue); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-link:hover { text-decoration: underline; }
</style>
