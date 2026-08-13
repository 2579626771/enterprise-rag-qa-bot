<template>
  <main class="admin-kb">
    <div class="akb-head">
      <div>
        <h1>知识库管理 <span class="pill">仅管理员</span></h1>
        <p>按用户查看与管理全部知识库及其文档、配额</p>
      </div>
      <button class="btn-ghost" type="button" :disabled="loading" @click="refresh">
        <i class="fa-solid fa-rotate" :class="{ spin: loading }"></i> 刷新
      </button>
    </div>

    <!-- 单行筛选栏：枚举下拉 + 一个综合搜索框 -->
    <div class="filter-toolbar">
      <el-select v-model="f.role" class="ft-select" filterable clearable placeholder="全部角色">
        <el-option label="管理员" value="admin" />
        <el-option label="普通用户" value="user" />
      </el-select>
      <el-input v-model="f.kw" class="ft-search" clearable placeholder="搜索用户名 / 显示名 / 用户ID">
        <template #prefix><i class="fa-solid fa-magnifying-glass" /></template>
      </el-input>
      <span class="ft-spacer" />
      <span class="ft-count">共 {{ filteredUsers.length }} 位用户（全部 {{ users.length }}）</span>
    </div>

    <div class="table-card">
      <table class="doc-table">
        <thead>
          <tr>
            <th class="sortable" :class="{ active: sortKey === 'name' }" @click="toggleSort('name')">
              用户 <i class="fa-solid sort-ico" :class="sortIcon('name')"></i>
            </th>
            <th class="sortable" :class="{ active: sortKey === 'id' }" @click="toggleSort('id')">
              用户ID <i class="fa-solid sort-ico" :class="sortIcon('id')"></i>
            </th>
            <th>角色</th>
            <th class="sortable" :class="{ active: sortKey === 'quota' }" @click="toggleSort('quota')">
              知识库配额 <i class="fa-solid sort-ico" :class="sortIcon('quota')"></i>
            </th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="5" class="table-empty">加载中…</td>
          </tr>
          <tr v-else-if="filteredUsers.length === 0">
            <td colspan="5" class="table-empty">没有匹配的用户</td>
          </tr>
          <tr v-for="u in filteredUsers" v-else :key="u.id">
            <td>
              <div class="doc-cell">
                <span class="doc-type-ico"><i class="fa-solid fa-user"></i></span>
                <div>
                  <strong>{{ u.display_name || u.username }}</strong>
                  <small>@{{ u.username }}</small>
                </div>
              </div>
            </td>
            <td class="muted-cell">#{{ u.id }}</td>
            <td>
              <span :class="['role-tag', u.role === 'admin' ? 'admin' : 'user']">
                {{ u.role === 'admin' ? '管理员' : '普通用户' }}
              </span>
            </td>
            <td>
              <span class="quota-cell">
                <b>{{ usedCount(u.id) }}</b> / {{ u.role === 'admin' ? '∞' : (u.kb_quota ?? 0) }}
              </span>
            </td>
            <td class="col-op">
              <button class="op-link" type="button" @click="manage(u)">
                <i class="fa-solid fa-folder-open"></i> 管理知识库
              </button>
              <button
                class="op-link"
                type="button"
                :disabled="u.role === 'admin'"
                :title="u.role === 'admin' ? '管理员不受配额限制' : ''"
                @click="openQuota(u)"
              >
                <i class="fa-solid fa-sliders"></i> 调整配额
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error akb-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice akb-msg">{{ notice }}</p>

    <!-- 调整配额弹窗 -->
    <div v-if="quotaUser" class="modal-mask" @click.self="quotaUser = null">
      <div class="modal">
        <div class="modal-head">
          <h3>调整配额 · {{ quotaUser.display_name || quotaUser.username }}</h3>
          <button class="modal-close" type="button" @click="quotaUser = null"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="detail-body">
          <p class="quota-hint">当前已用 <b>{{ usedCount(quotaUser.id) }}</b> 个知识库，配额不能低于此值。</p>
          <div class="form-row">
            <label class="form-label req">新的配额上限</label>
            <input v-model.number="quotaValue" type="number" :min="usedCount(quotaUser.id)" class="text-input" />
          </div>
          <p v-if="quotaErr" class="msg error">{{ quotaErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="quotaUser = null">取消</button>
          <button class="primary" type="button" :disabled="quotaSaving || quotaValue < usedCount(quotaUser.id)" @click="onSaveQuota">
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
  setUserQuota,
  extractErrorMessage,
  type KnowledgeBase,
  type AuthUser,
} from '../api/client'

const router = useRouter()

const kbs = ref<KnowledgeBase[]>([])
const users = ref<AuthUser[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')

// 筛选：一个综合搜索框(kw) + 角色下拉(role)
const f = reactive({ kw: '', role: '' })

// 排序
type SortKey = 'name' | 'id' | 'quota'
const sortKey = ref<SortKey>('id')
const sortAsc = ref(true)
function toggleSort(k: SortKey) {
  if (sortKey.value === k) sortAsc.value = !sortAsc.value
  else {
    sortKey.value = k
    sortAsc.value = true
  }
}
function sortIcon(k: SortKey) {
  if (sortKey.value !== k) return 'fa-sort'
  return sortAsc.value ? 'fa-sort-up' : 'fa-sort-down'
}

// 配额弹窗
const quotaUser = ref<AuthUser | null>(null)
const quotaValue = ref(0)
const quotaSaving = ref(false)
const quotaErr = ref('')

function usedCount(userId: number): number {
  return kbs.value.filter((k) => k.owner_id === userId).length
}

const filteredUsers = computed(() => {
  const kw = f.kw.trim().toLowerCase()
  let list = users.value.filter((u) => {
    if (f.role && u.role !== f.role) return false
    if (kw) {
      const hay = `${u.username} ${u.display_name || ''} ${u.id}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
  list = [...list].sort((a, b) => {
    let r = 0
    if (sortKey.value === 'name') r = (a.display_name || a.username).localeCompare(b.display_name || b.username)
    else if (sortKey.value === 'id') r = a.id - b.id
    else if (sortKey.value === 'quota') r = usedCount(a.id) - usedCount(b.id)
    return sortAsc.value ? r : -r
  })
  return list
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [kbRes, userList] = await Promise.all([listKbs(true), listUsers()])
    kbs.value = kbRes.kbs
    users.value = userList
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

function manage(u: AuthUser) {
  router.push({ name: 'admin-user-kbs', params: { userId: u.id } })
}

function openQuota(u: AuthUser) {
  quotaUser.value = u
  quotaValue.value = u.kb_quota ?? 0
  quotaErr.value = ''
}

async function onSaveQuota() {
  if (!quotaUser.value || quotaSaving.value) return
  const used = usedCount(quotaUser.value.id)
  if (quotaValue.value < used) {
    quotaErr.value = `配额不能低于已用的知识库数（${used}）`
    return
  }
  quotaSaving.value = true
  quotaErr.value = ''
  try {
    await setUserQuota(quotaUser.value.id, quotaValue.value)
    notice.value = `已将「${quotaUser.value.display_name || quotaUser.value.username}」的配额设为 ${quotaValue.value}`
    quotaUser.value = null
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
.akb-head h1 { margin: 0 0 4px; font-size: 22px; }
.akb-head p { margin: 0; color: var(--muted); font-size: 13px; }
.pill { font-size: 12px; padding: 2px 10px; border-radius: 10px; background: var(--blue-3); color: var(--blue); vertical-align: middle; }
.akb-msg { margin-top: 14px; }
.row-hint { color: var(--muted); font-size: 13px; margin-bottom: 12px; }

.role-tag { font-size: 12px; padding: 3px 10px; border-radius: 10px; }
.role-tag.admin { background: #fdeede; color: var(--orange); }
.role-tag.user { background: var(--blue-3); color: var(--blue); }
.quota-cell { font-size: 13px; color: #3a4147; }
.quota-cell b { color: var(--blue); }

.quota-hint { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
.quota-hint b { color: var(--blue); }
.text-input { width: 100%; height: 40px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; outline: none; }
.text-input:focus { border-color: var(--blue-2); }
.op-link:disabled { color: #b7bec4; cursor: not-allowed; }
.op-link:disabled:hover { text-decoration: none; }
</style>
