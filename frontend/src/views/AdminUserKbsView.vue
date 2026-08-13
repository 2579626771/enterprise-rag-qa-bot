<template>
  <main class="admin-kb">
    <!-- 面包屑 -->
    <div class="crumb">
      <button class="crumb-back" type="button" @click="goUsers">
        <i class="fa-solid fa-arrow-left"></i> 返回用户列表
      </button>
      <span class="crumb-sep">/</span>
      <span class="crumb-cur">
        <i class="fa-solid fa-user"></i>
        {{ user ? (user.display_name || user.username) : '用户' }} 的知识库
      </span>
    </div>

    <div class="akb-head sub">
      <div>
        <h1>{{ user ? (user.display_name || user.username) : '加载中…' }}</h1>
        <p v-if="user">
          @{{ user.username }} · 用户ID #{{ user.id }} ·
          配额 {{ ownKbs.length }} / {{ user.role === 'admin' ? '∞' : (user.kb_quota ?? 0) }}
        </p>
      </div>
      <button v-if="user && user.role !== 'admin'" class="btn-ghost" type="button" @click="openQuota">
        <i class="fa-solid fa-sliders"></i> 调整配额
      </button>
    </div>

    <!-- 单行筛选栏：一个综合搜索框 -->
    <div class="filter-toolbar">
      <el-input v-model="f.kw" class="ft-search" clearable placeholder="搜索知识库名 / 描述">
        <template #prefix><i class="fa-solid fa-magnifying-glass" /></template>
      </el-input>
      <span class="ft-spacer" />
      <span class="ft-count">共 {{ filteredKbs.length }} 个知识库（全部 {{ ownKbs.length }}）</span>
    </div>

    <div class="table-card">
      <table class="doc-table">
        <thead>
          <tr>
            <th>知识库</th>
            <th>描述</th>
            <th>创建时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="4" class="table-empty">加载中…</td></tr>
          <tr v-else-if="filteredKbs.length === 0"><td colspan="4" class="table-empty">该用户暂无匹配的知识库</td></tr>
          <tr v-for="kb in filteredKbs" v-else :key="kb.id">
            <td>
              <div class="doc-cell">
                <span class="doc-type-ico"><i class="fa-solid fa-book"></i></span>
                <div>
                  <strong>{{ kb.name }}</strong>
                  <small>ID #{{ kb.id }}</small>
                </div>
              </div>
            </td>
            <td class="muted-cell">{{ kb.description || '—' }}</td>
            <td class="muted-cell">{{ kb.created_at || '—' }}</td>
            <td class="col-op">
              <button class="op-link" type="button" @click="viewDocs(kb)">
                <i class="fa-regular fa-eye"></i> 查看文档
              </button>
              <button class="op-link danger" type="button" @click="onDelete(kb)">
                <i class="fa-solid fa-trash-can"></i> 删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error akb-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice akb-msg">{{ notice }}</p>

    <!-- 调整配额弹窗 -->
    <div v-if="showQuota && user" class="modal-mask" @click.self="showQuota = false">
      <div class="modal">
        <div class="modal-head">
          <h3>调整配额 · {{ user.display_name || user.username }}</h3>
          <button class="modal-close" type="button" @click="showQuota = false"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <p class="quota-hint">当前已用 <b>{{ ownKbs.length }}</b> 个知识库，配额不能低于此值。</p>
          <div class="form-row">
            <label class="form-label req">新的配额上限</label>
            <input v-model.number="quotaValue" type="number" :min="ownKbs.length" class="text-input" />
          </div>
          <p v-if="quotaErr" class="msg error">{{ quotaErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showQuota = false">取消</button>
          <button class="primary" type="button" :disabled="quotaSaving || quotaValue < ownKbs.length" @click="onSaveQuota">
            {{ quotaSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  listKbs,
  listUsers,
  deleteKb,
  setUserQuota,
  extractErrorMessage,
  type KnowledgeBase,
  type AuthUser,
} from '../api/client'

const props = defineProps<{ userId: string }>()
const router = useRouter()
const uid = computed(() => Number(props.userId))

const user = ref<AuthUser | null>(null)
const allKbs = ref<KnowledgeBase[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')

const f = reactive({ kw: '' })

const showQuota = ref(false)
const quotaValue = ref(0)
const quotaSaving = ref(false)
const quotaErr = ref('')

const ownKbs = computed(() => allKbs.value.filter((k) => k.owner_id === uid.value))
const filteredKbs = computed(() => {
  const kw = f.kw.trim().toLowerCase()
  if (!kw) return ownKbs.value
  return ownKbs.value.filter((k) => {
    const hay = `${k.name} ${k.description || ''}`.toLowerCase()
    return hay.includes(kw)
  })
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [kbRes, users] = await Promise.all([listKbs(true), listUsers()])
    allKbs.value = kbRes.kbs
    user.value = users.find((u) => u.id === uid.value) ?? null
    if (!user.value) error.value = '用户不存在或已被删除'
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function goUsers() {
  router.push({ name: 'adminkb' })
}

function viewDocs(kb: KnowledgeBase) {
  router.push({ name: 'admin-kb-docs', params: { userId: props.userId, kbId: kb.id } })
}

async function onDelete(kb: KnowledgeBase) {
  if (!confirm(`确定删除「${kb.name}」？其中所有文档与向量都会被清除，不可恢复。`)) return
  error.value = ''
  try {
    await deleteKb(kb.id)
    notice.value = `已删除知识库「${kb.name}」`
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

function openQuota() {
  if (!user.value) return
  quotaValue.value = user.value.kb_quota ?? 0
  quotaErr.value = ''
  showQuota.value = true
}

async function onSaveQuota() {
  if (!user.value || quotaSaving.value) return
  if (quotaValue.value < ownKbs.value.length) {
    quotaErr.value = `配额不能低于已用的知识库数（${ownKbs.value.length}）`
    return
  }
  quotaSaving.value = true
  quotaErr.value = ''
  try {
    await setUserQuota(user.value.id, quotaValue.value)
    notice.value = `配额已设为 ${quotaValue.value}`
    showQuota.value = false
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    quotaErr.value = extractErrorMessage(e)
  } finally {
    quotaSaving.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.admin-kb { padding: 26px 30px; overflow-y: auto; }
.akb-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.akb-head.sub { margin-top: 6px; }
.akb-head h1 { margin: 0 0 4px; font-size: 22px; }
.akb-head p { margin: 0; color: var(--muted); font-size: 13px; }
.akb-msg { margin-top: 14px; }
.row-hint { color: var(--muted); font-size: 13px; margin-bottom: 12px; }

.crumb { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; font-size: 13px; }
.crumb-back {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--blue-3); color: var(--blue);
  border: none; border-radius: 8px; padding: 6px 12px; cursor: pointer; transition: background .15s;
}
.crumb-back:hover { background: #dbe6f2; }
.crumb-sep { color: var(--muted); }
.crumb-cur { display: inline-flex; align-items: center; gap: 6px; color: #3a4147; font-weight: 600; }

.quota-hint { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
.quota-hint b { color: var(--blue); }
.text-input { width: 100%; height: 40px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; outline: none; }
.text-input:focus { border-color: var(--blue-2); }
</style>
