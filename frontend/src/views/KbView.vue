<template>
  <main class="kb-page">
    <div class="kb-head">
      <div>
        <h1>我的知识库 <span class="pill">{{ used }} / {{ quota }}</span></h1>
        <p>创建与管理你的个人知识库，文档与问答按库隔离</p>
      </div>
      <div class="head-actions">
        <button class="btn-ghost" type="button" @click="showRequest = true">
          <i class="fa-solid fa-paper-plane"></i> 申请更多配额
        </button>
        <button class="primary lg" type="button" :disabled="!canCreate" :title="canCreate ? '' : '已达配额上限，请先申请'" @click="showCreate = true">
          <i class="fa-solid fa-plus"></i> 新建知识库
        </button>
      </div>
    </div>

    <div class="kb-grid">
      <div v-for="kb in kbList" :key="kb.id" class="kb-card">
        <div class="kb-card-top">
          <i class="fa-solid fa-book"></i>
          <div class="kb-card-ops">
            <button class="op-link" type="button" title="编辑知识库" @click="onEdit(kb)">
              <i class="fa-solid fa-pen"></i>
            </button>
            <button class="op-link danger" type="button" title="删除知识库" @click="onDelete(kb)">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </div>
        </div>
        <strong>{{ kb.name }}</strong>
        <p>{{ kb.description || '（无描述）' }}</p>
        <small>创建于 {{ kb.created_at || '—' }}</small>
      </div>
      <div v-if="kbList.length === 0" class="kb-empty">还没有知识库，点右上角「新建知识库」</div>
    </div>

    <!-- 我的申请记录 -->
    <div class="req-section">
      <h2>我的配额申请</h2>
      <table v-if="myRequests.length" class="doc-table">
        <thead>
          <tr><th>申请数量</th><th>理由</th><th>状态</th><th>提交时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in myRequests" :key="r.id">
            <td>+{{ r.amount }}</td>
            <td>{{ r.reason || '—' }}</td>
            <td><span :class="['status-badge', r.status]">{{ statusLabel(r.status) }}</span></td>
            <td class="muted-cell">{{ r.created_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted-cell">暂无申请记录</p>
    </div>

    <p v-if="error" class="msg error kb-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice kb-msg">{{ notice }}</p>

    <!-- 新建知识库弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <div class="modal-head">
          <h3>新建知识库</h3>
          <button class="modal-close" type="button" @click="showCreate = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="form-label req">名称</label>
            <input v-model="form.name" class="text-input" placeholder="如：产品手册、内部制度" />
          </div>
          <div class="form-row">
            <label class="form-label">描述</label>
            <textarea v-model="form.description" class="textarea" rows="3" placeholder="选填"></textarea>
          </div>
          <p v-if="createErr" class="msg error">{{ createErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showCreate = false">取消</button>
          <button class="primary" type="button" :disabled="creating || !form.name.trim()" @click="onCreate">
            {{ creating ? '创建中…' : '确定创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 编辑知识库弹窗 -->
    <div v-if="showEdit" class="modal-mask" @click.self="showEdit = false">
      <div class="modal">
        <div class="modal-head">
          <h3>编辑知识库</h3>
          <button class="modal-close" type="button" @click="showEdit = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="form-label req">名称</label>
            <input v-model="editForm.name" class="text-input" placeholder="如：产品手册、内部制度" />
          </div>
          <div class="form-row">
            <label class="form-label">描述</label>
            <textarea v-model="editForm.description" class="textarea" rows="3" placeholder="选填"></textarea>
          </div>
          <p v-if="editErr" class="msg error">{{ editErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showEdit = false">取消</button>
          <button class="primary" type="button" :disabled="saving || !editForm.name.trim()" @click="onSaveEdit">
            {{ saving ? '保存中…' : '保存修改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 申请配额弹窗 -->
    <div v-if="showRequest" class="modal-mask" @click.self="showRequest = false">
      <div class="modal">
        <div class="modal-head">
          <h3>申请更多知识库配额</h3>
          <button class="modal-close" type="button" @click="showRequest = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="form-label req">申请数量</label>
            <input v-model.number="reqForm.amount" type="number" min="1" class="text-input" />
          </div>
          <div class="form-row">
            <label class="form-label">申请理由</label>
            <textarea v-model="reqForm.reason" class="textarea" rows="3" placeholder="说明业务需要，便于管理员审批"></textarea>
          </div>
          <p v-if="reqErr" class="msg error">{{ reqErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showRequest = false">取消</button>
          <button class="primary" type="button" :disabled="submitting || reqForm.amount < 1" @click="onSubmitRequest">
            {{ submitting ? '提交中…' : '提交申请' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  createKb,
  updateKb,
  deleteKb,
  submitQuotaRequest,
  myQuotaRequests,
  extractErrorMessage,
  type KnowledgeBase,
  type QuotaRequest,
} from '../api/client'
import { useKnowledgeBase } from '../composables/useKnowledgeBase'

const { kbList, quota, used, canCreate, refreshKbs, currentKbId, selectKb } = useKnowledgeBase()

const error = ref('')
const notice = ref('')
const myRequests = ref<QuotaRequest[]>([])

const showCreate = ref(false)
const creating = ref(false)
const createErr = ref('')
const form = reactive({ name: '', description: '' })

const showEdit = ref(false)
const saving = ref(false)
const editErr = ref('')
const editingId = ref<number | null>(null)
const editForm = reactive({ name: '', description: '' })

const showRequest = ref(false)
const submitting = ref(false)
const reqErr = ref('')
const reqForm = reactive({ amount: 1, reason: '' })

function statusLabel(s: string): string {
  return s === 'approved' ? '已通过' : s === 'rejected' ? '已驳回' : '待审批'
}

async function loadRequests() {
  try {
    myRequests.value = await myQuotaRequests()
  } catch {
    // 忽略
  }
}

async function onCreate() {
  if (creating.value || !form.name.trim()) return
  creating.value = true
  createErr.value = ''
  try {
    const kb = await createKb(form.name.trim(), form.description.trim())
    showCreate.value = false
    form.name = ''
    form.description = ''
    notice.value = '知识库创建成功'
    await refreshKbs()
    selectKb(kb.id)
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    createErr.value = extractErrorMessage(e)
  } finally {
    creating.value = false
  }
}

function onEdit(kb: KnowledgeBase) {
  editingId.value = kb.id
  editForm.name = kb.name
  editForm.description = kb.description || ''
  editErr.value = ''
  showEdit.value = true
}

async function onSaveEdit() {
  if (saving.value || editingId.value === null || !editForm.name.trim()) return
  saving.value = true
  editErr.value = ''
  try {
    await updateKb(editingId.value, editForm.name.trim(), editForm.description.trim())
    showEdit.value = false
    notice.value = '知识库已更新'
    await refreshKbs()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    editErr.value = extractErrorMessage(e)
  } finally {
    saving.value = false
  }
}

async function onDelete(kb: KnowledgeBase) {
  if (!confirm(`确定删除知识库「${kb.name}」？其中所有文档与向量都会被清除，且不可恢复。`)) return
  error.value = ''
  try {
    await deleteKb(kb.id)
    notice.value = `已删除知识库「${kb.name}」`
    await refreshKbs()
    // 若删的是当前库，切到剩下的第一个
    if (currentKbId.value === kb.id && kbList.value.length) {
      selectKb(kbList.value[0].id)
    }
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

async function onSubmitRequest() {
  if (submitting.value || reqForm.amount < 1) return
  submitting.value = true
  reqErr.value = ''
  try {
    await submitQuotaRequest(reqForm.amount, reqForm.reason.trim())
    showRequest.value = false
    reqForm.amount = 1
    reqForm.reason = ''
    notice.value = '申请已提交，等待管理员审批'
    await loadRequests()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    reqErr.value = extractErrorMessage(e)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  if (kbList.value.length === 0) {
    try {
      await refreshKbs()
    } catch (e) {
      error.value = extractErrorMessage(e)
    }
  }
  await loadRequests()
})
</script>

<style scoped>
.kb-page { padding: 26px 30px; overflow-y: auto; }
.kb-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.kb-head h1 { margin: 0 0 4px; font-size: 22px; }
.kb-head p { margin: 0; color: var(--muted); font-size: 13px; }
.head-actions { display: flex; gap: 10px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; margin-bottom: 26px; }
.kb-card { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
.kb-card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.kb-card-top > i { font-size: 22px; color: var(--blue); }
.kb-card-ops { display: flex; gap: 6px; }
.kb-card strong { display: block; font-size: 15px; margin-bottom: 4px; }
.kb-card p { margin: 0 0 8px; color: var(--muted); font-size: 13px; min-height: 18px; }
.kb-card small { color: #9aa2a8; font-size: 12px; }
.kb-empty { color: var(--muted); grid-column: 1 / -1; padding: 30px; text-align: center; border: 1px dashed var(--line); border-radius: 12px; }
.req-section { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 18px; }
.req-section h2 { margin: 0 0 12px; font-size: 16px; }
.text-input { width: 100%; height: 40px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; outline: none; }
.text-input:focus { border-color: var(--blue-2); }
.status-badge.pending { background: #fdeede; color: var(--orange); }
.status-badge.approved { background: #e3f5e8; color: #2e9e5b; }
.status-badge.rejected { background: #fde8e8; color: #d9534f; }
.kb-msg { margin-top: 14px; }
</style>
