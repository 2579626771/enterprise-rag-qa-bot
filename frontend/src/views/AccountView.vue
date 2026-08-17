<template>
  <main class="account">
    <div class="account-head">
      <div>
        <h1>账户管理 <span class="pill">仅管理员</span></h1>
        <p>创建与管理系统用户账号</p>
      </div>
      <button class="primary lg" type="button" @click="showCreate = true">
        <i class="fa-solid fa-user-plus"></i> 新建用户
      </button>
    </div>

    <div class="filter-toolbar account-filter">
      <input
        v-model="searchText"
        class="text-input ft-search"
        placeholder="搜索用户名 / 显示名 / 用户ID"
      />
      <select v-model="roleFilter" class="select ft-select">
        <option value="all">全部角色</option>
        <option value="admin">管理员</option>
        <option value="user">普通用户</option>
      </select>
      <span class="ft-count">共 {{ filteredUsers.length }} / {{ users.length }} 个用户</span>
    </div>

    <div class="table-card">
      <div v-if="loading" class="table-empty">加载中…</div>
      <div v-else-if="filteredUsers.length === 0" class="table-empty">没有匹配的用户</div>
      <table v-else class="doc-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>显示名</th>
            <th>角色</th>
            <th>登录安全</th>
            <th>创建时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in filteredUsers" :key="u.id">
            <td><strong>{{ u.username }}</strong></td>
            <td>{{ u.display_name }}</td>
            <td>
              <span :class="['role-tag', u.role === 'admin' ? 'admin' : 'user']">
                {{ u.role === 'admin' ? '管理员' : '普通用户' }}
              </span>
            </td>
            <td>
              <span :class="['security-tag', securityState(u).type]">{{ securityState(u).label }}</span>
            </td>
            <td class="muted-cell">{{ u.created_at || '—' }}</td>
            <td class="col-op">
              <button
                class="op-link"
                type="button"
                :disabled="u.id === currentUser?.id"
                :title="u.id === currentUser?.id ? '请在个人中心修改自己的密码' : '重置密码'"
                @click="openReset(u)"
              >
                <i class="fa-solid fa-key"></i> 重置密码
              </button>
              <button
                class="op-link danger"
                type="button"
                :disabled="u.id === currentUser?.id"
                :title="u.id === currentUser?.id ? '不能删除自己' : '删除用户'"
                @click="onDelete(u)"
              >
                <i class="fa-solid fa-trash-can"></i> 删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="error" class="msg error account-msg">{{ error }}</p>
    <p v-if="notice" class="msg notice account-msg">{{ notice }}</p>

    <!-- 重置密码弹窗 -->
    <div v-if="resetUser" class="modal-mask" @click.self="resetUser = null">
      <div class="modal">
        <div class="modal-head">
          <h3>重置密码 · {{ resetUser.display_name || resetUser.username }}</h3>
          <button class="modal-close" type="button" @click="resetUser = null">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="detail-body">
          <p class="reset-hint">请把临时密码安全告知用户。默认要求用户下次登录后先修改密码。</p>
          <div class="form-row">
            <label class="form-label req">新密码</label>
            <input v-model="resetForm.password" type="password" class="text-input" placeholder="至少 8 位" />
          </div>
          <div class="form-row">
            <label class="form-label req">确认新密码</label>
            <input v-model="resetForm.password2" type="password" class="text-input" placeholder="再次输入新密码" />
          </div>
          <label class="check-row">
            <input v-model="resetForm.force_change" type="checkbox" />
            <span>要求用户下次登录后修改密码</span>
          </label>
          <p v-if="resetErr" class="msg error">{{ resetErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="resetUser = null">取消</button>
          <button class="primary" type="button" :disabled="resetting" @click="onResetPassword">
            {{ resetting ? '重置中…' : '确定重置' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新建用户弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <div class="modal-head">
          <h3>新建用户</h3>
          <button class="modal-close" type="button" @click="showCreate = false">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div class="detail-body">
          <div class="form-row">
            <label class="form-label req">用户名</label>
            <input v-model="form.username" class="text-input" placeholder="登录用户名" />
          </div>
          <div class="form-row">
            <label class="form-label">显示名</label>
            <input v-model="form.display_name" class="text-input" placeholder="选填，默认同用户名" />
          </div>
          <div class="form-row">
            <label class="form-label req">密码</label>
            <input v-model="form.password" type="password" class="text-input" placeholder="登录密码" />
          </div>
          <div class="form-row">
            <label class="form-label req">角色</label>
            <select v-model="form.role" class="select full">
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <p v-if="createErr" class="msg error">{{ createErr }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" type="button" @click="showCreate = false">取消</button>
          <button class="primary" type="button" :disabled="creating || !canCreate" @click="onCreate">
            {{ creating ? '创建中…' : '确定创建' }}
          </button>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  listUsers,
  createUser,
  deleteUser,
  resetUserPassword,
  extractErrorMessage,
  type AuthUser,
} from '../api/client'
import { useAuth } from '../composables/useAuth'

const { user: currentUser } = useAuth()

const users = ref<AuthUser[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const searchText = ref('')
const roleFilter = ref<'all' | 'admin' | 'user'>('all')

const showCreate = ref(false)
const creating = ref(false)
const createErr = ref('')
const form = reactive({ username: '', password: '', display_name: '', role: 'user' })

const resetUser = ref<AuthUser | null>(null)
const resetting = ref(false)
const resetErr = ref('')
const resetForm = reactive({ password: '', password2: '', force_change: true })

const canCreate = computed(() => !!form.username.trim() && !!form.password)
const filteredUsers = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return users.value.filter((u) => {
    if (roleFilter.value !== 'all' && u.role !== roleFilter.value) return false
    if (!keyword) return true
    return [String(u.id), u.username, u.display_name || '']
      .some((value) => value.toLowerCase().includes(keyword))
  })
})

function securityState(u: AuthUser): { type: string; label: string } {
  if (u.locked_until && u.locked_until !== '—') return { type: 'locked', label: `锁定至 ${u.locked_until}` }
  if (u.force_password_change) return { type: 'force', label: '需改密' }
  return { type: 'ok', label: '正常' }
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    users.value = await listUsers()
  } catch (e) {
    error.value = extractErrorMessage(e)
  } finally {
    loading.value = false
  }
}

async function onCreate() {
  if (creating.value || !canCreate.value) return
  creating.value = true
  createErr.value = ''
  try {
    await createUser({
      username: form.username.trim(),
      password: form.password,
      role: form.role,
      display_name: form.display_name.trim(),
    })
    showCreate.value = false
    form.username = ''
    form.password = ''
    form.display_name = ''
    form.role = 'user'
    notice.value = '用户创建成功'
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    createErr.value = extractErrorMessage(e)
  } finally {
    creating.value = false
  }
}

function openReset(u: AuthUser) {
  if (u.id === currentUser.value?.id) return
  resetUser.value = u
  resetForm.password = ''
  resetForm.password2 = ''
  resetForm.force_change = true
  resetErr.value = ''
}

async function onResetPassword() {
  if (!resetUser.value || resetting.value) return
  if (resetForm.password.length < 8) {
    resetErr.value = '密码至少 8 位'
    return
  }
  if (resetForm.password !== resetForm.password2) {
    resetErr.value = '两次输入的密码不一致'
    return
  }
  resetting.value = true
  resetErr.value = ''
  try {
    await resetUserPassword(resetUser.value.id, resetForm.password, resetForm.force_change)
    notice.value = `已重置用户「${resetUser.value.username}」的密码`
    resetUser.value = null
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    resetErr.value = extractErrorMessage(e)
  } finally {
    resetting.value = false
  }
}

async function onDelete(u: AuthUser) {
  if (u.id === currentUser.value?.id) return
  if (!confirm(`确定删除用户「${u.username}」？`)) return
  error.value = ''
  try {
    await deleteUser(u.id)
    notice.value = `已删除用户「${u.username}」`
    await refresh()
    window.setTimeout(() => (notice.value = ''), 2600)
  } catch (e) {
    error.value = extractErrorMessage(e)
  }
}

onMounted(refresh)
</script>

<style scoped>
.account {
  padding: 26px 30px;
  overflow-y: auto;
}
.account-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.account-head h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.account-head p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}
.pill {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--blue-3);
  color: var(--blue);
  vertical-align: middle;
}
.role-tag {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
}
.role-tag.admin {
  background: #fdeede;
  color: var(--orange);
}
.role-tag.user {
  background: var(--blue-3);
  color: var(--blue);
}
.security-tag {
  display: inline-flex;
  padding: 3px 10px;
  border-radius: 10px;
  font-size: 12px;
}
.security-tag.ok { background: #ecfdf5; color: #1d6f42; }
.security-tag.force { background: #fff6e5; color: #b8791a; }
.security-tag.locked { background: #fde8e8; color: #d9534f; }
.reset-hint { margin: 0 0 14px; color: var(--muted); font-size: 13px; }
.check-row { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; font-size: 13px; color: #35433f; }
.text-input {
  width: 100%;
  height: 40px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0 12px;
  outline: none;
}
.text-input:focus {
  border-color: var(--blue-2);
}
.account-filter {
  margin-bottom: 14px;
}
.account-filter .text-input {
  width: 320px;
}
.account-msg {
  margin-top: 14px;
}
.op-link:disabled { color: #b7bec4; cursor: not-allowed; }
.op-link:disabled:hover { text-decoration: none; }
</style>
